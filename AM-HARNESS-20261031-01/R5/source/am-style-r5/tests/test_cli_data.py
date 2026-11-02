"""Exercise the shipped portable CLI without any model or training execution."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "run.py"


def call(*arguments, cwd):
    return subprocess.run([sys.executable, str(ENTRY), *map(str, arguments)],
                          cwd=cwd, capture_output=True, text=True, timeout=30)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class CliDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="r5-cli-data-tests-")
        cls.home = Path(cls.workspace.name)
        cls.prepared = cls.home / "prepared"
        result = call("prepare", "--output", cls.prepared, cwd=cls.home)
        if result.returncode:
            cls.workspace.cleanup()
            raise AssertionError(result.stderr)
        cls.preparation_stdout = json.loads(result.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="case-", dir=self.home)
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_prepare_runs_outside_repository_and_produces_only_twenty_two_pending_proposals(self):
        summary = self.preparation_stdout
        self.assertEqual(summary["new_proposals"], 22)
        self.assertEqual(summary["new_train_proposals"], 15)
        self.assertEqual(summary["new_dev_proposals"], 7)
        self.assertEqual(summary["new_human_approvals"], 0)
        self.assertEqual(summary["actual_model_calls"], 0)
        self.assertFalse(summary["training_executed"])
        self.assertFalse(summary["production_changed"])
        self.assertFalse(summary["pilot_ready"])
        self.assertEqual(summary["current_gold"], {"train": 9, "dev": 1, "train_groups": 9, "dev_groups": 1})
        batch = read(self.prepared / "review-batch.json")
        feedback = read(self.prepared / "feedback.pending.json")
        self.assertEqual(len(batch["cases"]), 22)
        self.assertEqual(len(feedback["ratings"]), 22)
        self.assertEqual(feedback["origin"], "pending")
        self.assertIsNone(feedback["reviewer"])
        for rating in feedback["ratings"]:
            self.assertEqual(rating["status"], "pending")
            self.assertIsNone(rating["accepted_candidate"])
            self.assertTrue(all(a[f] is None for a in rating["assessments"].values()
                                for f in ("facts_pass", "style_pass", "acceptable")))
        for split in ("train", "dev"):
            old = ROOT / "baseline/data/r4-gold" / f"sft.{split}.jsonl"
            current = self.prepared / "current-gold" / f"sft.{split}.jsonl"
            self.assertEqual(old.read_bytes(), current.read_bytes())
        self.assertEqual((self.prepared / "review.md").read_text().count("## "), 22)

    def test_pending_import_snapshot_and_relocated_readback_preserve_nine_and_one(self):
        feedback = self.root / "feedback.json"
        shutil.copyfile(self.prepared / "feedback.pending.json", feedback)
        imported = self.root / "import.json"
        result = call("import-feedback", "--batch", self.prepared / "review-batch.json",
                      "--feedback", feedback, "--output", imported, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        exports = read(imported)["r4_import"]["exports"]["outputs"]
        self.assertTrue(all(not rows for rows in exports.values()))
        original = self.root / "original-snapshot"
        result = call("snapshot", "--registry", self.prepared / "group-registry.json",
                      "--imports", imported, "--output", original, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        feedback.unlink()
        imported.unlink()
        moved = self.root / "moved" / "snapshot"
        moved.parent.mkdir()
        original.rename(moved)
        result = call("verify-snapshot", "--snapshot", moved / "snapshot.json", cwd=self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = read(moved / "snapshot.json")
        self.assertEqual(snapshot["counts"], {"train": 9, "dev": 1, "train_groups": 9, "dev_groups": 1})
        self.assertEqual(snapshot["sealed_test"]["exported_rows"], 0)
        self.assertFalse(original.exists())

    def test_revise_mapping_creates_a_new_pending_batch_and_invalidates_old_feedback(self):
        old = read(self.prepared / "review-batch.json")
        ident = old["cases"][0]["id"]
        replacement = {ident: "这是需要重新评审的完整改稿，尚未取得人工认可。"}
        source = self.root / "replacements.json"
        source.write_text(json.dumps(replacement, ensure_ascii=False), encoding="utf-8")
        revised = self.root / "revised"
        result = call("revise", "--batch", self.prepared / "review-batch.json",
                      "--replacements", source, "--version", "R5-cli-revision-2",
                      "--output", revised, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = read(revised / "review-batch.json")
        self.assertNotEqual(actual["batch_sha256"], old["batch_sha256"])
        self.assertEqual(actual["parent_batch_sha256"], old["batch_sha256"])
        self.assertEqual(actual["cases"][0]["candidates"]["proposed_revision"]["text"], replacement[ident])
        pending = read(revised / "feedback.pending.json")
        self.assertTrue(all(r["status"] == "pending" for r in pending["ratings"]))
        self.assertEqual(read(self.prepared / "review-batch.json"), old)
        blocked_output = self.root / "invalid-old-feedback.json"
        result = call("import-feedback", "--batch", revised / "review-batch.json",
                      "--feedback", self.prepared / "feedback.pending.json",
                      "--output", blocked_output, cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("belongs to another batch", result.stderr)
        self.assertFalse(blocked_output.exists())

    def test_wrong_revise_json_shape_is_a_clear_block_without_traceback_or_outputs(self):
        ident = read(self.prepared / "review-batch.json")["cases"][0]["id"]
        for index, data in enumerate(([ident], {ident: {"text": "nested is invalid"}})):
            with self.subTest(data=data):
                source = self.root / f"wrong-{index}.json"
                source.write_text(json.dumps(data), encoding="utf-8")
                destination = self.root / f"wrong-{index}"
                result = call("revise", "--batch", self.prepared / "review-batch.json",
                              "--replacements", source, "--version", "R5-cli-invalid",
                              "--output", destination, cwd=self.root)
                self.assertEqual(result.returncode, 2)
                self.assertIn("JSON object mapping case IDs", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(destination.exists())

    def test_existing_output_is_not_overwritten_and_stale_text_hash_is_not_imported(self):
        existing = self.root / "existing"
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_text("retain user-owned contents", encoding="utf-8")
        result = call("prepare", "--output", existing, cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(marker.read_text(), "retain user-owned contents")
        feedback = deepcopy(read(self.prepared / "feedback.pending.json"))
        feedback["ratings"][0]["assessments"]["proposed_revision"]["candidate_sha256"] = "0" * 64
        path = self.root / "stale-feedback.json"
        path.write_text(json.dumps(feedback), encoding="utf-8")
        output = self.root / "stale-import.json"
        result = call("import-feedback", "--batch", self.prepared / "review-batch.json",
                      "--feedback", path, "--output", output, cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("assessment text hash differs", result.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
