import copy
import json
from pathlib import Path
import unittest

from am_style.data import (
    DataError, PLACEHOLDER, align_runtime_prompt, analyze_ratings,
    assert_split_integrity, canonical, digest, export_training,
    legacy_payload_sha256, read_json, strict_loads, verify_pairs,
)
from am_style.synthetic import generate_seeds, generate_projected_seeds, semantic_challenges


def fixture():
    rows = [{"number": 1, "case_id": "SYN-QRY-01", "a": "林工负责。", "b": "负责人是林工。",
             "question": "谁负责？", "pair_available": True}]
    index = {"entries": 1, "case_ids": ["SYN-QRY-01"], "available_pairs": 1,
             "dataset_sha256": legacy_payload_sha256(rows)}
    ratings = {"version": "r2-fix1-blind/1", "dataset_sha256": index["dataset_sha256"],
               "ratings": {"SYN-QRY-01": {"rating": "B 更好", "severe_error_a": False,
                                          "severe_error_b": False, "comment": ""}}}
    return rows, index, ratings


def approved_record():
    row = copy.deepcopy(generate_seeds()[0])
    row["split"] = "train"
    row = align_runtime_prompt(row, [{"role": "system", "content": "Test host contract"},
                                    {"role": "user", "content": "Who owns demo A?"}], "test-host/1")
    ph = digest(canonical(row["prompt"]))
    for key, candidate in row["candidates"].items():
        row["reviews"][key] = {"origin": "human", "reviewer": "test-reviewer",
            "reviewed_at": "2026-11-02T10:00:00+08:00", "candidate_sha256": candidate["sha256"],
            "prompt_sha256": ph, "facts_pass": True, "style_pass": key == "draft",
            "acceptable": key == "draft", "human_approved": True}
    row["selection"] = {"chosen": "draft", "rejected": "stiff", "source": "human", "reviewer": "test-reviewer",
        "prompt_sha256": ph, "chosen_sha256": row["candidates"]["draft"]["sha256"],
        "rejected_sha256": row["candidates"]["stiff"]["sha256"]}
    return row


class DataPreparationTests(unittest.TestCase):
    def test_actual_rating_file_is_bound_to_public_index(self):
        import os
        root = Path(os.environ.get('AM_R3_INPUT_DIR',Path(__file__).resolve().parents[1]/'data/input'))
        if not (root/'ratings.json').exists():
            self.skipTest('Private original ratings not distributed; set AM_R3_INPUT_DIR to run this check.')
        report = analyze_ratings(read_json(root / "ratings.json"),
                                 read_json(root / "pair-index.json"))
        self.assertEqual(report["entries"], 48)
        self.assertEqual(report["rated"], 47)
        self.assertEqual(report["counts"], {"B 更好": 23, "两者都不合格": 4, "A 更好": 20, "未评分": 1})
        self.assertEqual(report["public_available_pairs"], 10)
        self.assertIsNone(report["relative_preferences_with_verified_nonempty_pairs"])
        self.assertEqual(report["dpo_trainable_pairs"], 0)

    def test_text_mutation_breaks_legacy_payload_binding(self):
        rows, index, _ = fixture()
        rows[0]["a"] = "周工负责。"
        with self.assertRaises(DataError):
            verify_pairs(rows, index)

    def test_hash_uses_legacy_escape_formula_not_file_bytes(self):
        rows, index, _ = fixture()
        rows[0]["a"] = "<林工>负责。"
        expected = digest(json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c"))
        self.assertEqual(legacy_payload_sha256(rows), expected)
        self.assertNotEqual(expected, digest(json.dumps(rows, ensure_ascii=False, indent=2)))

    def test_duplicate_json_keys_and_nan_rejected(self):
        for source in ('{"ratings": {}, "ratings": {}}', '{"value": NaN}'):
            with self.assertRaises(DataError):
                strict_loads(source)

    def test_missing_case_cannot_be_silently_counted_as_rejection(self):
        rows, index, ratings = fixture()
        ratings["ratings"] = {}
        with self.assertRaises(DataError):
            analyze_ratings(ratings, index)

    def test_relative_winner_with_severe_error_is_quarantined(self):
        rows, index, ratings = fixture()
        ratings["ratings"]["SYN-QRY-01"]["severe_error_b"] = True
        report = analyze_ratings(ratings, index, rows)
        self.assertEqual(len(report["queues"]["quarantined_winner"]), 1)
        self.assertEqual(len(report["queues"]["relative_preference"]), 0)

    def test_pair_available_false_stays_untrainable_despite_preference(self):
        rows, index, ratings = fixture()
        rows[0].update(a=PLACEHOLDER, pair_available=False)
        index.update(available_pairs=0, dataset_sha256=legacy_payload_sha256(rows))
        ratings["dataset_sha256"] = index["dataset_sha256"]
        report = analyze_ratings(ratings, index, rows)
        self.assertEqual(report["relative_preferences_with_verified_nonempty_pairs"], 0)
        self.assertEqual(report["dpo_trainable_pairs"], 0)

    def test_A_B_not_automatically_model_labels(self):
        rows, index, ratings = fixture()
        report = analyze_ratings(ratings, index, rows)
        self.assertIsNone(report["queues"]["relative_preference"][0]["model_attribution"])

    def test_synthetic_drafts_export_zero(self):
        records = generate_seeds()
        result = export_training(records)
        self.assertEqual(sum(map(len, result["outputs"].values())), 0)
        self.assertTrue(all(not r["reviews"] and not r["selection"] for r in records))

    def test_projected_synthetic_uses_identical_free_runtime_prompt(self):
        from am_style.contracts import SpeechFrame, StylePolicy
        from am_style.prompt import build_messages
        records = generate_projected_seeds()
        for row in records:
            self.assertEqual(row["realization"], "free")
            self.assertEqual(row["runtime_prompt_alignment"], "aligned")
            frame = SpeechFrame.freeze(row["frame"])
            self.assertEqual(row["prompt"], build_messages(frame, StylePolicy(**row["style_policy"])))
        self.assertEqual(sum(map(len, export_training(records)["outputs"].values())), 0)

    def test_variants_share_preassigned_group_split(self):
        records = generate_seeds()
        for a, b in zip(records[::2], records[1::2]):
            self.assertEqual(a["group_id"], b["group_id"])
            self.assertEqual(a["split"], b["split"])

    def test_group_cannot_cross_splits(self):
        a, b = copy.deepcopy(generate_seeds()[:2])
        a["split"], b["split"] = "train", "dev"
        with self.assertRaises(DataError):
            assert_split_integrity([a, b])

    def test_entity_variant_cannot_hide_cross_split_duplicate(self):
        a, b = copy.deepcopy(generate_seeds()[:2])
        a["split"], b["split"] = "train", "dev"
        b["group_id"] = b["parent_group_id"] = "dishonestly-renamed-group"
        with self.assertRaises(DataError):
            assert_split_integrity([a, b])

    def test_human_bound_acceptance_exports_json_completion(self):
        row = approved_record()
        result = export_training([row])["outputs"]
        self.assertEqual(len(result["sft.train"]), 1)
        self.assertEqual(len(result["dpo.train"]), 1)
        item = result["sft.train"][0]
        self.assertEqual(set(json.loads(item["completion"][0]["content"])), {"text"})
        self.assertEqual(item["provenance"]["candidate_sha256"], digest(canonical(item["completion"])))

    def test_test_and_calibration_never_export_even_when_approved(self):
        for split in ("sealed_test", "calibration"):
            row = approved_record()
            row["split"] = split
            self.assertEqual(sum(map(len, export_training([row])["outputs"].values())), 0)

    def test_machine_judge_cannot_be_promoted_to_human(self):
        row = approved_record()
        row["reviews"]["draft"]["origin"] = "llm_judge"
        self.assertEqual(len(export_training([row])["outputs"]["sft.train"]), 0)

    def test_text_change_invalidates_human_review_even_with_fresh_candidate_hash(self):
        row = approved_record()
        row["candidates"]["draft"]["text"] = "别的答复"
        row["candidates"]["draft"]["sha256"] = digest("别的答复")
        self.assertEqual(len(export_training([row])["outputs"]["sft.train"]), 0)

    def test_prompt_change_invalidates_review(self):
        row = approved_record()
        row["prompt"][-1]["content"] = "Who owns demo B?"
        self.assertEqual(len(export_training([row])["outputs"]["sft.train"]), 0)

    def test_factually_bad_rejected_not_used_in_style_dpo(self):
        row = approved_record()
        row["reviews"]["stiff"]["facts_pass"] = False
        result = export_training([row])["outputs"]
        self.assertEqual(len(result["sft.train"]), 1)
        self.assertEqual(len(result["dpo.train"]), 0)

    def test_reprojection_clears_existing_reviews(self):
        row = approved_record()
        row = align_runtime_prompt(row, row["prompt"], "new-host/2")
        self.assertFalse(row["reviews"])
        self.assertFalse(row["selection"])
        self.assertEqual(len(row["review_history"]), 1)
        self.assertTrue(row["review_history"][0]["reviews"])
        self.assertEqual(len(export_training([row])["outputs"]["sft.train"]), 0)

    def test_unaligned_prompt_cannot_train(self):
        row = approved_record()
        row["runtime_prompt_alignment"] = "pending_host_projector"
        self.assertEqual(len(export_training([row])["outputs"]["sft.train"]), 0)

    def test_unbound_DPO_choice_does_not_gain_pair_from_approved_answers(self):
        row = approved_record()
        row["selection"]["source"] = "llm_judge"
        result = export_training([row])["outputs"]
        self.assertEqual(len(result["sft.train"]), 1)
        self.assertEqual(len(result["dpo.train"]), 0)


if __name__ == "__main__":
    unittest.main()
