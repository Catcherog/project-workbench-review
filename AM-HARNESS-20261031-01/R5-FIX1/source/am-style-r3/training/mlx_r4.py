"""R4 local MLX preflight; real workers require an explicit --execute.

The parent imports no MLX. Fit must exit and release memory before a separate
interpreter loads the saved adapter. No production/model install/deploy path.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from training.common import TrainingInputError, file_hash, object_hash, read_json
from training.mlx_r4_contracts import inventory, validate_base, validate_environment, validate_plan
from training.mlx_r4_resources import validate_service_paths
from training.mlx_r4_runtime import atomic_json, code_hashes


def preflight(manifest, config):
    checks, blockers = {}, []
    for name, fn in (("base", lambda: validate_base(manifest)),
                     ("environment", lambda: validate_environment(manifest)),
                     ("service_paths", lambda: validate_service_paths(manifest)),
                     ("data_plan", lambda: validate_plan(config))):
        try:
            value = fn()
            if name == "data_plan":
                value = {"train": len(value[0]), "dev": len(value[1]), "stage": config["stage"], "passes": 1}
            if name == "service_paths":
                value = {"configured_existing_original_paths": True, "lease_acquired": False, "service_probed": False}
            checks[name] = value
        except (TrainingInputError, OSError, ValueError, KeyError, TypeError) as exc:
            blockers.append({"check": name, "reason": str(exc)})
    return {"schema": "am-style-mlx-r4-preflight/1", "ready_for_runtime_checks": not blockers,
            "checks": checks, "blockers": blockers, "manifest_sha256": object_hash(manifest),
            "config_sha256": object_hash(config), "code_sha256": code_hashes(),
            "model_loading": False, "training_executed": False, "numeric_kernel_validation": "not_run",
            "effectiveness": "not_established"}


def _group_gone(pid):
    try:
        os.killpg(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def execute_worker(kind, request_path, timeout):
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    argv = [sys.executable, "-m", "training.mlx_r4", "--worker", kind, "--request", str(request_path), "--execute"]
    with (request_path.parent / f"{kind}.log").open("wb") as log:
        process = subprocess.Popen(argv, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
                code = process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    code = None
        stopped = code is not None and _group_gone(process.pid)
        return {"phase": kind, "attempted": True, "pid": process.pid, "exit_code": code,
                "timed_out": timed_out, "stop_confirmed": stopped,
                "status": "completed" if stopped and code == 0 and not timed_out else "failed_or_stop_unconfirmed"}


def execute_phases(request_path, timeout, *, runner=execute_worker):
    """Never load a second model while the first worker may still be alive."""
    fit = runner("fit", request_path, timeout)
    if fit["status"] != "completed" or fit.get("stop_confirmed") is not True:
        return [fit, {"phase": "reload", "attempted": False, "status": "skipped_fit_not_completed_or_stop_unconfirmed"}]
    return [fit, runner("reload", request_path, timeout)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--config")
    parser.add_argument("--output", help="New absolute experiment directory; required for --execute")
    parser.add_argument("--report", help="New metadata-only preflight JSON path")
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--worker", choices=("fit", "reload"), help=argparse.SUPPRESS)
    parser.add_argument("--request", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        if not args.execute or not args.request:
            raise TrainingInputError("Internal workers also require an explicit execute request")
        from training.mlx_r4_runtime import run_worker
        return run_worker(args.worker, args.request)
    if args.inventory:
        if args.execute:
            raise TrainingInputError("Inventory does not execute models")
        print(json.dumps(inventory(), ensure_ascii=False, indent=2))
        return 0
    if not args.manifest or not args.config:
        raise TrainingInputError("Supply the sealed base manifest and explicit stage config")
    manifest, config = read_json(args.manifest), read_json(args.config)
    report = preflight(manifest, config)
    if args.report:
        path = Path(args.report)
        if path.exists():
            raise TrainingInputError("Never overwrite a previous preflight report")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.execute:
        return 0 if report["ready_for_runtime_checks"] else 2
    if not report["ready_for_runtime_checks"]:
        raise TrainingInputError("Runtime execution is blocked by the reported preflight findings")
    output = Path(args.output or "")
    if not args.output or not output.is_absolute() or output.exists():
        raise TrainingInputError("Use a new absolute run directory; existing runs are immutable")
    model_root = Path(manifest["local_model_path"]).resolve()
    if output.resolve().is_relative_to(model_root):
        raise TrainingInputError("Training output must not modify the sealed model directory")
    protected_roots = {Path(value).resolve().parent for value in manifest["service"].values() if isinstance(value, str) and value.startswith("/")}
    protected_roots.update(Path(name).resolve().parent for name in manifest["service"]["protected_config_files"])
    if any(output.resolve().is_relative_to(root) for root in protected_roots):
        raise TrainingInputError("Training output must not be inside original service state directories")
    output.mkdir(parents=True)
    request = {"schema": "am-style-mlx-r4-request/1", "manifest": manifest, "config": config, "code_sha256": code_hashes()}
    request_path = output / "request.json"
    atomic_json(request_path, request)
    atomic_json(output / "preflight.json", report)
    phases = execute_phases(request_path, config["worker_timeout_seconds"])
    complete = all(phase.get("status") == "completed" and phase.get("stop_confirmed") is True for phase in phases)
    if complete:
        fit_record, reload_record = read_json(output / "fit.json"), read_json(output / "reload.json")
        complete = (fit_record.get("training_completed") is True and reload_record.get("fresh_load_verified") is True
                    and fit_record.get("request_sha256") == object_hash(request)
                    and reload_record.get("request_sha256") == object_hash(request)
                    and reload_record.get("fit_record_sha256") == file_hash(output / "fit.json"))
    evidence_names = ("request.json", "fit.json", "reload.json", "kernel-validation.json", "steps.json", "adapters.safetensors", "adapter_config.json")
    atomic_json(output / "result.json", {"schema": "am-style-mlx-r4-result/1", "request_sha256": object_hash(request),
                "phases": phases, "mechanics_closed": complete, "quality_conclusion": "not_established",
                "files_sha256": {name: file_hash(output / name) for name in evidence_names if (output / name).is_file()},
                "production_changed": False, "business_acceptance": False})
    return 0 if complete else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainingInputError as exc:
        raise SystemExit(f"R4 MLX blocked: {exc}")
