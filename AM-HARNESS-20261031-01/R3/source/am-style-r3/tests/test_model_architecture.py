"""Architecture gates only; no GPU packages, weights or actual Qwen execution."""
import copy
import hashlib
import json
import struct
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from training.common import TrainingInputError, file_hash
from training.runtime import (TRANSFORMERS_ARCHITECTURE_COMMIT, _causal_registry,
                              _installed_transformers_sources, load_base,
                              validate_loaded_text_model, validate_model_architecture)


REGISTRY = '''from collections import OrderedDict
MODEL_FOR_CAUSAL_LM_MAPPING_NAMES = OrderedDict([
    ("qwen3_5", "Qwen3_5ForCausalLM"),
    ("qwen3_5_text", "Qwen3_5ForCausalLM"),
])
'''


def architecture_fixture(root, *, composite=True):
    text = {"model_type": "qwen3_5_text", "num_hidden_layers": 2, "tie_word_embeddings": False}
    if composite:
        cfg = {"model_type": "qwen3_5", "architectures": ["Qwen3_5ForConditionalGeneration"],
               "text_config": text, "vision_config": {"model_type": "qwen3_5_vision"}}
    else:
        cfg = {**text, "architectures": ["Qwen3_5ForCausalLM"]}
    (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    prefix = "model.language_model." if composite else "model."
    names = [prefix + "embed_tokens.weight", prefix + "norm.weight", "lm_head.weight",
             prefix + "layers.0.self_attn.q_proj.weight", prefix + "layers.1.self_attn.q_proj.weight"]
    if composite:
        names.append("model.visual.patch_embed.proj.weight")
    # A tiny header fixture, never represented as a loadable or real model.
    header = json.dumps({name: {"dtype": "F32", "shape": [0], "data_offsets": [0, 0]}
                         for name in names}).encode()
    (root / "model.safetensors").write_bytes(struct.pack("<Q", len(header)) + header)
    return {
        "local_model_path": str(root), "model_type": cfg["model_type"],
        "metadata_sha256": {"config.json": file_hash(root / "config.json")},
        "weight_files_sha256": {"model.safetensors": file_hash(root / "model.safetensors")},
        "package_versions": {"transformers": "fixture-version"},
        "training_architecture": {
            "route": "qwen3_5_text_compat" if composite else "qwen3_5_native_text",
            "auto_class": "AutoModelForCausalLM", "expected_model_class": "Qwen3_5ForCausalLM",
            "expected_config_model_type": "qwen3_5_text", "text_only": True,
            "transformers_source_commit": TRANSFORMERS_ARCHITECTURE_COMMIT,
        },
    }


class ModelArchitectureTests(unittest.TestCase):
    def test_missing_route_blocks_before_heavy_import_or_model_load(self):
        # The environment has no torch/transformers. A missing route must fail
        # with our input error, before an ImportError or attempted model load.
        with self.assertRaisesRegex(TrainingInputError, "training_architecture"):
            load_base({}, {})

    def test_unknown_or_native_vlm_route_is_not_guessed(self):
        with self.assertRaisesRegex(TrainingInputError, "Unsupported architecture route"):
            validate_model_architecture({"training_architecture": {"route": "native_vlm"}})

    def test_composite_and_native_text_metadata_routes(self):
        for composite in (True, False):
            with self.subTest(composite=composite), tempfile.TemporaryDirectory() as tmp:
                manifest = architecture_fixture(Path(tmp), composite=composite)
                with patch("training.runtime._installed_transformers_sources", return_value={"models/auto/modeling_auto.py": REGISTRY}):
                    report = validate_model_architecture(manifest)
                self.assertEqual(report["loaded_model_class"], "Qwen3_5ForCausalLM")
                self.assertFalse(report["tensor_data_read"])
                self.assertFalse(report["training_compatibility_proven"])

    def test_top_level_compatibility_requires_actual_registry_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = architecture_fixture(Path(tmp))
            source = REGISTRY.replace('("qwen3_5", "Qwen3_5ForCausalLM"),', '')
            with patch("training.runtime._installed_transformers_sources", return_value={"models/auto/modeling_auto.py": source}):
                with self.assertRaisesRegex(TrainingInputError, "registry lacks"):
                    validate_model_architecture(manifest)

    def test_wrong_route_config_or_source_commit_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = architecture_fixture(Path(tmp))
            bad = copy.deepcopy(manifest)
            bad["training_architecture"]["transformers_source_commit"] = "0" * 40
            with self.assertRaisesRegex(TrainingInputError, "exact audited"):
                validate_model_architecture(bad)
            bad = copy.deepcopy(manifest)
            bad["training_architecture"]["route"] = "qwen3_5_native_text"
            with self.assertRaisesRegex(TrainingInputError, "model_type"):
                validate_model_architecture(bad)

    def test_prequantized_composite_checkpoint_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = architecture_fixture(root)
            cfg = json.loads((root / "config.json").read_text())
            cfg["quantization_config"] = {"quant_method": "fixture-only"}
            (root / "config.json").write_text(json.dumps(cfg))
            manifest["metadata_sha256"]["config.json"] = file_hash(root / "config.json")
            with self.assertRaisesRegex(TrainingInputError, "unquantized"):
                validate_model_architecture(manifest)

    def test_missing_language_layer_blocked_from_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = architecture_fixture(root)
            cfg = json.loads((root / "config.json").read_text())
            cfg["text_config"]["num_hidden_layers"] = 3
            (root / "config.json").write_text(json.dumps(cfg))
            manifest["metadata_sha256"]["config.json"] = file_hash(root / "config.json")
            with patch("training.runtime._installed_transformers_sources", return_value={"models/auto/modeling_auto.py": REGISTRY}):
                with self.assertRaisesRegex(TrainingInputError, "language layer set"):
                    validate_model_architecture(manifest)

    def test_local_source_bytes_and_installed_version_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "models/auto/modeling_auto.py"
            path.parent.mkdir(parents=True)
            raw = REGISTRY.encode()
            path.write_bytes(raw)
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            with patch("training.runtime.TRANSFORMERS_ARCHITECTURE_BLOBS", {"models/auto/modeling_auto.py": blob}), \
                 patch("training.runtime.importlib.metadata.version", return_value="fixture-version"), \
                 patch("training.runtime.importlib.util.find_spec", return_value=types.SimpleNamespace(submodule_search_locations=[str(root)])):
                sources = _installed_transformers_sources("fixture-version")
                self.assertEqual(_causal_registry(sources["models/auto/modeling_auto.py"])["qwen3_5"], "Qwen3_5ForCausalLM")
                with self.assertRaisesRegex(TrainingInputError, "version differs"):
                    _installed_transformers_sources("other-version")
                path.write_bytes(raw + b"\n# unreviewed source change\n")
                with self.assertRaisesRegex(TrainingInputError, "Unaudited Transformers"):
                    _installed_transformers_sources("fixture-version")

    def test_loaded_language_weights_must_all_match(self):
        Qwen3_5ForCausalLM = type("Qwen3_5ForCausalLM", (), {})
        model = Qwen3_5ForCausalLM()
        model.config = types.SimpleNamespace(model_type="qwen3_5_text")
        good = {"missing_keys": [], "unexpected_keys": ["model.visual.patch_embed.weight", "mtp.weight"],
                "mismatched_keys": [], "error_msgs": []}
        validate_loaded_text_model(model, good)
        for key, value in (("missing_keys", ["model.layers.0.weight"]),
                           ("mismatched_keys", [("lm_head.weight", [1], [2])]),
                           ("unexpected_keys", ["model.language_model.layers.0.weight"])):
            with self.subTest(key=key):
                bad = {**good, key: value}
                with self.assertRaises(TrainingInputError):
                    validate_loaded_text_model(model, bad)
        with self.assertRaisesRegex(TrainingInputError, "omitted"):
            validate_loaded_text_model(model, {})
        model.config.model_type = "qwen3_5"
        with self.assertRaisesRegex(TrainingInputError, "text-only class/config"):
            validate_loaded_text_model(model, good)


if __name__ == "__main__":
    unittest.main()
