"""Synthetic test fixtures only. No real judge calls or human approvals created."""
import copy
import unittest

from am_style.contracts import ModelResult, SpeechFrame, digest as object_hash
from am_style.data import DataError, canonical, digest
from am_style.render import render_canonical
from am_style.silver import (export_silver_sft, judge_candidate, prepare_silver_sft_row,
                            validate_silver_sft_row)
from am_style.synthetic import generate_projected_seeds
from training.common import TrainingInputError, validate_rows


def fixture():
    record = generate_projected_seeds()[0]
    record["split"] = "train"
    text = render_canonical(SpeechFrame.freeze(record["frame"]))
    record["candidates"]["model_fixture"] = {"text": text, "sha256": digest(text), "available": True,
        "origin": "model_call", "provider": "fixture-generator", "model": "fixture-only-not-real",
        "run_id": "fixture-generation-1"}
    record["silver_selection"] = "model_fixture"
    completion = [{"role": "assistant", "content": canonical({"text": text})}]
    anchor = {"schema": "am-style-gold-anchor/1", "version": "fixture-gold/1",
        "policy_sha256": object_hash(record["style_policy"]), "examples": [{
            "id": "fictional-anchor-not-an-actual-human-rating", "prompt": record["prompt"], "completion": completion,
            "provenance": {"source_kind": "human_reviewed_synthetic", "human_approved": True,
                "facts_pass": True, "style_pass": True, "acceptable": True,
                "reviewer": "fixture-only", "reviewed_at": "2026-11-02T10:00:00+08:00",
                "group_id": "fixture-gold-anchor", "split": "calibration",
                "prompt_sha256": object_hash(record["prompt"]), "candidate_sha256": object_hash(completion)}}]}

    class FakeJudge:
        def __init__(self, provider):
            self.provider = provider
        def generate(self, request):
            response = {"decision": "pass", "facts_pass": True, "style_pass": True,
                        "rules_pass": True, "reason": "unit-test fixture only"}
            return ModelResult(canonical({"text": canonical(response)}), self.provider,
                               "fixture-only-not-real", 0, "{}")
    record["silver_judges"] = [judge_candidate(FakeJudge(provider), record, "model_fixture", anchor)
                                for provider in ("fixture-provider-1", "fixture-provider-2")]
    return record, anchor


class SilverTests(unittest.TestCase):
    def test_current_unjudged_seeds_still_export_zero(self):
        result = export_silver_sft(generate_projected_seeds(), experimental_only=True)
        self.assertEqual(sum(map(len, result["outputs"].values())), 0)
        self.assertFalse(result["human_approved"])
        self.assertFalse(result["dpo_enabled"])

    def test_small_gold_anchor_is_required(self):
        record, _ = fixture()
        with self.assertRaisesRegex(DataError, "gold anchor"):
            prepare_silver_sft_row(record, gold_anchor=None, experimental_only=True)

    def test_silver_is_explicit_experimental_sft_not_gold_or_dpo(self):
        record, anchor = fixture()
        row = prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)
        self.assertFalse(row["provenance"]["human_approved"])
        kwargs = dict(quality_tier="experimental_silver", experimental_only=True,
                      anchor_sha=object_hash(anchor), policy_sha=object_hash(record["style_policy"]))
        validate_rows([row], split="train", mode="sft", **kwargs)
        with self.assertRaises(TrainingInputError):
            validate_rows([row], split="train", mode="sft")
        with self.assertRaises(TrainingInputError):
            validate_rows([row], split="train", mode="dpo", **kwargs)
        with self.assertRaises(DataError):
            prepare_silver_sft_row(record, gold_anchor=anchor)

    def test_two_calls_of_same_judge_do_not_count_as_independent(self):
        record, anchor = fixture()
        record["silver_judges"][1]["provider"] = record["silver_judges"][0]["provider"]
        with self.assertRaisesRegex(DataError, "independent"):
            prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)

    def test_changed_assessment_or_forged_human_flag_rejected(self):
        record, anchor = fixture()
        record["silver_judges"][0]["response"]["reason"] = "modified"
        with self.assertRaisesRegex(DataError, "hash mismatch"):
            prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)
        record, anchor = fixture()
        row = prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)
        row["provenance"]["human_approved"] = True
        with self.assertRaisesRegex(DataError, "human-approval"):
            validate_silver_sft_row(row, split="train", anchor_sha=object_hash(anchor),
                                    policy_sha=object_hash(record["style_policy"]))

    def test_model_agreement_does_not_override_host_fact_check(self):
        record, anchor = fixture()
        bad = "测试已经完成了。"
        record["candidates"]["model_fixture"].update(text=bad, sha256=digest(bad))
        with self.assertRaisesRegex(DataError, "bounded factual"):
            prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)

    def test_calibration_and_sealed_records_never_silver_train(self):
        for split in ("calibration", "sealed_test"):
            record, anchor = fixture()
            record["split"] = split
            with self.assertRaisesRegex(DataError, "held-out"):
                prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)

    def test_dev_or_test_answers_cannot_be_gold_judge_anchors(self):
        for split in ("dev", "sealed_test", "test"):
            record, anchor = fixture()
            anchor["examples"][0]["provenance"]["split"] = split
            with self.assertRaisesRegex(DataError, "train/calibration"):
                prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)
        record, anchor = fixture()
        record["split"] = "dev"
        record["group_id"] = "fixture-gold-anchor"
        with self.assertRaisesRegex(DataError, "group leaked"):
            prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)


if __name__ == "__main__":
    unittest.main()
