"""Feedback marked fixture-only in tests; no actual human labels are created."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from am_style.data import DataError, digest
from am_style.review import build_review_batch, feedback_template, import_feedback
from training.common import validate_rows

ROOT = Path(__file__).resolve().parents[1]


def batch_fixture():
    root = ROOT / "data/r3"
    names = ("frozen-comparison.json", "comparison.json", "sft.train.jsonl", "sft.dev.jsonl")
    files = {n: {"sha256": digest((root/n).read_bytes()), "relative_path": "data/r3/"+n} for n in names}
    gold = [json.loads((root/n).read_text()) for n in names[2:]]
    return build_review_batch(json.loads((root/names[0]).read_text()), json.loads((root/names[1]).read_text()),
                              gold, source_files=files)


def simulated_feedback(batch):
    feedback = feedback_template(batch)
    feedback.update(origin="human", reviewer="fixture-only-not-an-actual-human-label", reviewed_at="2026-11-02T00:00:00+00:00")
    row = feedback["ratings"][0]
    row.update(status="reviewed", accepted_candidate="qwen_r3")
    for assessment in row["assessments"].values():
        assessment.update(facts_pass=True, style_pass=True, acceptable=True)
    return feedback


class ReviewTests(unittest.TestCase):
    def test_cli_never_overwrites_existing_build_or_import_directory(self):
        script = str(ROOT / "scripts/review_batch.py")
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "already-reviewed"
            destination.mkdir()
            marker = destination / "keep.txt"
            marker.write_bytes(b"existing human-reviewed export must stay intact")
            commands = [
                ["build", "--input-dir", str(ROOT / "data/r3")],
                ["import", "--batch", str(ROOT / "data/r4-review/batch.json"),
                 "--feedback", str(ROOT / "data/r4-review/feedback.pending.json")],
            ]
            for args in commands:
                result = subprocess.run([sys.executable, script, *args, "--out-dir", str(destination)],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("already exists", result.stderr)
                self.assertEqual(marker.read_bytes(), b"existing human-reviewed export must stay intact")
                self.assertEqual(list(destination.iterdir()), [marker])
            not_created = Path(temp) / "invalid-input-must-not-create-output"
            bad = subprocess.run([sys.executable, script, "import", "--batch", str(ROOT / "data/r4-review/batch.json"),
                "--feedback", str(Path(temp) / "missing-feedback.json"), "--out-dir", str(not_created)],
                capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse(not_created.exists())

    def test_batch_excludes_old_approvals_and_host_defects_defaults_zero(self):
        batch = batch_fixture()
        self.assertEqual(len(batch["cases"]), 8)
        self.assertEqual(len({r["group_id"] for r in batch["cases"]}), 8)
        self.assertEqual(len(batch["already_reviewed"]), 2)
        self.assertEqual(len(batch["host_repair"]), 2)
        self.assertEqual({r["split"] for r in batch["cases"]}, {"train"})
        result = import_feedback(batch, feedback_template(batch))
        self.assertEqual(sum(map(len, result["exports"]["outputs"].values())), 0)
        self.assertEqual(len(result["pending_ids"]), 8)
        self.assertTrue(all(r["reviews"] == {} for r in result["records"]))

    def test_import_absolute_acceptance_and_optional_style_pair_bind_actual_wire(self):
        batch = batch_fixture()
        feedback = simulated_feedback(batch)
        feedback["ratings"][0]["preference"] = {"chosen": "qwen_r3", "rejected": "proposed_revision"}
        result = import_feedback(batch, feedback)
        outputs = result["exports"]["outputs"]
        self.assertEqual(len(outputs["sft.train"]), 1)
        self.assertEqual(len(outputs["dpo.train"]), 1)
        validate_rows(outputs["sft.train"], split="train", mode="sft")
        validate_rows(outputs["dpo.train"], split="train", mode="dpo")
        self.assertEqual(outputs["sft.train"][0]["prompt"], batch["cases"][0]["prompt"])
        self.assertEqual(batch["cases"][0]["reviews"], {})

    def test_relative_preference_or_assistant_rating_is_not_human_gold(self):
        batch = batch_fixture()
        feedback = simulated_feedback(batch)
        feedback["ratings"][0]["assessments"]["qwen_r3"]["acceptable"] = None
        with self.assertRaisesRegex(DataError, "absolute acceptance"):
            import_feedback(batch, feedback)
        feedback = simulated_feedback(batch)
        feedback["origin"] = "assistant"
        with self.assertRaisesRegex(DataError, "human origin"):
            import_feedback(batch, feedback)

    def test_feedback_cannot_cross_batch_context_or_text(self):
        batch = batch_fixture()
        for path in ("batch", "context", "candidate"):
            feedback = simulated_feedback(batch)
            if path == "batch":
                feedback["batch_sha256"] = "0" * 64
            elif path == "context":
                feedback["ratings"][0]["review_context_sha256"] = "0" * 64
            else:
                feedback["ratings"][0]["assessments"]["qwen_r3"]["candidate_sha256"] = "0" * 64
            with self.assertRaises(DataError):
                import_feedback(batch, feedback)

    def test_both_bad_is_a_repair_request_not_an_implicit_rejected_label(self):
        batch = batch_fixture()
        feedback = simulated_feedback(batch)
        row = feedback["ratings"][0]
        row.update(status="both_bad", accepted_candidate=None, preference=None)
        for assessment in row["assessments"].values():
            assessment.update(style_pass=False, acceptable=False)
        result = import_feedback(batch, feedback)
        self.assertEqual(len(result["repair_queue"]), 1)
        self.assertEqual(sum(map(len, result["exports"]["outputs"].values())), 0)


if __name__ == "__main__":
    unittest.main()
