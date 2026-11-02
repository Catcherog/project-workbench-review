"""Synthetic, non-executing reproduction of the R5 independent-holdout gate gap.

No model process, network request, production action or real training occurs.
The existing test_pilot gold fixture supplies synthetic approvals, NOT human data.
Only inaccessible original-machine mechanics validation and metadata probe are
stubbed as valid; real data/source/config/plan checks remain in the code path.
The CLI's final subprocess invocation is intercepted and never launched.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.dont_write_bytecode = True
AUDIT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("AM_R5_REPRO_PACKAGE", str(AUDIT / "am-style-r5"))).resolve()
if not (ROOT / "tests/test_pilot.py").is_file():
    raise SystemExit("Set AM_R5_REPRO_PACKAGE to the original fixed R5 am-style-r5 directory; this reproduces the unpatched control flow only.")
for source in (
    ROOT / "src",
    ROOT / "baseline/am-style-r3",
    ROOT / "baseline/am-conversation-r1/src",
    ROOT / "tests",
):
    sys.path.insert(0, str(source))

from am_style_r5 import cli, pilot
from am_style_r5.common import read_json, write_json
from test_pilot import _snapshot, _synthetic_request
from training.mlx_r4_runtime import code_hashes


def main():
    with tempfile.TemporaryDirectory(prefix="holdout-repro-", dir=AUDIT) as temp:
        tmp = Path(temp).resolve()
        snapshot_path, snapshot = _snapshot(tmp, accepted=True)
        assert snapshot["counts"]["train"] == 24
        assert snapshot["counts"]["dev"] == 8
        mechanics_dir = tmp / "synthetic-mechanics"
        mechanics_dir.mkdir()
        mechanics_path = mechanics_dir / "result.json"
        manifest_path = tmp / "synthetic-manifest.json"
        write_json(mechanics_path, {"fixture_only": True})
        manifest = {
            "local_model_path": str(tmp / "synthetic-model"),
            "service": {
                "lease_file": str(tmp / "synthetic-service/model-coordinator.lock"),
                "gateway_db": str(tmp / "synthetic-service/gateway.sqlite3"),
                "chat_db": str(tmp / "synthetic-service/chat.sqlite3"),
                "protected_config_files": {str(tmp / "synthetic-config/config.json"): "a" * 64},
            },
        }
        write_json(manifest_path, manifest)
        request = _synthetic_request()
        request["code_sha256"] = code_hashes()
        metadata_stub = {
            "blockers": [],
            "ready_for_launch": True,
            "model_loaded": False,
            "mlx_imported": False,
            "training_executed": False,
            "fixture_only": True,
        }

        with patch.object(pilot, "_original_mechanics", return_value=(
            mechanics_path, manifest_path, request, manifest
        )) as mechanics_stub, patch.object(pilot, "_run_probe", return_value=metadata_stub) as probe_stub:
            prepared = pilot.prepare_pilot(
                snapshot_path, mechanics_path, manifest_path,
                tmp / "plan", run_dir=tmp / "never-executed-run"
            )
            plan_path = prepared["plan_path"]
            plan = read_json(plan_path)
            assert not any("holdout" in key or "test" in key for key in plan)
            assert not list(tmp.rglob("*holdout*"))
            command = pilot.execution_argv(plan_path)
            assert command["argv"][-1] == "--execute"
            with patch.object(cli.subprocess, "run", return_value=subprocess.CompletedProcess(
                args=["INTERCEPTED_NO_EXECUTION"], returncode=0
            )) as launch_stub:
                status = cli.main(["pilot-execute", "--plan", plan_path, "--execute"])
            assert status == 0
            assert launch_stub.call_count == 1
            called_argv = launch_stub.call_args.args[0]
            assert "training.mlx_r4" in called_argv and "--execute" in called_argv
            assert not (tmp / "never-executed-run").exists()
            report = {
                "scope": "synthetic_control_flow_reproduction_only",
                "fixture_counts": snapshot["counts"],
                "holdout_files_created": 0,
                "holdout_fields_in_plan": [],
                "metadata_ready": prepared["preflight"]["ready_for_launch"],
                "execution_argv_returned": True,
                "cli_attempted_trainer_subprocess": launch_stub.call_count,
                "cli_exit_code_under_interception": status,
                "real_subprocesses_started": 0,
                "model_loaded": False,
                "training_executed": False,
                "mocked_checks": [
                    "pilot._original_mechanics (assumes original R4 mechanics and manifest are valid)",
                    "pilot._run_probe (assumes original machine metadata contracts pass)",
                    "cli.subprocess.run (intercepts the final launch; no process is created)",
                ],
                "unmocked_checks": [
                    "gold snapshot export and verification from original synthetic test fixture",
                    "train/dev counts and immutable snapshot/config bindings",
                    "R4 runtime source fingerprints and selected Python fingerprint",
                    "plan seal, readback, protected output checks and CLI argument routing",
                ],
                "mechanics_stub_calls": mechanics_stub.call_count,
                "metadata_probe_stub_calls": probe_stub.call_count,
                "conclusion": "Without any frozen holdout, current pilot-execute reaches its trainer launch when other prerequisites are assumed valid.",
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
            write_json(AUDIT / "repro_holdout_gate_result.json", report)


if __name__ == "__main__":
    main()
