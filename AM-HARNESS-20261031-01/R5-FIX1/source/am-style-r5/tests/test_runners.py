"""Offline adapter failure tests. No real model/service/production data is used.

The model and process substitutes below exist only inside temporary tests; their
records are not training evidence, gold labels, or actual provider measurements.
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from am_style_r5.common import R5Error, canonical, file_hash, object_hash, read_json, read_jsonl, seal, text_hash, write_json
from am_style_r5.evaluation import build_plan
from am_style_r5.scenarios import calibration_specs, evaluation_cases
from am_style_r5 import runners
from training.mlx_r4_resources import PRODUCTION_MODEL, PRODUCTION_DIGEST


def _manifest(root):
    """A local path fixture, never a real MLX model manifest."""
    service = root / "service"
    service.mkdir()
    for name in ("model-coordinator.lock", "gateway.sqlite3", "chat.sqlite3"):
        (service / name).touch()
    model = root / "not-a-real-model"
    model.mkdir()
    config = root / "config"
    config.mkdir()
    host, poc = config / "host.json", config / "poc.json"
    write_json(poc, {"service": {"root_directory": str(service)}})
    write_json(host, {"poc_config": str(poc)})
    return {"revision": "a" * 40, "local_model_path": str(model),
        "files": {"tokenizer.json": {"sha256": "2" * 64},
                  "chat_template.jinja": {"sha256": text_hash("UNIT_TEST_TEMPLATE")}},
        "service": {"lease_file": str(service / "model-coordinator.lock"),
                    "gateway_db": str(service / "gateway.sqlite3"), "chat_db": str(service / "chat.sqlite3"),
                    "protected_config_files": {str(host): file_hash(host), str(poc): file_hash(poc)},
                    "expected_model": PRODUCTION_MODEL, "expected_digest": PRODUCTION_DIGEST}}


def _plan(manifest, count=2):
    shared = {"base_revision": manifest["revision"], "model_manifest_sha256": object_hash(manifest),
              "tokenizer_sha256": manifest["files"]["tokenizer.json"]["sha256"],
              "generation_settings": runners.MLX_SETTINGS}
    arms = {"production_q8": {"model": PRODUCTION_MODEL, "model_digest": PRODUCTION_DIGEST,
                              "generation_settings": runners.QWEN_SETTINGS},
            "mlx_base": {**shared, "adapter_sha256": None},
            "mlx_sft": {**shared, "adapter_sha256": "3" * 64,
                        "pilot_request_sha256": "4" * 64, "pilot_result_file_sha256": "5" * 64,
                        "train_file_sha256": "7" * 64, "dev_file_sha256": "8" * 64}}
    # mode=real exercises the adapter protocol; this fixture is NOT exported.
    return build_plan(evaluation_cases(calibration_specs()[:count]), arms, mode="real")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r5-adapter-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = _manifest(self.root)
        self.plan = _plan(self.manifest)

    def _queue(self):
        path = self.root / "manifest.json"
        write_json(path, self.manifest)
        queue = self.root / "service/state/am-conversation-r2"
        (queue / "requests").mkdir(parents=True)
        (queue / "results").mkdir()
        return {"service_manifest_path": str(path), "service_manifest_sha256": file_hash(path),
                "queue_root": str(queue), "expected_consumer_pid": os.getpid(),
                "host_config_path": str(self.root / "config/host.json")}, queue

    def test_execute_flag_required_before_side_effects_or_source_reads(self):
        with patch.object(runners, "_execution_sources", side_effect=AssertionError("must not run")), \
                patch.object(runners.subprocess, "Popen", side_effect=AssertionError("must not spawn")):
            with self.assertRaisesRegex(R5Error, "execute=True"):
                runners.run_original_qwen({}, {}, self.root / "queue-output")
            with self.assertRaisesRegex(R5Error, "execute=True"):
                runners.run_mlx_arm({}, "mlx_base", "missing", self.root / "mlx-output")
            with self.assertRaisesRegex(R5Error, "explicit execution"):
                runners.main(["--mlx-worker", str(self.root / "missing-request.json")])
        self.assertFalse((self.root / "queue-output").exists())
        self.assertFalse((self.root / "mlx-output").exists())

    def test_explicit_empty_or_duplicate_case_selection_does_not_expand(self):
        with self.assertRaisesRegex(R5Error, "empty"):
            runners._case_ids(self.plan, [])
        ident = self.plan["cases"][0]["case_id"]
        with self.assertRaisesRegex(R5Error, "Duplicate"):
            runners._case_ids(self.plan, [ident, ident])
        self.assertEqual(len(runners._case_ids(self.plan)), 2)

    def test_queue_is_bound_to_protected_config_chain(self):
        config, queue = self._queue()
        self.assertEqual(runners.validate_queue_config(config)["root"], queue)
        other = self.root / "other-queue"
        (other / "requests").mkdir(parents=True); (other / "results").mkdir()
        with self.assertRaisesRegex(R5Error, "Queue path differs"):
            runners.validate_queue_config({**config, "queue_root": str(other)})
        with patch.object(runners.os, "kill", side_effect=ProcessLookupError):
            with self.assertRaisesRegex(R5Error, "not observable"):
                runners.validate_queue_config(config)

    def test_unverified_failed_queue_result_is_retained_and_stops_next_case(self):
        config, queue = self._queue()
        def simulated_consumer(_):
            jobs = list((queue / "requests").glob("*.json"))
            self.assertEqual(len(jobs), 1)
            label = jobs[0].stem
            response = {"ok": False, "label": label, "operation": "task_model_probe",
                "model": PRODUCTION_MODEL, "model_digest": PRODUCTION_DIGEST,
                "original_host_pid": os.getpid() + 1,  # deliberately wrong
                "original_coordinator": True, "synthetic_only": True,
                "external_business_calls": 0, "error": "UNIT_TEST_FAILED_RESPONSE"}
            write_json(queue / "results" / (label + ".json"), response)
        out = self.root / "qwen-result"
        with patch.object(runners.time, "sleep", side_effect=simulated_consumer):
            report = runners.run_original_qwen(self.plan, config, out, execute=True)
        self.assertTrue(report["stop_unknown"])
        self.assertTrue(report["resume_requires_reconciliation"])
        self.assertEqual(report["submitted_probes"], 1)
        self.assertEqual(report["remaining_cases"], 1)
        self.assertIsNone(report["actual_calls"])
        records = read_jsonl(out / "results.jsonl")
        self.assertEqual(records[0]["status"], "stop_unknown")
        self.assertIn("UNIT_TEST_FAILED_RESPONSE", records[0]["response_artifact"])
        self.assertTrue((out / "001-request.json").is_file())
        self.assertTrue((out / "001-response.json").is_file())

    def test_sft_artifact_symlink_cannot_escape_run_directory(self):
        out = self.root / "sft-fixture"
        out.mkdir()
        other = self.root / "outside-request.json"
        write_json(other, {"fixture": True})
        (out / "request.json").symlink_to(other)
        write_json(out / "result.json", {"schema": "am-style-mlx-r4-result/1", "mechanics_closed": True,
                                         "files_sha256": {"request.json": file_hash(other)}})
        with self.assertRaisesRegex(R5Error, "out-of-root"):
            runners.validate_sft_run(out, self.manifest)

    def test_same_adapter_does_not_substitute_a_different_pilot_run(self):
        selected = {"adapter_sha256": "3" * 64, "request_sha256": "4" * 64, "result_file_sha256": "5" * 64,
                    "train_sha256": "7" * 64, "dev_sha256": "8" * 64}
        runners._mlx_identity(self.plan, "mlx_sft", self.manifest, selected)
        for key in ("request_sha256", "result_file_sha256", "train_sha256", "dev_sha256"):
            with self.subTest(key=key), self.assertRaisesRegex(R5Error, "checkpoint/run differ"):
                runners._mlx_identity(self.plan, "mlx_sft", self.manifest, {**selected, key: "6" * 64})
        with self.assertRaisesRegex(R5Error, "Base arm"):
            runners._mlx_identity(self.plan, "mlx_base", self.manifest, selected)

    def test_runner_source_hash_includes_dependency_bundle(self):
        sources = {"r4": {"training/runtime.py": "1" * 64}, "r5": {"runners.py": "2" * 64}}
        changed = {**sources, "r4": {"training/runtime.py": "3" * 64}}
        with patch.object(runners, "_execution_sources", return_value=sources):
            original = runners.runner_source_hash()
        with patch.object(runners, "_execution_sources", return_value=changed):
            revised = runners.runner_source_hash()
        self.assertEqual(original, object_hash(sources))
        self.assertNotEqual(original, revised)

    def test_timeout_cleanup_kills_surviving_group_after_leader_exits(self):
        process = types.SimpleNamespace(pid=123456, poll=lambda: 0, wait=lambda timeout: 0)
        gone = iter([False, False, True, True, True])
        with patch.object(runners, "_group_gone", side_effect=lambda _: next(gone, True)), \
                patch.object(runners.os, "killpg") as kill:
            code, stopped = runners._stop_group(process)
        self.assertEqual(code, 0)
        self.assertTrue(stopped)
        self.assertEqual([call.args[1] for call in kill.call_args_list], [signal.SIGTERM, signal.SIGKILL])

    def test_zero_exit_without_bound_worker_results_is_not_success(self):
        out = self.root / "exit-zero-no-evidence"
        out.mkdir()
        with self.assertRaisesRegex(R5Error, "Missing"):
            runners._validate_worker_completion(out, {"plan": self.plan})

    def _worker_fixture(self, stream, *, count=2):
        """Replace model imports and lease with bounded in-memory substitutes."""
        plan = _plan(self.manifest, count)
        out = self.root / "worker-fixture"
        out.mkdir()
        request = seal({"schema": "am-r5-mlx-generation-request/1", "plan": plan, "arm": "mlx_base",
            "manifest": self.manifest, "selected_run": None, "execution_sources": runners._execution_sources(),
            "case_ids": [c["case_id"] for c in plan["cases"]], "timeout_seconds": 30,
            "runner_source_sha256": runners.runner_source_hash()})
        path = out / "request.json"
        write_json(path, request)
        observations = {"entered": 0, "exited": 0, "checks": 0, "loads": 0}
        class Lease:
            def __init__(self, *_): self.history = []
            def __enter__(self): observations["entered"] += 1; return self
            def __exit__(self, *_): observations["exited"] += 1
            def check(self, **_): observations["checks"] += 1
        class Model:
            model_type = "qwen3_5"
            layers = [None] * 64
            def eval(self): pass
        class Tokenizer:
            chat_template = "UNIT_TEST_TEMPLATE"
            def apply_chat_template(self, _wire, **kwargs):
                self.options = kwargs
                if kwargs != {"tokenize": True, "add_generation_prompt": True, "enable_thinking": False,
                              "preserve_thinking": False, "return_dict": False}:
                    raise AssertionError("template options changed")
                return [1, 2, 3]
        mlx = types.ModuleType("mlx")
        core = types.ModuleType("mlx.core")
        core.set_memory_limit = lambda *_: None
        core.set_cache_limit = lambda *_: None
        core.random = types.SimpleNamespace(seed=lambda *_: None)
        mlx.core = core
        mlx_lm = types.ModuleType("mlx_lm")
        def load(*_, **__):
            observations["loads"] += 1
            return Model(), Tokenizer()
        mlx_lm.load, mlx_lm.stream_generate = load, stream
        stack = ExitStack()
        stack.enter_context(patch.dict(sys.modules, {"mlx": mlx, "mlx.core": core, "mlx_lm": mlx_lm}))
        stack.enter_context(patch("training.mlx_r4_contracts.validate_environment", return_value={"fixture_only": True}))
        stack.enter_context(patch("training.mlx_r4_contracts.validate_base", return_value={"fixture_only": True}))
        stack.enter_context(patch("training.mlx_r4_resources.OriginalLease", Lease))
        self.addCleanup(stack.close)
        return path, out, request, observations

    def test_stream_exception_preserves_partial_attempt_and_releases_original_lease(self):
        calls = []
        def failing_stream(_model, _tokenizer, _tokens, **kwargs):
            calls.append(kwargs)
            kwargs["prompt_progress_callback"](0, 3)
            yield types.SimpleNamespace(text='{"text":"partial', finish_reason=None)
            raise RuntimeError("UNIT_TEST_GENERATOR_ERROR")
        path, out, request, observations = self._worker_fixture(failing_stream)
        self.assertEqual(runners._mlx_worker(path), 2)
        records = read_jsonl(out / "results.jsonl")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "failed")
        self.assertEqual(records[0]["raw_output"], '{"text":"partial')
        self.assertIn("UNIT_TEST_GENERATOR_ERROR", records[0]["response_artifact"])
        self.assertEqual(len(calls), 1)
        self.assertEqual((observations["entered"], observations["exited"], observations["loads"]), (1, 1, 1))
        self.assertEqual(read_json(out / "worker-result.json")["status"], "failed")
        recovered = runners._parent_interruption(out, request, "failed", "worker_failed", stopped=True)
        self.assertEqual(len(read_jsonl(recovered)), 1)  # Remaining case was not attempted.

    def test_length_finish_is_truncated_and_parent_verifies_complete_record_graph(self):
        def short_stream(_model, _tokenizer, _tokens, **kwargs):
            kwargs["prompt_progress_callback"](3, 3)
            yield types.SimpleNamespace(text='{"text":"test"}', finish_reason="length", prompt_tokens=3,
                generation_tokens=192, prompt_tps=10.0, generation_tps=20.0, peak_memory=1.0)
        path, out, request, _ = self._worker_fixture(short_stream, count=1)
        self.assertEqual(runners._mlx_worker(path), 0)
        records = runners._validate_worker_completion(out, request)
        self.assertEqual(records[0]["status"], "truncated")
        self.assertIsNone(records[0]["output_text"])
        result = read_json(out / "worker-result.json")
        result["rows"] = 2
        (out / "worker-result.json").unlink()
        write_json(out / "worker-result.json", seal(result))
        with self.assertRaisesRegex(R5Error, "complete bound result set"):
            runners._validate_worker_completion(out, request)

    def test_internal_worker_rejects_bad_timeout_before_loading_any_model(self):
        path, _, request, observations = self._worker_fixture(lambda *_args, **_kwargs: iter(()), count=1)
        request["timeout_seconds"] = 0
        path.unlink(); write_json(path, seal(request))
        with self.assertRaisesRegex(R5Error, "resource window"):
            runners._mlx_worker(path)
        self.assertEqual(observations["loads"], 0)
        self.assertEqual(observations["entered"], 0)


if __name__ == "__main__":
    unittest.main()
