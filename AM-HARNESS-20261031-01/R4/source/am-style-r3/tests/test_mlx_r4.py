"""Pure-Python protocol tests, never evidence of actual MLX/kernel training."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from am_style.contracts import StylePolicy
from am_style.prompt import build_messages, coordinator_messages
from am_style import prompt as runtime_prompt

from training.common import TrainingInputError, file_hash, object_hash
from training.mlx_r4 import execute_phases, preflight
from training.mlx_r4_contracts import (LORA, compare_teacher, encode_row, require_finite_update,
                                      validate_base, validate_native_prompt, validate_plan)
from training.mlx_r4_resources import ResourcePause, check_metrics
from training.mlx_r4_runtime import _assert_adapter_equal


def synthetic_fixture(index=0, *, split="train", group=None):
    """In-memory test approval; never exported into the real gold dataset."""
    frame = {"question": f"fixture-{split}-{index}", "family": "query", "context": [], "obligations": ["x"],
             "units": [{"covers": ["x"], "variants": ["fixture only"]}], "deferred_gap_count": 0}
    prompt = coordinator_messages(build_messages(frame, StylePolicy(version="test-policy", realization="free")))
    completion = [{"role": "assistant", "content": '{"text":"Fixture answer."}'}]
    return {"id": f"fixture-{split}-{index}", "prompt": prompt, "completion": completion,
            "provenance": {"schema": "am-style-data/1", "split": split, "group_id": group or f"{split}-group-{index % (8 if split == 'train' else 4)}",
             "source_kind": "human_reviewed_synthetic", "source_sha256": "1" * 64, "style_policy_version": "test-policy",
             "reviewer": "test-fixture-not-a-human-review", "reviewed_at": "fixture-time", "host_contract_version": "test-host",
             "runtime_alignment": "aligned", "human_approved": True, "facts_pass": True, "style_pass": True,
             "acceptable": True, "prompt_sha256": object_hash(prompt), "candidate_sha256": object_hash(completion)}}


def config_fixture(root, train_count=24, dev_count=8):
    cfg = {"schema": "am-style-mlx-r4-run/1", "stage": "pilot", "quality_tier": "gold", "epochs": 1,
           "seed": 221, "adapted_layers": 2, "lora": copy.deepcopy(LORA), "learning_rate": 1e-5,
           "weight_decay": 0.01, "optimizer_bias_correction": False, "max_length": 1024,
           "worker_timeout_seconds": 300, "gradient_accumulation": 4,
           "runtime_prompt_builder_sha256": file_hash(Path(runtime_prompt.__file__)),
           "style_policy_version": "test-policy", "host_contract_version": "test-host"}
    for split, count in (("train", train_count), ("dev", dev_count)):
        path = root / (split + ".jsonl")
        path.write_text("".join(json.dumps(synthetic_fixture(i, split=split), ensure_ascii=False) + "\n" for i in range(count)))
        cfg[split + "_file"] = str(path)
        cfg[split + "_sha256"] = file_hash(path)
    return cfg


class FakeTokenizer:
    eos_token_id = 99
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, **kwargs):
        if not tokenize:
            return "fixed-rendered-prompt"
        return [1, 2] if add_generation_prompt else [1, 2, 3, 99, 10]
    def encode(self, text, *, add_special_tokens):
        if add_special_tokens:
            raise AssertionError("No heuristic extra BOS in the reviewed token path")
        return [1, 2]
    def decode(self, ids, **kwargs):
        return "\n" if ids == [10] else ("" if not ids else "unexpected")


class MLXR4ContractsTests(unittest.TestCase):
    def test_real_native_envelope_required(self):
        row = synthetic_fixture()
        validate_native_prompt(row)
        row["prompt"] = json.loads(row["prompt"][0]["content"])["messages"]
        with self.assertRaisesRegex(TrainingInputError, "single-user"):
            validate_native_prompt(row)

    def test_nonempty_tools_or_noncanonical_wrapper_is_rejected(self):
        row = synthetic_fixture()
        value = json.loads(row["prompt"][0]["content"]); value["tools"] = [{"name": "write"}]
        row["prompt"][0]["content"] = json.dumps(value)
        with self.assertRaises(TrainingInputError):
            validate_native_prompt(row)

    def test_shifted_completion_only_mask_and_eos_whitespace(self):
        encoded = encode_row(FakeTokenizer(), synthetic_fixture(), 128)
        self.assertEqual(encoded["labels"], [-100, -100, 3, 99, 10])
        self.assertEqual(encoded["loss_positions"], [1, 2, 3])
        self.assertEqual(encoded["completion_tokens"], 3)
        self.assertEqual(encoded["eos_position"], 3)

    def test_template_drift_truncation_or_missing_eos_is_rejected(self):
        tok = FakeTokenizer()
        tok.encode = lambda *_a, **_kw: [0, 1, 2]
        with self.assertRaisesRegex(TrainingInputError, "token IDs differ"):
            encode_row(tok, synthetic_fixture(), 128)
        with self.assertRaisesRegex(TrainingInputError, "boundary/length"):
            encode_row(FakeTokenizer(), synthetic_fixture(), 4)
        tok = FakeTokenizer(); tok.eos_token_id = None
        with self.assertRaisesRegex(TrainingInputError, "EOS/EOM"):
            encode_row(tok, synthetic_fixture(), 128)

    def test_pilot_cannot_repeat_the_old_single_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config_fixture(Path(tmp), 1, 1)
            with self.assertRaisesRegex(TrainingInputError, "collect data first"):
                validate_plan(cfg)
            cfg["epochs"] = 24
            with self.assertRaisesRegex(TrainingInputError, "one pass"):
                validate_plan(cfg)

    def test_pilot_with_group_split_and_actual_file_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config_fixture(Path(tmp))
            with patch("training.mlx_r4_contracts.validate_mechanics_gate"):
                train, dev = validate_plan(cfg)
            self.assertEqual((len(train), len(dev)), (24, 8))
            self.assertFalse({r["provenance"]["group_id"] for r in train} & {r["provenance"]["group_id"] for r in dev})
            cfg["runtime_prompt_builder_sha256"] = "0" * 64
            with self.assertRaisesRegex(TrainingInputError, "Prompt builder changed"):
                validate_plan(cfg)

    def test_pilot_requires_completed_real_mechanics_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config_fixture(Path(tmp))
            with self.assertRaisesRegex(TrainingInputError, "concrete path"):
                validate_plan(cfg)

    def test_r3_original_group_split_must_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config_fixture(Path(tmp))
            path = Path(cfg["train_file"])
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[0]["provenance"]["group_id"] = "empty-todo-complete-read"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            cfg["train_sha256"] = file_hash(path)
            with self.assertRaisesRegex(TrainingInputError, "original R3"):
                validate_plan(cfg)

    def test_unapproved_rows_or_same_prompts_cannot_inflate_pilot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config_fixture(Path(tmp))
            path = Path(cfg["train_file"])
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[0]["provenance"]["human_approved"] = False
            path.write_text("".join(json.dumps(row) + "\n" for row in rows)); cfg["train_sha256"] = file_hash(path)
            with self.assertRaisesRegex(TrainingInputError, "human_approved"):
                validate_plan(cfg)
            rows[0]["provenance"]["human_approved"] = True
            rows[1]["prompt"] = copy.deepcopy(rows[0]["prompt"])
            rows[1]["provenance"]["prompt_sha256"] = object_hash(rows[1]["prompt"])
            path.write_text("".join(json.dumps(row) + "\n" for row in rows)); cfg["train_sha256"] = file_hash(path)
            with self.assertRaisesRegex(TrainingInputError, "Duplicate prompts"):
                validate_plan(cfg)

    def test_scope_mismatch_or_missing_model_never_downloads(self):
        with self.assertRaisesRegex(TrainingInputError, "schema"):
            validate_base({})
        with self.assertRaisesRegex(TrainingInputError, "independent baseline"):
            validate_base({"schema": "am-style-mlx-r4-base/1", "repo": "another/model"})

    def test_nonfinite_zero_gradient_and_decay_only_updates_are_rejected(self):
        gradient = {"all_finite": True, "l2_norm": 1.0}
        delta = {"all_finite": True, "max_abs": 1e-5, "changed_tensors": 2, "changed_lora_b": 1}
        require_finite_update(gradient, delta)
        for bad in ({**gradient, "l2_norm": 0}, {**gradient, "l2_norm": float("nan")}, {**gradient, "all_finite": False}):
            with self.assertRaisesRegex(TrainingInputError, "Gradient"):
                require_finite_update(bad, delta)
        with self.assertRaisesRegex(TrainingInputError, "LoRA-B"):
            require_finite_update(gradient, {**delta, "changed_lora_b": 0})

    def test_incomplete_adapter_not_accepted_by_strict_false(self):
        with self.assertRaisesRegex(TrainingInputError, "incomplete"):
            _assert_adapter_equal({"layer.lora_a": object(), "layer.lora_b": object()}, {"layer.lora_a": object()}, None)

    def test_unknown_stop_never_starts_fresh_model(self):
        called = []
        def runner(kind, *_args):
            called.append(kind)
            return {"phase": kind, "status": "completed", "stop_confirmed": False, "attempted": True}
        phases = execute_phases(Path("unused"), 30, runner=runner)
        self.assertEqual(called, ["fit"])
        self.assertEqual(len(phases), 2)
        self.assertFalse(phases[1]["attempted"])

    def test_fresh_load_is_sequential_after_confirmed_exit(self):
        called = []
        def runner(kind, *_args):
            called.append(kind)
            return {"phase": kind, "status": "completed", "stop_confirmed": True, "attempted": True}
        execute_phases(Path("unused"), 30, runner=runner)
        self.assertEqual(called, ["fit", "reload"])

    def test_shared_memory_business_and_swap_guards(self):
        metrics = {"available_memory_GiB": 25, "memory_pressure": 1, "pending_business": 0,
                   "swap_used_GiB": 1.1, "loaded_models": []}
        check_metrics(metrics, before_load=True)
        for bad in ({**metrics, "available_memory_GiB": 23}, {**metrics, "pending_business": 1}, {**metrics, "memory_pressure": 4}):
            with self.assertRaises(ResourcePause):
                check_metrics(bad, before_load=True)
        with self.assertRaises(ResourcePause):
            check_metrics({**metrics, "swap_used_GiB": 2.2}, before_load=False, initial_swap_gib=1.1)

    def test_metadata_preflight_never_claims_kernel_pass(self):
        report = preflight({}, {})
        self.assertFalse(report["ready_for_runtime_checks"])
        self.assertFalse(report["model_loading"])
        self.assertEqual(report["numeric_kernel_validation"], "not_run")

    def test_probability_change_can_exist_without_a_quality_claim(self):
        first = {"case": {"token_ids_sha256": "f" * 64, "target_ids": [11, 99], "target_logprobs": [-0.2, -0.1],
                          "probe_coordinates": [[0, 11]], "probe_logits": [1.5]}}
        second = copy.deepcopy(first)
        second["case"]["target_logprobs"][0] = -0.19
        second["case"]["probe_logits"][0] = 1.51
        report = compare_teacher(first, second)
        self.assertGreater(report["rows"][0]["max_target_logprob_abs_delta"], 0)
        self.assertIn("not_established", report["quality_conclusion"])
        with self.assertRaisesRegex(TrainingInputError, "Fresh-loaded"):
            compare_teacher(first, second, reload_check=True)
        self.assertTrue(compare_teacher(second, second, reload_check=True)["reload_within_tolerance"])
        second["case"]["target_ids"][0] = 12
        with self.assertRaisesRegex(TrainingInputError, "inputs/targets"):
            compare_teacher(first, second)


if __name__ == "__main__":
    unittest.main()
