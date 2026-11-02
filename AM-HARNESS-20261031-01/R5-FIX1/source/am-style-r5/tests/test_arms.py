"""Metadata-only attribution tests; no real model, trained adapter or consumer.

The pure formatting fixtures are not submitted through the public real-run
builder and are never described as a successful pilot. Queue tests use this
test process PID and empty temporary files/directories, solely to exercise
path/hash binding. They do not authenticate a production service or send work.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from training.common import TrainingInputError
from training.mlx_r4_contracts import BASE_REPO, BASE_REVISION
from training.mlx_r4_resources import PRODUCTION_MODEL, PRODUCTION_DIGEST

from am_style_r5.arms import (_compose_runtime_arms, build_queue_config,
                              build_runtime_arms)
from am_style_r5.common import R5Error, file_hash, object_hash, write_json
from am_style_r5.runners import MLX_SETTINGS, QWEN_SETTINGS


ROOT = Path(__file__).resolve().parents[1]


class ArmMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r5-arm-metadata-fixture-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def formatting_fixture(self):
        # Deliberately incomplete metadata: it cannot pass validate_base or a
        # pilot validator. This fixture tests formatting, not execution gates.
        manifest = {"fixture_only": True, "revision": "a" * 40,
                    "files": {"tokenizer.json": {"sha256": "b" * 64}}}
        selected = {"root": str(self.root / "nonexistent-pilot"),
                    "adapter_sha256": "c" * 64, "request_sha256": "d" * 64,
                    "result_file_sha256": "e" * 64,
                    "train_sha256": "7" * 64, "dev_sha256": "8" * 64}
        return manifest, selected

    def queue_metadata_fixture(self):
        """Create only real tiny metadata files, not real service artifacts."""
        service = self.root / "fictional-service"
        queue = service / "state/am-conversation-r2"
        for name in ("requests", "results"):
            (queue / name).mkdir(parents=True)
        paths = {}
        for key, filename in (("lease_file", "model-coordinator.lock"),
                              ("gateway_db", "fictional-gateway.db"),
                              ("chat_db", "fictional-chat.db")):
            path = service / filename
            path.write_bytes(b"METADATA TEST FIXTURE; NOT A PRODUCTION DATABASE\n")
            paths[key] = str(path)
        poc = self.root / "fictional-poc.json"
        host = self.root / "fictional-host.json"
        write_json(poc, {"fixture_only": True, "service": {"root_directory": str(service)}})
        write_json(host, {"fixture_only": True, "poc_config": str(poc)})
        manifest = {"fixture_only": True, "service": {**paths,
            "protected_config_files": {str(poc): file_hash(poc), str(host): file_hash(host)},
            "expected_model": PRODUCTION_MODEL, "expected_digest": PRODUCTION_DIGEST}}
        path = self.root / "fictional-service-manifest.json"
        write_json(path, manifest)
        return path, host, queue

    def test_pure_formatting_keeps_reference_base_and_selected_pilot_distinct(self):
        manifest, chosen = self.formatting_fixture()
        arms = _compose_runtime_arms(manifest, chosen)
        self.assertEqual(set(arms), {"production_q8", "mlx_base", "mlx_sft"})
        production = arms["production_q8"]
        self.assertEqual(production["comparison_role"], "external_reference")
        self.assertEqual(production["provider"], "existing_original_coordinator_queue")
        self.assertEqual((production["model"], production["model_digest"]), (PRODUCTION_MODEL, PRODUCTION_DIGEST))
        self.assertEqual(production["generation_settings"], QWEN_SETTINGS)
        for name in ("mlx_base", "mlx_sft"):
            self.assertEqual(arms[name]["base_revision"], manifest["revision"])
            self.assertEqual(arms[name]["model_manifest_sha256"], object_hash(manifest))
            self.assertEqual(arms[name]["tokenizer_sha256"], manifest["files"]["tokenizer.json"]["sha256"])
            self.assertEqual(arms[name]["generation_settings"], MLX_SETTINGS)
            self.assertFalse(arms[name]["production_equivalence_verified"])
        self.assertIsNone(arms["mlx_base"]["adapter_sha256"])
        self.assertEqual(arms["mlx_sft"]["adapter_sha256"], chosen["adapter_sha256"])
        self.assertEqual(arms["mlx_sft"]["pilot_request_sha256"], chosen["request_sha256"])
        self.assertEqual(arms["mlx_sft"]["pilot_result_file_sha256"], chosen["result_file_sha256"])
        self.assertEqual(arms["mlx_sft"]["train_file_sha256"], chosen["train_sha256"])
        self.assertEqual(arms["mlx_sft"]["dev_file_sha256"], chosen["dev_sha256"])

    def test_same_adapter_bytes_do_not_erase_the_selected_pilot_identity(self):
        manifest, chosen = self.formatting_fixture()
        original = _compose_runtime_arms(manifest, chosen)
        other_run = dict(chosen, request_sha256="f" * 64, result_file_sha256="1" * 64)
        changed = _compose_runtime_arms(manifest, other_run)
        self.assertEqual(original["mlx_sft"]["adapter_sha256"], changed["mlx_sft"]["adapter_sha256"])
        self.assertNotEqual(object_hash(original["mlx_sft"]), object_hash(changed["mlx_sft"]))
        self.assertEqual(original["mlx_base"], changed["mlx_base"])
        self.assertEqual(original["production_q8"], changed["production_q8"])

    def test_runner_identity_gate_rejects_another_request_or_result_even_with_same_adapter(self):
        # This exercises only the identity comparison, not a model/weight gate.
        from am_style_r5.runners import _mlx_identity
        manifest, chosen = self.formatting_fixture()
        plan = {"arms": _compose_runtime_arms(manifest, chosen)}
        self.assertEqual(_mlx_identity(plan, "mlx_sft", manifest, chosen), plan["arms"]["mlx_sft"])
        for key in ("adapter_sha256", "request_sha256", "result_file_sha256"):
            with self.subTest(key=key), self.assertRaisesRegex(R5Error, "checkpoint/run differ"):
                _mlx_identity(plan, "mlx_sft", manifest, dict(chosen, **{key: "0" * 64}))
        with self.assertRaisesRegex(R5Error, "Base arm must not contain"):
            _mlx_identity(plan, "mlx_base", manifest, chosen)

    def test_selected_pilot_training_data_are_part_of_the_sft_identity(self):
        manifest, chosen = self.formatting_fixture()
        original = _compose_runtime_arms(manifest, chosen)
        for key in ("train_sha256", "dev_sha256"):
            with self.subTest(key=key):
                changed = _compose_runtime_arms(manifest, dict(chosen, **{key: "0" * 64}))
                self.assertNotEqual(object_hash(original["mlx_sft"]), object_hash(changed["mlx_sft"]))
                self.assertEqual(original["mlx_base"], changed["mlx_base"])
                self.assertEqual(original["production_q8"], changed["production_q8"])

    def test_settings_are_not_shared_mutable_objects_between_arms(self):
        manifest, chosen = self.formatting_fixture()
        original_mlx, original_qwen = deepcopy(MLX_SETTINGS), deepcopy(QWEN_SETTINGS)
        arms = _compose_runtime_arms(manifest, chosen)
        arms["mlx_sft"]["generation_settings"]["seed"] = 999
        arms["production_q8"]["generation_settings"]["max_tokens"] = 1
        self.assertEqual(arms["mlx_base"]["generation_settings"], original_mlx)
        self.assertEqual(MLX_SETTINGS, original_mlx)
        self.assertEqual(QWEN_SETTINGS, original_qwen)

    def test_public_builder_refuses_formatting_fixture_as_real_metadata(self):
        manifest, chosen = self.formatting_fixture()
        path = self.root / "not-a-real-base.json"
        write_json(path, manifest)
        with self.assertRaisesRegex(TrainingInputError, "Wrong R4 MLX base manifest"):
            build_runtime_arms(path, chosen["root"])

    def test_structurally_present_dummy_weights_cannot_replace_fixed_source_provenance(self):
        # These bytes are not safetensors; no loader ever reads them. The real
        # metadata validator must refuse the missing reviewed provenance first.
        model = self.root / "dummy-model"
        model.mkdir()
        contents = {
            "config.json": json.dumps({"model_type": "qwen3_5", "num_hidden_layers": 64,
                                       "tie_word_embeddings": False, "quantization": {"bits": 4}}),
            "tokenizer.json": "{}", "tokenizer_config.json": "{}", "chat_template.jinja": "fixture",
            "model.safetensors.index.json": "{}", "model-00001.safetensors": "NOT MODEL WEIGHTS",
        }
        for name, text in contents.items():
            (model / name).write_text(text, encoding="utf-8")
        manifest = {"schema": "am-style-mlx-r4-base/1", "repo": BASE_REPO,
            "revision": BASE_REVISION, "scope": "independent_official_HF_text_branch",
            "production_equivalence_verified": False, "local_model_path": str(model),
            "files": {name: {"bytes": (model / name).stat().st_size,
                              "sha256": file_hash(model / name)} for name in contents}}
        path = self.root / "dummy-base.json"
        write_json(path, manifest)
        with self.assertRaisesRegex(TrainingInputError, "Only the source manifests sealed in R3"):
            build_runtime_arms(path, self.root / "absent-real-pilot")

    def test_cold_public_builder_missing_inputs_never_imports_model_libraries(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(map(str, (ROOT / "src",
            ROOT / "baseline/am-conversation-r1/src", ROOT / "baseline/am-style-r3")))
        script = """
import json, sys
from am_style_r5.arms import build_runtime_arms
try:
    build_runtime_arms(sys.argv[1], sys.argv[2])
except FileNotFoundError:
    failure = 'missing_real_input_refused'
else:
    raise AssertionError('missing real files were accepted')
loaded = [n for n in sys.modules if n == 'mlx' or n.startswith('mlx.') or n == 'mlx_lm' or n.startswith('mlx_lm.')]
print(json.dumps({'status': failure, 'model_modules_loaded': loaded}))
"""
        result = subprocess.run([sys.executable, "-c", script,
                                 str(self.root / "missing-manifest.json"), str(self.root / "missing-run")],
                                cwd=self.root, env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "missing_real_input_refused")
        self.assertEqual(report["model_modules_loaded"], [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_queue_builder_binds_existing_fixture_files_without_submitting_requests(self):
        manifest, host, queue = self.queue_metadata_fixture()
        before = {str(p): file_hash(p) for p in self.root.rglob("*") if p.is_file()}
        # The observed PID is this test process, not a claimed real consumer.
        config = build_queue_config(manifest, host, queue, os.getpid())
        self.assertEqual(config["schema"], "am-r5-original-queue-config/1")
        self.assertEqual(config["service_manifest_sha256"], file_hash(manifest))
        self.assertEqual(config["expected_consumer_pid"], os.getpid())
        self.assertTrue(config["operator_must_verify_single_original_consumer"])
        self.assertEqual(config["queue_root"], str(queue))
        self.assertEqual(list((queue / "requests").iterdir()), [])
        self.assertEqual(list((queue / "results").iterdir()), [])
        self.assertEqual(before, {str(p): file_hash(p) for p in self.root.rglob("*") if p.is_file()})

    def test_queue_builder_rejects_missing_or_changed_real_inputs_and_invalid_pid(self):
        manifest, host, queue = self.queue_metadata_fixture()
        for pid in (0, -1, True, "123"):
            with self.subTest(pid=pid), self.assertRaisesRegex(R5Error, "observed original consumer PID"):
                build_queue_config(manifest, host, queue, pid)
        with self.assertRaisesRegex(R5Error, "must be absolute"):
            build_queue_config("relative.json", host, queue, os.getpid())
        with self.assertRaises(FileNotFoundError):
            build_queue_config(self.root / "missing.json", host, queue, os.getpid())
        (queue / "requests").rmdir()
        with self.assertRaisesRegex(R5Error, "existing original probe queue"):
            build_queue_config(manifest, host, queue, os.getpid())
        (queue / "requests").mkdir()
        with host.open("a", encoding="utf-8") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(TrainingInputError, "Protected production config differs"):
            build_queue_config(manifest, host, queue, os.getpid())


if __name__ == "__main__":
    unittest.main()
