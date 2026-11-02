"""Contract tests only: synthetic review labels never count as actual feedback."""
from pathlib import Path
import shutil
import sys

import tempfile
import unittest

from am_style_r5.common import R5Error, file_hash, read_json, seal, write_json
from am_style_r5.dataset import (build_review_batch, export_gold_snapshot,
    feedback_template, freeze_group_registry, import_feedback_file)
from am_style_r5.scenarios import calibration_specs
from am_style_r5 import pilot


ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "baseline/data/r4-gold/sft.train.jsonl"
DEV = ROOT / "baseline/data/r4-gold/sft.dev.jsonl"


def _snapshot(tmp_path, *, accepted=False):
    specs = calibration_specs()
    registry = freeze_group_registry(specs, baseline_train=TRAIN, baseline_dev=DEV)
    imports = []
    if accepted:
        # Unit-test fixture only. This is not a real human approval, is never
        # retained in deliverable data, and cannot unlock real mechanics proof.
        batch = build_review_batch(specs, registry, version="unit-test-only")
        feedback = feedback_template(batch)
        feedback.update(origin="human", reviewer="UNIT_TEST_FIXTURE_NOT_REAL_FEEDBACK",
                        reviewed_at="2026-11-02T08:00:00+08:00")
        for row in feedback["ratings"]:
            row.update(status="reviewed", accepted_candidate="proposed_revision")
            row["assessments"]["proposed_revision"].update(facts_pass=True, style_pass=True, acceptable=True)
        path = tmp_path / "unit-test-feedback.json"
        write_json(path, feedback)
        imports.append(import_feedback_file(batch, path))
    output = tmp_path / "snapshot"
    snapshot = export_gold_snapshot(registry, imports, baseline_train=TRAIN,
                                   baseline_dev=DEV, output_dir=output)
    return output / "snapshot.json", snapshot


def _synthetic_request():
    config = read_json(ROOT / "baseline/am-style-r3/config/mlx_r4.mechanics.example.json")
    config["runtime_prompt_builder_sha256"] = file_hash(ROOT / "baseline/am-conversation-r1/src/am_style/prompt.py")
    return {"config": config}


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r5-pilot-test-")
        self.addCleanup(self.temp.cleanup)
        self.tmp_path = Path(self.temp.name)

    def test_existing_nine_one_cannot_be_promoted_or_create_a_run(self):
        tmp_path = self.tmp_path
        path, snapshot = _snapshot(tmp_path)
        assert snapshot["counts"]["train"] == 9
        assert snapshot["counts"]["dev"] == 1
        with self.assertRaisesRegex(R5Error, "24–48"):
            pilot.prepare_pilot(path, tmp_path / "missing-result.json", tmp_path / "missing-manifest.json",
                                tmp_path / "plan")
        assert not (tmp_path / "plan").exists()


    def test_self_declared_mechanics_success_cannot_unlock_a_complete_test_dataset(self):
        tmp_path = self.tmp_path
        path, snapshot = _snapshot(tmp_path, accepted=True)
        assert snapshot["counts"]["train"] == 24
        assert snapshot["counts"]["dev"] == 8
        result = tmp_path / "fake-result.json"
        write_json(result, {"mechanics_closed": True, "training_completed": True, "actual_run": True})
        with self.assertRaisesRegex(R5Error, "ORIGINAL result"):
            pilot.prepare_pilot(path, result, tmp_path / "manifest.json", tmp_path / "plan")
        assert not (tmp_path / "plan").exists()


    def test_public_completion_record_without_private_artifacts_is_not_executable(self):
        tmp_path = self.tmp_path
        # Exact public observation of the real result. There are intentionally no
        # original request bytes or adapter tensors in this test or deliverable.
        value = {
            "schema": "am-style-mlx-r4-result/1",
            "request_sha256": "6f61e9952f3ee869869e3ad98e5e8297317c7ea931e42cd510912128198e9146",
            "phases": [
                {"phase": "fit", "attempted": True, "pid": 20007, "exit_code": 0,
                 "timed_out": False, "stop_confirmed": True, "status": "completed"},
                {"phase": "reload", "attempted": True, "pid": 20279, "exit_code": 0,
                 "timed_out": False, "stop_confirmed": True, "status": "completed"}],
            "mechanics_closed": True, "quality_conclusion": "not_established",
            "files_sha256": {
                "request.json": "de7afd3237f83676bf16111b0768a778dd51c74505360606b3bba7d443d0f024",
                "fit.json": "4cb17be3de96e995587b384576daa19812952b47b165cae1e0f8dfbc9436a6ba",
                "reload.json": "b5d3cd444cc7ea78ea8f89133afe2f9562da84819415af1ee64bfd88de98d54f",
                "kernel-validation.json": "a242849c0d37985c68893955c0f568c33d3e97f6e475a66fda4703794b6155e5",
                "steps.json": "470355b1615773fdf7e593f6a570472b5e5348125c6fc743e5d37ee533c8bad7",
                "adapters.safetensors": "c61a03a8ea9847e9a025cf10309d8ffc2dd4bdc2c91ede1619c0ea0005eb0b4b",
                "adapter_config.json": "4568b8ceed42a7c1dd993669d1ffcf60870e4b618d182c300c6ab4684f9283b4"},
            "production_changed": False, "business_acceptance": False,
        }
        result = tmp_path / "result.json"
        write_json(result, value)
        assert file_hash(result) == pilot.AUDITED_MECHANICS_RESULT_SHA
        with self.assertRaisesRegex(R5Error, "missing original mechanics artifact: request.json"):
            pilot._original_mechanics(result, tmp_path / "manifest.json")


    def test_config_preserves_mechanics_hyperparameters_and_uses_complete_gold(self):
        tmp_path = self.tmp_path
        path, snapshot = _snapshot(tmp_path, accepted=True)
        request = _synthetic_request()
        config = pilot._config(path, snapshot, request, tmp_path / "actual-mechanics-result.json")
        for key in ("lora", "seed", "epochs", "adapted_layers", "learning_rate", "weight_decay",
                    "optimizer_bias_correction", "max_length", "worker_timeout_seconds",
                    "runtime_prompt_builder_sha256", "style_policy_version", "host_contract_version"):
            assert config[key] == request["config"][key]
        assert config["stage"] == "pilot"
        assert config["gradient_accumulation"] == 4
        assert config["train_sha256"] == file_hash(path.parent / "sft.train.jsonl")
        assert config["dev_sha256"] == file_hash(path.parent / "sft.dev.jsonl")
        assert request["config"]["stage"] == "mechanics"


    def test_original_preflight_is_called_and_cannot_treat_fixture_as_real_training(self):
        tmp_path = self.tmp_path
        path, snapshot = _snapshot(tmp_path, accepted=True)
        config = pilot._config(path, snapshot, _synthetic_request(), tmp_path / "nonexistent-result.json")
        config_path, manifest_path = tmp_path / "pilot.config.json", tmp_path / "manifest.json"
        write_json(config_path, config)
        write_json(manifest_path, {})
        binding = pilot._source_binding()
        # These are the actual original module hashes, not patched validators.
        from training.mlx_r4_runtime import code_hashes
        report = pilot._run_probe(manifest_path, config_path, binding,
                                  pilot._interpreter_record(), code_hashes())
        assert report["ready_for_launch"] is False
        assert report["checks"]["validate_mechanics_gate"]["status"] == "blocked"
        assert report["checks"]["validate_plan"]["status"] == "blocked"
        assert any(x["check"] == "validate_plan" and "sealed actual R4 mechanics result" in x["reason"]
                   for x in report["blockers"])
        assert report["mlx_imported"] is False
        assert report["training_executed"] is False
        assert "base" in {x["check"] for x in report["r4_preflight"]["blockers"]}


    def test_newer_host_source_is_reported_without_overwriting_it(self):
        tmp_path = self.tmp_path
        roots = {"training": tmp_path / "training-root", "am_style": tmp_path / "style-root"}
        original = pilot._source_binding()
        for name in pilot.RUNTIME_FILES:
            key = name.split("/", 1)[0]
            dst = roots[key] / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(original["roots"][key]) / name, dst)
        assert pilot._source_binding(roots)["mode"] == "explicit_host_runtime"
        changed = roots["training"] / "training/mlx_r4_runtime.py"
        changed.write_text(changed.read_text() + "\n# Newer host implementation remains untouched.\n")
        before = changed.read_bytes()
        with self.assertRaisesRegex(R5Error, "runtime source differs"):
            pilot._source_binding(roots)
        assert changed.read_bytes() == before


    def test_cached_green_flag_is_not_an_execution_permission(self):
        tmp_path = self.tmp_path
        path = tmp_path / "forged-plan.json"
        write_json(path, seal({"schema": pilot.PLAN_SCHEMA, "training_executed": False,
                               "ready_for_launch": True, "initial_preflight": {"passed": True}}))
        report = pilot.preflight_pilot(path)
        assert report["ready_for_launch"] is False
        assert report["training_executed"] is False
        with self.assertRaisesRegex(R5Error, "pilot is blocked"):
            pilot.execution_argv(path)


    def test_virtualenv_interpreter_path_is_preserved(self):
        tmp_path = self.tmp_path
        executable = tmp_path / "venv with spaces" / "bin" / "python"
        executable.parent.mkdir(parents=True)
        executable.symlink_to(sys.executable)
        record = pilot._interpreter_record(executable)
        assert record["path"] == str(executable)
        assert record["resolved_path"] == str(executable.resolve())


    def test_outputs_cannot_enter_model_service_or_input_evidence(self):
        tmp_path = self.tmp_path
        manifest = {"local_model_path": str(tmp_path / "model"), "service": {
            "lease_file": str(tmp_path / "service/model-coordinator.lock"),
            "gateway_db": str(tmp_path / "service/gateway.sqlite3"),
            "chat_db": str(tmp_path / "service/chat.sqlite3"),
            "protected_config_files": {str(tmp_path / "config/config.json"): "a" * 64}}}
        for child in ("model/run", "service/run", "config/run", "evidence/run"):
            with self.assertRaisesRegex(R5Error, "protected"):
                pilot._check_output(tmp_path / child, manifest, evidence_roots=(tmp_path / "evidence",))
        assert pilot._check_output(tmp_path / "new-run", manifest) == tmp_path / "new-run"



if __name__ == "__main__":
    unittest.main()
