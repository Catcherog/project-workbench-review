"""Contract tests only; these do not simulate or claim model-training quality."""
import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from training.common import (TrainingInputError, file_hash, load_training_data, object_hash,
                             validate_model_manifest, validate_rows, validate_sft_checkpoint,
                             validate_tokenization, write_json)
from training.preflight import inspect_local
from training.runtime import verify_reference_copy
from training.train_sft import check_prepared_sft_loss
from training.train_dpo import validate_beta


def response(text):
    return [{"role": "assistant", "content": json.dumps({"text": text}, ensure_ascii=False)}]


def row(mode="sft", split="train", rid="one", group="group-one", question="进度呢？"):
    prompt = [{"role": "system", "content": "只按核实结果回答。"}, {"role": "user", "content": question}]
    result = {"id": rid, "prompt": prompt, "provenance": {
        "schema": "am-style-data/1", "group_id": group, "split": split,
        "source_kind": "human_reviewed_synthetic", "source_sha256": "1" * 64,
        "style_policy_version": "policy-one", "reviewer": "test-human", "reviewed_at": "2026-11-02",
        "facts_pass": True, "style_pass": True, "acceptable": True, "human_approved": True,
        "runtime_alignment": "aligned", "host_contract_version": "r3-1", "prompt_sha256": object_hash(prompt),
    }}
    if mode == "sft":
        result["completion"] = response("测试还在进行。")
        result["provenance"]["candidate_sha256"] = object_hash(result["completion"])
    else:
        result.update(chosen=response("测试还在进行。"), rejected=response("当前测试状态为进行中。"))
        result["provenance"].update(chosen_sha256=object_hash(result["chosen"]),
                                     rejected_sha256=object_hash(result["rejected"]),
                                     preference_source="human", rejected_facts_pass=True)
    return result


def model_fixture(path):
    (path / "config.json").write_text('{"model_type":"fixture-only"}', encoding="utf-8")
    (path / "tokenizer_config.json").write_text('{"chat_template":"fixture-template"}', encoding="utf-8")
    (path / "tokenizer.json").write_text('{}', encoding="utf-8")
    (path / "model.safetensors").write_bytes(b"not-real-weights-contract-test-only")
    import hashlib
    return {
        "schema": "am-style-model/1", "runtime_model": "qwen-tag-under-test",
        "runtime_mapping_evidence": "fixture-only-not-a-real-mapping", "base_model_id": "fixture/model",
        "base_revision": "a" * 40, "tokenizer_model_id": "fixture/model", "tokenizer_revision": "a" * 40,
        "local_model_path": str(path), "model_type": "fixture-only", "trust_remote_code": False,
        "metadata_sha256": {n: file_hash(path / n) for n in ("config.json", "tokenizer_config.json", "tokenizer.json")},
        "chat_template_sha256": hashlib.sha256(b"fixture-template").hexdigest(),
        "weight_files_sha256": {"model.safetensors": file_hash(path / "model.safetensors")},
    }


class TrainingDataTests(unittest.TestCase):
    def test_valid_sft_and_dpo_contracts(self):
        validate_rows([row()], split="train", mode="sft")
        validate_rows([row("dpo")], split="train", mode="dpo")

    def test_relative_preference_is_not_approval(self):
        r = row("dpo")
        r["provenance"]["acceptable"] = False
        with self.assertRaisesRegex(TrainingInputError, "acceptable"):
            validate_rows([r], split="train", mode="dpo")

    def test_unreviewed_synthetic_rejected(self):
        r = row()
        r["provenance"]["source_kind"] = "synthetic"
        with self.assertRaisesRegex(TrainingInputError, "Unreviewed"):
            validate_rows([r], split="train", mode="sft")

    def test_calibration_not_silently_trainable(self):
        r = row()
        r["provenance"]["split"] = "calibration"
        with self.assertRaises(TrainingInputError):
            validate_rows([r], split="train", mode="sft")

    def test_review_does_not_survive_response_edit(self):
        r = row()
        r["completion"] = response("测试完成了。")
        with self.assertRaisesRegex(TrainingInputError, "changed after review"):
            validate_rows([r], split="train", mode="sft")

    def test_dpo_fact_error_is_not_style_pair(self):
        r = row("dpo")
        r["provenance"]["rejected_facts_pass"] = False
        with self.assertRaisesRegex(TrainingInputError, "fact-correct"):
            validate_rows([r], split="train", mode="dpo")

    def test_missing_runtime_alignment_rejected(self):
        r = row()
        del r["provenance"]["runtime_alignment"]
        with self.assertRaisesRegex(TrainingInputError, "alignment"):
            validate_rows([r], split="train", mode="sft")

    def test_no_training_on_plain_text_when_runtime_expects_json(self):
        r = row()
        r["completion"][0]["content"] = "测试还在进行。"
        with self.assertRaisesRegex(TrainingInputError, "runtime JSON"):
            validate_rows([r], split="train", mode="sft")

    def test_group_leakage_blocked_even_with_different_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cfg = {"style_policy_version": "policy-one", "host_contract_version": "r3-1"}
            for split, r in (("train", row()), ("dev", row(split="dev", rid="two", question="现在怎么样？"))):
                p = tmp / f"{split}.jsonl"
                p.write_text(json.dumps(r, ensure_ascii=False) + "\n", encoding="utf-8")
                cfg[split + "_file"] = str(p)
                cfg[split + "_sha256"] = file_hash(p)
            with self.assertRaisesRegex(TrainingInputError, "groups leaked"):
                load_training_data(cfg, "sft")

    def test_mixed_or_stale_host_contract_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"style_policy_version": "policy-one", "host_contract_version": "new-host"}
            for split, r in (("train", row()), ("dev", row(split="dev", rid="two", group="another-group", question="另一种问题"))):
                r["provenance"]["host_contract_version"] = "old-host" if split == "train" else "new-host"
                p = Path(tmp) / f"{split}.jsonl"
                p.write_text(json.dumps(r, ensure_ascii=False) + "\n", encoding="utf-8")
                cfg[split + "_file"] = str(p)
                cfg[split + "_sha256"] = file_hash(p)
            with self.assertRaisesRegex(TrainingInputError, "host contract"):
                load_training_data(cfg, "sft")
            del cfg["host_contract_version"]
            with self.assertRaisesRegex(TrainingInputError, "host_contract_version"):
                load_training_data(cfg, "sft")

    def test_dpo_beta_rejects_no_learning_and_nonfinite_values(self):
        for value in (0, -0.1, float("nan"), float("inf"), True, None, "invalid"):
            with self.assertRaisesRegex(TrainingInputError, "finite positive"):
                validate_beta({"beta": value})
        self.assertEqual(validate_beta({"beta": 0.1}), 0.1)

    def test_loss_mask_preflight_rejects_truncation(self):
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs):
                return [1, 2] if messages[-1]["role"] == "user" else [1, 2, 3, 4]
        with self.assertRaisesRegex(TrainingInputError, "overlength"):
            validate_tokenization(Tokenizer(), [row()], 3, "sft")

    def test_trl_prepared_labels_need_no_removed_completion_mask(self):
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs):
                return [1, 2] if messages[-1]["role"] == "user" else [1, 2, 3, 4]
        # TRL 1.17.1 removes completion_mask after constructing this labels field.
        dataset = [{"input_ids": [1, 2, 3, 4], "labels": [-100, -100, 3, 4]}]
        def collator(samples):
            return {"labels": [samples[0]["labels"] + [-100]]}
        report = check_prepared_sft_loss(dataset, collator, Tokenizer(), [row()])
        self.assertEqual(report["supervised_completion_tokens"], 2)

    def test_prepared_or_collated_mask_drift_is_rejected(self):
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs):
                return [1, 2] if messages[-1]["role"] == "user" else [1, 2, 3, 4]
        dataset = [{"input_ids": [1, 2, 3, 4], "labels": [-100, -100, 3, 4]}]
        for corrupt in ([1, 2, 3, 4], [-100, -100, -100, -100], [-100, -100, 3]):
            with self.assertRaises(TrainingInputError):
                check_prepared_sft_loss(dataset, lambda samples: {"labels": [corrupt]}, Tokenizer(), [row()])
        dataset[0]["labels"] = [1, 2, 3, 4]
        with self.assertRaisesRegex(TrainingInputError, "Prepared labels"):
            check_prepared_sft_loss(dataset, lambda samples: {"labels": [samples[0]["labels"]]}, Tokenizer(), [row()])


class ModelManifestTests(unittest.TestCase):
    def test_metadata_inspection_does_not_hash_weights_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = model_fixture(root)
            report = inspect_local(root)
            self.assertIsNone(report["weight_files"]["model.safetensors"]["sha256"])
            self.assertTrue(validate_model_manifest(manifest)["metadata_verified"])
            self.assertFalse(validate_model_manifest(manifest)["weights_verified"])

    def test_unresolved_ollama_tag_cannot_start_training(self):
        with self.assertRaises(TrainingInputError):
            validate_model_manifest({"schema": "am-style-model/1", "runtime_model": "qwen3.8:27b-bartowski-q8_0"})

    def test_template_change_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = model_fixture(root)
            (root / "chat_template.jinja").write_text("changed-template", encoding="utf-8")
            with self.assertRaisesRegex(TrainingInputError, "template hash"):
                validate_model_manifest(manifest)

    def test_weight_change_rejected_on_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = model_fixture(root)
            (root / "model.safetensors").write_bytes(b"changed")
            with self.assertRaisesRegex(TrainingInputError, "Weight mismatch"):
                validate_model_manifest(manifest, verify_weights=True)

    def test_dpo_cannot_use_unfinished_or_different_sft_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = model_fixture(root)
            with self.assertRaisesRegex(TrainingInputError, "actually completed"):
                validate_sft_checkpoint(manifest, {"stage": "sft", "training_completed": False}, root)
            with self.assertRaisesRegex(TrainingInputError, "different base"):
                validate_sft_checkpoint(manifest, {"stage": "sft", "training_completed": True,
                                                   "model_manifest_sha256": "f" * 64}, root)


class Param:
    def __init__(self, value, pointer):
        self.value = value
        self.pointer = pointer
        self.requires_grad = True
    def detach(self):
        return self
    def data_ptr(self):
        return self.pointer
    def requires_grad_(self, value):
        self.requires_grad = value


class FakeModel:
    def __init__(self, reference_value=7, reference_pointer=2, has_reference=True):
        self.peft_config = {"default": {}, **({"ref": {}} if has_reference else {})}
        self.params = {"layer.lora_A.default.weight": Param(7, 1), "layer.lora_A.ref.weight": Param(reference_value, reference_pointer)}
    def set_adapter(self, name):
        pass
    def named_parameters(self):
        return self.params.items()
    def get_parameter(self, name):
        if name not in self.params:
            raise AttributeError(name)
        return self.params[name]


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.fake_torch = types.SimpleNamespace(equal=lambda a, b: a.value == b.value)

    def test_reference_is_equal_distinct_and_frozen(self):
        model = FakeModel()
        with patch.dict("sys.modules", {"torch": self.fake_torch}):
            names = verify_reference_copy(model)
        self.assertFalse(model.get_parameter(names[0]).requires_grad)

    def test_missing_reference_does_not_fall_back_to_base(self):
        with patch.dict("sys.modules", {"torch": self.fake_torch}):
            with self.assertRaisesRegex(TrainingInputError, "did not create"):
                verify_reference_copy(FakeModel(has_reference=False))

    def test_wrong_sft_reference_and_shared_storage_rejected(self):
        with patch.dict("sys.modules", {"torch": self.fake_torch}):
            for model in (FakeModel(reference_value=0), FakeModel(reference_pointer=1)):
                with self.assertRaisesRegex(TrainingInputError, "aliased or not"):
                    verify_reference_copy(model)


if __name__ == "__main__":
    unittest.main()
