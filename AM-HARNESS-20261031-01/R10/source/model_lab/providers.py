"""Real provider adapters with original host ownership and fail-closed pins.

Q8 reuses R5's protected queue. MLX submits eval-mlx to the original live
consumer; its TrainingWindow/OriginalLease owns all lifecycle and resource
checks. This module never constructs a consumer, unloads a model, or trains.
Codex uses the original provider's real capability-proof validator, while
retaining stdout/stderr/request bytes in the experiment instead of temp files.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from .core import (LabError, canonical, empty_measurements, file_sha, measured,
                   private_dir, read_json, read_jsonl, resolve_ref, seal, sha,
                   text_sha, utc, validate_manifest, write_json)

BASE_PINS = {
    "codex_cli": ["am-conversation-r1/src/am_style/providers.py", "am-conversation-r1/src/am_style/contracts.py"],
    "production_q8": ["am-style-r5/src/am_style_r5/runners.py", "am-style-r5/src/am_style_r5/evaluation.py"],
    "mlx_base": ["am-integrated-r6/tools/training_control.py", "local-qwen3.8/feishu-bridge/am_training_control.py",
                 "am-integrated-r6/am_training_window/native_eval.py", "am-integrated-r6/am_training_window/window.py"],
    "mlx_adapter": ["am-integrated-r6/tools/training_control.py", "local-qwen3.8/feishu-bridge/am_training_control.py",
                    "am-integrated-r6/am_training_window/native_eval.py", "am-integrated-r6/am_training_window/window.py"],
}


def _roots(arm):
    runtime = arm.get("runtime", {})
    root = Path(runtime.get("source_root", ""))
    if not root.is_absolute() or not root.is_dir():
        raise LabError("absolute_existing_original_source_root_required")
    pins = runtime.get("source_pins", {})
    for relative in BASE_PINS.get(arm["kind"], []):
        if relative not in pins:
            raise LabError("original_source_pin_required:" + relative)
    for relative, digest in pins.items():
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()) or file_sha(path) != digest:
            raise LabError("original_source_changed:" + relative)
    paths = [root / "am-style-r5/src", root / "am-conversation-r1/src",
             root / "am-style-r3", root / "am-integrated-r6"]
    for path in reversed(paths):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    # Imports cached from a different checkout must not silently change identity.
    for module in ("am_style", "am_style_r5", "am_training_window", "training"):
        loaded = sys.modules.get(module)
        actual = getattr(loaded, "__file__", None)
        if actual and not Path(actual).resolve().is_relative_to(root.resolve()):
            raise LabError("already_imported_different_original_runtime:" + module)
    return root


def _r5_arm(arm):
    return "mlx_sft" if arm["kind"] == "mlx_adapter" else arm["kind"]


def _r5_plan(arm, cases):
    path = resolve_ref(arm["runtime"]["r5_plan"], "r5_plan")
    from am_style_r5.evaluation import validate_plan
    from am_style.prompt import RESPONSE_SCHEMA
    plan = validate_plan(read_json(path))
    if plan["mode"] != "real":
        raise LabError("real_arm_requires_real_r5_plan")
    from .prepare import require_synthetic_origins
    require_synthetic_origins(plan['cases'])
    name = _r5_arm(arm)
    identity = plan["arms"][name]
    if arm["identity"].get("r5_identity_sha256") != sha(identity):
        raise LabError("r5_model_identity_and_settings_pin_mismatch")
    if arm["settings"] != identity["generation_settings"]:
        raise LabError("r5_generation_settings_mismatch")
    index = {c["case_id"]: c for c in plan["cases"]}
    for case in cases:
        original = index.get(case.get("r5_case_id", case["case_id"]))
        if original is None or original["student_wire_messages"] != case["messages"]:
            raise LabError("r5_case_does_not_use_exact_frozen_messages")
        if case["response_schema"] != RESPONSE_SCHEMA:
            raise LabError("r5_response_schema_changed")
        if case["split"] == "sealed_test" and original["split"] != "sealed_test":
            raise LabError("regression_cannot_be_promoted_to_holdout")
    return path, plan


def preflight_arm(arm, cases, *, mode="real"):
    """Read-only; no queue publication or model call. Every missing pin blocks."""
    if mode == "fixture":
        return {"status": "fixture", "blockers": [], "identity": deepcopy(arm["identity"]),
                "real_runtime_verified": False}
    try:
        if any(c["phase"] == "end_to_end" for c in cases):
            raise LabError("real_end_to_end_requires_native_workflow_receipt_adapter; module_output_is_not_end_to_end")
        root = _roots(arm)
        runtime = arm["runtime"]
        if arm["kind"] == "codex_cli":
            binary = resolve_ref(runtime["binary"], "codex_binary")
            proof = read_json(resolve_ref(runtime["capability_proof"], "capability_proof"))
            if proof.get("model") != arm["identity"].get("model"):
                raise LabError("codex_model_not_fixed_to_captured_request")
            if proof.get("cli_version") != arm["identity"].get("cli_version"):
                raise LabError("codex_cli_version_not_fixed")
            if proof.get("model_catalog_sha256") != arm["identity"].get("model_catalog_sha256"):
                raise LabError("codex_catalog_not_fixed")
            from am_style.providers import CodexCLIProvider, restricted_environment
            provider = CodexCLIProvider(binary=str(binary), model=arm["identity"]["model"],
                profile=runtime["profile"], capability_proof=proof, synthetic_only=True)
            # The original implementation verifies actual request/catalog bytes,
            # complete empty tool inventory, current config, expiry and binary.
            provider._preflight(str(root), restricted_environment(proof))
            if set(arm["settings"]) != {"timeout_seconds"}:
                raise LabError("codex_generation_settings_come_from_pinned_effective_profile; only_client_timeout_is_set_here")
            if (arm["settings"].get("timeout_seconds", 0) <= 0
                    or arm["settings"].get("timeout_seconds", 0) > 600):
                raise LabError("codex_timeout_must_be_1_to_600_seconds")
            return {"status": "ready", "blockers": [], "identity": deepcopy(arm["identity"]),
                    "real_runtime_verified": True, "tools": [],
                    "comparison_scope": "provider_plus_harness; retained policy and AGENTS",
                    "server_weights_revision": arm["identity"].get("server_weights_revision"),
                    "server_weights_revision_missing_reason": (None if arm["identity"].get("server_weights_revision")
                                                               else "not_exposed_by_provider; no immutable weight claim")}
        plan_path, plan = _r5_plan(arm, cases)
        resolve_ref(runtime["python"], "native_python")
        if arm["kind"] == "production_q8":
            from am_style_r5.runners import validate_queue_config
            queue = read_json(resolve_ref(runtime["queue_config"], "original_queue_config"))
            validated = validate_queue_config(queue)
            identity = plan["arms"]["production_q8"]
            if any(arm["identity"].get(k) != identity.get(k) for k in ("model", "model_digest")):
                raise LabError("production_q8_exact_model_and_digest_required")
            return {"status": "ready", "blockers": [], "identity": deepcopy(arm["identity"]),
                    "real_runtime_verified": True, "consumer_pid": validated["pid"],
                    "created_consumers": 0, "identity_limit": validated["identity_limit"]}
        if arm["kind"] in {"mlx_base", "mlx_adapter"}:
            if sys.platform != "darwin":
                raise LabError("original_mlx_resource_window_requires_native_macos")
            host_config = resolve_ref(runtime["host_config"], "original_host_config")
            expected = (Path.home() / ".local/share/local-qwen-feishu/config.json").resolve()
            if host_config.resolve() != expected:
                raise LabError("native_control_reads_original_host_config_only")
            control = Path(read_json(host_config)["state_directory"]) / "training-window-r7"
            if not control.is_dir() or control.is_symlink():
                raise LabError("existing_original_training_control_not_installed")
            pilot_path = resolve_ref(runtime["pilot_plan"], "sealed_original_pilot_plan")
            pilot = read_json(pilot_path)
            scope = root / "AM-HARNESS-20261031-01/R7/private"
            if not plan_path.is_relative_to(scope) or not pilot_path.is_relative_to(scope):
                raise LabError("native_eval_plan_outside_existing_private_scope")
            from am_training_window.native_eval import OriginalEvaluationGate
            # Gate checks selected existing adapter, source hashes, holdout
            # binding, environment and original manifest. It does not train.
            prospective = scope / ("r10-preflight-" + uuid.uuid4().hex)
            OriginalEvaluationGate(plan_path, pilot_path, _r5_arm(arm), prospective).checked()
            identity = plan["arms"][_r5_arm(arm)]
            for key in ("base_revision", "model_manifest_sha256", "tokenizer_sha256", "adapter_sha256"):
                if arm["identity"].get(key) != identity.get(key):
                    raise LabError("mlx_identity_pin_mismatch:" + key)
            if arm["kind"] == "mlx_base" and identity.get("adapter_sha256") is not None:
                raise LabError("base_must_not_load_adapter")
            if {c.get("r5_case_id", c["case_id"]) for c in cases} != {c["case_id"] for c in plan["cases"]}:
                raise LabError("native_eval_batch_must_equal_frozen_r5_case_set")
            return {"status": "ready", "blockers": [], "identity": deepcopy(arm["identity"]),
                    "real_runtime_verified": True, "control_directory": str(control),
                    "maintenance_owner": "existing_live_consumer", "training": False}
        raise LabError("unsupported_provider_kind")
    except Exception as exc:
        return {"status": "blocked", "blockers": [type(exc).__name__ + ": " + str(exc)],
                "identity": deepcopy(arm.get("identity", {})), "real_runtime_verified": False}


def preflight_manifest(manifest):
    validate_manifest(manifest)
    arms = manifest["arms"]
    result = {}
    for name, arm in arms.items():
        if arm["kind"] != "cascade":
            phases = {phase: preflight_arm(arm, [c for c in manifest["cases"] if c["phase"] == phase], mode=manifest["mode"])
                      for phase in sorted({c["phase"] for c in manifest["cases"]})}
            blockers = [phase + ": " + b for phase, pf in phases.items() for b in pf["blockers"]]
            states = {pf["status"] for pf in phases.values()}
            result[name] = {"status": next(iter(states)) if len(states) == 1 else "partial",
                            "blockers": blockers, "identity": deepcopy(arm["identity"]), "phases": phases,
                            "real_runtime_verified": all(pf["real_runtime_verified"] for pf in phases.values())}
    for name, arm in arms.items():
        if arm["kind"] == "cascade":
            blockers = [f"{stage}: {b}" for stage in arm["route"]["stages"] for b in result[stage]["blockers"]]
            result[name] = {"status": ("blocked" if blockers else "fixture" if manifest["mode"] == "fixture" else "ready"),
                            "blockers": blockers, "identity": arm["identity"],
                            "real_runtime_verified": not blockers and manifest["mode"] == "real"}
    return seal({"schema": "am-model-lab-preflight/1", "manifest_sha256": manifest["sha256"],
                 "checked_at": utc(), "arms": result, "models_called": 0,
                 "production_changed": False, "mode": manifest["mode"]})


def _raw(path, role):
    return {"path": str(Path(path).resolve()), "sha256": file_sha(path), "role": role}


def _stop_process(process):
    for sig, seconds in ((signal.SIGTERM, 2), (signal.SIGKILL, 2)):
        if process.poll() is not None:
            break
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            pass
    return process.poll() is not None


def _blank(status, error, *, attempted=False, timings=None, raw=None):
    return {"status": status, "error": error, "model_attempted": attempted, "output": None,
            "timings_ms": timings or {}, "raw": raw or [], "measurements": empty_measurements()}


def codex_generate(arm, case, output_dir, *, messages=None):
    """Real noninteractive CLI; exact argv/stdin/events/final retained privately."""
    private_dir(output_dir)
    out = Path(output_dir)
    started = time.monotonic()
    pf = preflight_arm(arm, [case])
    if pf["status"] != "ready":
        return _blank("blocked", "; ".join(pf["blockers"]))
    from am_style.providers import CodexCLIProvider, inspect_events, restricted_environment
    runtime = arm["runtime"]
    proof = read_json(resolve_ref(runtime["capability_proof"], "capability_proof"))
    binary = resolve_ref(runtime["binary"], "codex_binary")
    provider = CodexCLIProvider(binary=str(binary), model=arm["identity"]["model"],
        profile=runtime["profile"], capability_proof=proof, synthetic_only=True)
    work = private_dir(out / "empty-workdir")
    environment = restricted_environment(proof)
    overrides, version = provider._preflight(str(work), environment)
    schema_path = write_json(out / "response.schema.json", case["response_schema"])
    final_path, events_path, stderr_path = out / "final.txt", out / "events.jsonl", out / "stderr.log"
    payload = canonical(case["messages"] if messages is None else messages)
    input_path = out / "stdin.json"
    input_path.write_text(payload, encoding="utf-8"); input_path.chmod(0o600)
    argv = [str(binary), "exec", "--json", "--output-schema", str(schema_path),
            "--output-last-message", str(final_path), "--ephemeral", "--sandbox", "read-only",
            "--profile", runtime["profile"], "--model", arm["identity"]["model"], "--skip-git-repo-check"]
    for key, value in sorted(overrides.items()):
        argv.extend(["-c", key + "=" + json.dumps(value)])
    argv.append("-")
    request_path = write_json(out / "request.json", {"argv": argv, "messages_sha256": sha(json.loads(payload)),
        "response_schema_sha256": sha(case["response_schema"]), "preflight": pf,
        "cli_version": version, "overrides_sha256": sha(overrides), "environment_names": sorted(environment),
        "timeout_seconds": arm["settings"]["timeout_seconds"],
        "max_output_tokens_hard_enforced": False, "created_at": utc(),
        "settings_limit": "Codex does not expose an equal max-output-token limit here; report native settings"})
    process, attempted, error, status = None, False, None, "provider_failed"
    try:
        with events_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            events_path.chmod(0o600); stderr_path.chmod(0o600)
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                cwd=work, env=environment, start_new_session=True)
            attempted = True
            try:
                process.communicate(payload.encode(), timeout=arm["settings"]["timeout_seconds"])
            except subprocess.TimeoutExpired:
                _stop_process(process)
                status, error = "stop_unknown", "codex_timeout_remote_stop_not_proven; no fallback or retry"
            if error is None:
                if process.returncode != 0:
                    error = "codex_exit_nonzero:" + str(process.returncode)
                elif not final_path.is_file():
                    error = "codex_final_file_missing"
                else:
                    status = "completed"
    except BaseException as exc:
        if process is not None:
            _stop_process(process)
        status = "stop_unknown" if attempted else "provider_failed"
        error = type(exc).__name__ + ": " + str(exc)
    raw = [_raw(p, role) for p, role in ((input_path, "stdin"), (request_path, "request"),
           (schema_path, "schema"), (events_path, "events"), (stderr_path, "stderr"), (final_path, "final")) if p.is_file()]
    duration = (time.monotonic() - started) * 1000
    result = _blank(status, error, attempted=attempted, raw=raw, timings={"total_experience": duration,
        "provider_plus_cli": duration, "first_token": None, "human_wait": None})
    if events_path.is_file():
        try:
            if events_path.stat().st_size > 16 * 1024 * 1024:
                raise LabError("events_exceed_capture_limit")
            events = inspect_events(events_path.read_text(encoding="utf-8"))
            result["tools_observed"] = events["tools_called"]
            if events["tools_called"]:
                # A violated preventive boundary can leave external work or
                # descendants. Do not continue the experiment as a mere bad answer.
                result.update(status="stop_unknown", error="tool_surface_violation_requires_reconciliation")
            # Usage is accepted only from actual terminal usage events.
            completed = [x for x in read_jsonl(events_path) if x.get("type") == "turn.completed"]
            if completed and isinstance(completed[-1].get("usage"), dict):
                usage = completed[-1]["usage"]
                for target, key in (("input", "input_tokens"), ("output", "output_tokens"), ("cached_input", "cached_input_tokens")):
                    value = usage.get(key)
                    if type(value) is int and value >= 0:
                        result["measurements"]["tokens"][target] = measured(value, unit="tokens", source="codex turn.completed", scope="provider-reported")
        except Exception as exc:
            # Never turn unknown stop into an ordinary invalid-output failure.
            if result["status"] != "stop_unknown":
                result.update(status="invalid", error="event_capture_invalid:" + str(exc))
    if result["status"] == "completed":
        if final_path.stat().st_size > 16 * 1024 * 1024:
            result.update(status="invalid", error="final_exceeds_capture_limit")
        else:
            result["output"] = final_path.read_text(encoding="utf-8")
            final_path.chmod(0o600)
    write_json(out / "receipt.json", seal(result))
    return result


def _worker_environment(root):
    env = dict(os.environ)
    # Keep HOME/CODEX_HOME and existing policies. Only add explicit import paths.
    env["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).resolve().parent.parent),
        str(root / "am-style-r5/src"), str(root / "am-conversation-r1/src"),
        str(root / "am-style-r3"), str(root / "am-integrated-r6")])
    return env


def _import_r5(plan, path, cases, arm_name, batch_ms, raw_refs):
    from am_style_r5.evaluation import import_results
    original = read_jsonl(path)
    # This verifies exact request, response, generation settings and output
    # bindings, not only subprocess exit status. Missing rows stay missing.
    imported = import_results(plan, original)
    verified = {(r["case_id"], r["arm"]): r for r in imported["rows"] if r["record"] is not None}
    result = {}
    for case in cases:
        key = (case.get("r5_case_id", case["case_id"]), arm_name)
        row = verified.get(key)
        if row is None:
            result[case["case_id"]] = _blank("not_run", "original_runner_stopped_before_case", raw=raw_refs)
            continue
        record = row["record"]
        status = {"failed": "provider_failed"}.get(record["status"], record["status"])
        result[case["case_id"]] = {
            "status": status, "error": record.get("error"), "output": record.get("raw_output") or None,
            "model_attempted": bool(record.get("response_artifact")) or status in {"completed", "truncated", "stop_unknown"},
            "raw": raw_refs, "r5_record": record,
            "r5_fact_guard": row["safety"], "artifact_bindings_verified": row["artifact_bindings_verified"],
            "timings_ms": {**record.get("latency_ms", {}), "batch_window_total": batch_ms,
                           "total_experience": record.get("latency_ms", {}).get("end_to_end"),
                           "first_token": None, "human_wait": None},
            "measurements": empty_measurements("original_runner_does_not_capture_this_metric"),
        }
        if arm_name in {"mlx_base", "mlx_sft"}:
            # Native R5 explicitly labels end_to_end as generation-only. Do not
            # silently present it as the user-visible load/suspend/restore loop.
            target = result[case["case_id"]]
            target["timings_ms"]["provider"] = record.get("latency_ms", {}).get("end_to_end")
            target["timings_ms"]["total_experience"] = None
            if record.get("response_artifact"):
                response = json.loads(record["response_artifact"])
                for name, key in (("input", "prompt_tokens"), ("output", "generation_tokens")):
                    value = response.get(key)
                    if type(value) is int and value >= 0:
                        target["measurements"]["tokens"][name] = measured(value, unit="tokens", source="original MLX response", scope="per_generation")
                memory = response.get("peak_memory_GB")
                if type(memory) in (float, int) and memory >= 0:
                    target["measurements"]["resources"]["mlx_reported_peak_memory_GB"] = measured(memory,
                        unit="GB", source="original MLX peak_memory_GB", scope="native_library_reported_peak; not per-process RSS")
    return result


def q8_generate_batch(arm, cases, output_dir):
    """Run original R5 in a private-umask process; never spawn a consumer."""
    out = private_dir(output_dir)
    pf = preflight_arm(arm, cases)
    if pf["status"] != "ready":
        return {c["case_id"]: _blank("blocked", "; ".join(pf["blockers"])) for c in cases}
    root = _roots(arm)
    runtime = arm["runtime"]
    _, plan = _r5_plan(arm, cases)
    python = resolve_ref(runtime["python"], "native_python")
    worker_config = write_json(out / "worker-request.json", {"arm": arm,
        "case_ids": [c.get("r5_case_id", c["case_id"]) for c in cases], "output": str(out / "original")})
    argv = [str(python), "-m", "model_lab.worker", "q8", str(worker_config)]
    write_json(out / "launch.json", {"argv": argv, "umask": "0077", "created_consumers": 0})
    log = out / "worker.log"
    start = time.monotonic()
    with log.open("xb") as stream:
        log.chmod(0o600)
        process = subprocess.Popen(argv, env=_worker_environment(root), cwd=root,
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=min(3600, 160 * len(cases) + 30))
        except subprocess.TimeoutExpired:
            _stop_process(process)
            return {c["case_id"]: _blank("stop_unknown", "q8_client_timeout_original_consumer_stop_unknown",
                    attempted=True, raw=[_raw(log, "worker_log")]) for c in cases}
    elapsed = (time.monotonic() - start) * 1000
    records = out / "original/results.jsonl"
    raw = [_raw(p, "original_r5_artifact") for p in sorted(out.rglob("*")) if p.is_file()]
    if not records.is_file():
        # A crash after a publication must not become a safe-to-retry error.
        return {c["case_id"]: _blank("stop_unknown", "original_q8_worker_returned_without_complete_evidence",
                attempted=True, raw=raw) for c in cases}
    try:
        return _import_r5(plan, records, cases, "production_q8", elapsed, raw)
    except Exception as exc:
        return {c["case_id"]: _blank("stop_unknown", "original_evidence_invalid:" + str(exc), attempted=True, raw=raw) for c in cases}


def mlx_generate_batch(arm, cases, output_dir):
    """Publish original eval-mlx envelope and wait for the same host's receipt."""
    out = private_dir(output_dir)
    pf = preflight_arm(arm, cases)
    if pf["status"] != "ready":
        return {c["case_id"]: _blank("blocked", "; ".join(pf["blockers"])) for c in cases}
    root, runtime = _roots(arm), arm["runtime"]
    plan_path, plan = _r5_plan(arm, cases)
    pilot_path = resolve_ref(runtime["pilot_plan"], "pilot_plan")
    python = resolve_ref(runtime["python"], "native_python")
    request_id, run_id = str(uuid.uuid4()), "r10-eval-" + uuid.uuid4().hex
    native_run = root / "AM-HARNESS-20261031-01/R7/private" / run_id
    control = Path(pf["control_directory"])
    script = root / "am-integrated-r6/tools/training_control.py"
    argv = [str(python), str(script), "eval-mlx", "--plan", str(plan_path), "--pilot-plan", str(pilot_path),
            "--arm", _r5_arm(arm), "--run-id", run_id, "--request-id", request_id,
            "--expires-seconds", "900", "--execute"]
    write_json(out / "launch.json", {"argv": argv, "request_id": request_id, "run_id": run_id,
        "native_run": str(native_run), "operation": "eval-mlx", "training": False, "created_consumers": 0})
    start = time.monotonic()
    try:
        submitted = subprocess.run(argv, cwd=root, env=_worker_environment(root), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=15)
        write_json(out / "submission.json", {"returncode": submitted.returncode, "stdout": submitted.stdout,
                   "stderr": submitted.stderr})
        if submitted.returncode != 0:
            raise LabError("native_submission_failed; reconcile request path before retry")
        receipt = control / (request_id + ".result.json")
        deadline = start + 960
        while not receipt.is_file() and time.monotonic() < deadline:
            time.sleep(.25)
        if not receipt.is_file():
            raise LabError("native_eval_result_missing; recover original request explicitly")
        result = read_json(receipt)
        write_json(out / "native-result.json", result)
        for suffix in (".receipt.json", ".journal.json"):
            p = control / (request_id + suffix)
            if p.is_file(): write_json(out / p.name, read_json(p))
        window = result.get("window", {})
        if (result.get("trainer_start_attempts") != 0 or result.get("real_platform_sends") != 0
                or window.get("status") != "completed" or window.get("restore_verified") is not True):
            raise LabError("native_window_not_completed_restored_or_unexpected_training_or_send")
        parent = read_json(native_run / "parent-result.json")
        if parent.get("stop_confirmed") is not True or parent.get("status") != "completed":
            raise LabError("original_mlx_worker_stop_or_completion_not_verified")
        # Copy exact native artifacts privately; hashes identify the original bytes.
        import shutil
        captured = private_dir(out / "original")
        for p in sorted(native_run.rglob("*")):
            if p.is_symlink(): raise LabError("symlink_in_native_evidence")
            if p.is_file():
                target = captured / p.relative_to(native_run)
                private_dir(target.parent)
                shutil.copyfile(p, target); target.chmod(0o600)
        raw = [_raw(p, "original_native_artifact") for p in sorted(out.rglob("*")) if p.is_file()]
        return _import_r5(plan, captured / "results.jsonl", cases, _r5_arm(arm), (time.monotonic() - start) * 1000, raw)
    except BaseException as exc:
        write_json(out / "unreconciled.json", {"request_id": request_id, "run_id": run_id,
                   "error": str(exc), "next_action": "inspect original training-control receipt/journal; never rerun automatically"})
        raw = [_raw(p, "native_attempt") for p in sorted(out.rglob("*")) if p.is_file()]
        return {c["case_id"]: _blank("stop_unknown", type(exc).__name__ + ": " + str(exc),
                    attempted=True, raw=raw) for c in cases}
