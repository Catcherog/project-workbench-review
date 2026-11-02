"""Exercise the offline CLI file chain; never start any real model/provider."""
from pathlib import Path
import json
import stat
import subprocess
import sys
import tempfile
import unittest

from am_style_r5.common import canonical, read_json, write_json
from am_style_r5.evaluation import freeze_cases


class EvaluationCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = Path(__file__).resolve().parents[1]
        cls.scratch = tempfile.TemporaryDirectory()
        cls.root = Path(cls.scratch.name)
        cls.demo_dir = cls.root / "demo"
        result = cls.invoke("demo", "--output", cls.demo_dir)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.demo_summary = json.loads(result.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    @classmethod
    def invoke(cls, *arguments):
        return subprocess.run([sys.executable, "run.py", *map(str, arguments)], cwd=cls.package,
                              text=True, capture_output=True, timeout=30, check=False)

    def test_demo_preserves_missing_denominator_and_zero_real_effects(self):
        self.assertEqual(self.demo_summary["planned_results"], 9)
        self.assertEqual(self.demo_summary["recorded_results"], 8)
        self.assertEqual(self.demo_summary["missing_results"], 1)
        self.assertEqual(self.demo_summary["actual_model_calls"], 0)
        self.assertEqual(self.demo_summary["human_approvals"], 0)
        self.assertFalse(self.demo_summary["training_executed"])
        report = read_json(self.demo_dir / "report.json")
        self.assertEqual(report["mode"], "fixture")
        self.assertEqual(report["sample_status"], "not_independent")
        self.assertEqual(report["arms"]["production_q8"]["statuses"]["missing"], 1)
        self.assertTrue(all(v["human_usable_cases"] == 0 for v in report["arms"].values()))
        self.assertFalse(report["production_enabled"])

    def test_public_review_includes_question_without_arm_mapping(self):
        public = read_json(self.demo_dir / "blind-public.json")
        markdown = (self.demo_dir / "blind-review.md").read_text()
        combined = canonical(public) + markdown
        self.assertTrue(all(arm not in combined for arm in ("production_q8", "mlx_base", "mlx_sft")))
        self.assertTrue(all(task["question"] and task["question"] in markdown for task in public["tasks"]))
        private_mode = stat.S_IMODE((self.demo_dir / "blind-private.json").stat().st_mode)
        self.assertEqual(private_mode, 0o600)
        pending = read_json(self.demo_dir / "blind-feedback.pending.json")
        self.assertEqual(pending["ratings"], [])
        self.assertEqual(pending["preferences"], [])
        self.assertFalse(pending["human_authored"])
        self.assertTrue(pending["pending_preference_items"])
        self.assertTrue(all(p["outcome"] is None for p in pending["pending_preference_items"]))

    def test_complete_eval_plan_import_blind_report_command_chain(self):
        old = read_json(self.demo_dir / "plan.json")
        frozen_path, arms_path = self.root / "frozen-cases.json", self.root / "arms.json"
        write_json(frozen_path, freeze_cases(old["cases"]))
        write_json(arms_path, old["arms"])
        plan_path = self.root / "eval-plan.json"
        planned = self.invoke("eval-plan", "--cases", frozen_path, "--arms", arms_path, "--mode", "fixture", "--output", plan_path)
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual(read_json(plan_path), old)
        results_path = self.root / "imported.json"
        imported = self.invoke("eval-import", "--plan", plan_path, "--records", self.demo_dir / "fixture-records.jsonl", "--output", results_path)
        self.assertEqual(imported.returncode, 0, imported.stderr)
        blind_dir = self.root / "blind-chain"
        blind = self.invoke("blind", "--plan", plan_path, "--results", results_path, "--output", blind_dir)
        self.assertEqual(blind.returncode, 0, blind.stderr)
        report_dir = self.root / "report-chain"
        result = self.invoke("report", "--plan", plan_path, "--results", results_path,
                             "--public", blind_dir / "blind-public.json", "--private", blind_dir / "blind-private.json",
                             "--output", report_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = read_json(report_dir / "report.json")
        markdown = (report_dir / "report.md").read_text()
        self.assertEqual(report["planned_results"], 9)
        self.assertIn("missing: 1", markdown)
        self.assertIn("尝试 p50 / p95 / max", markdown)

    def test_pending_form_does_not_silently_become_approval(self):
        result = self.invoke("report", "--plan", self.demo_dir / "plan.json", "--results", self.demo_dir / "results.json",
                             "--public", self.demo_dir / "blind-public.json", "--private", self.demo_dir / "blind-private.json",
                             "--feedback", self.demo_dir / "blind-feedback.pending.json", "--output", self.root / "pending-report")
        self.assertEqual(result.returncode, 2)
        self.assertIn("reviewer", result.stderr)
        self.assertFalse((self.root / "pending-report").exists())

    def test_only_one_blind_binding_file_rejected(self):
        result = self.invoke("report", "--plan", self.demo_dir / "plan.json", "--results", self.demo_dir / "results.json",
                             "--public", self.demo_dir / "blind-public.json", "--output", self.root / "broken-report")
        self.assertEqual(result.returncode, 2)
        self.assertIn("both public", result.stderr)

    def test_demo_refuses_overwrite_of_existing_evidence(self):
        before = (self.demo_dir / "plan.json").read_bytes()
        result = self.invoke("demo", "--output", self.demo_dir)
        self.assertEqual(result.returncode, 2)
        self.assertEqual((self.demo_dir / "plan.json").read_bytes(), before)

    def test_real_sealed_plan_cannot_skip_snapshot_or_human_declaration(self):
        old = read_json(self.demo_dir / "plan.json")
        cases = old["cases"]
        for case in cases:
            case.update(split="sealed_test", public_exposed=False, independent_test_eligible=True)
        cases_path, arms_path = self.root / "unapproved-sealed.json", self.root / "unapproved-arms.json"
        write_json(cases_path, freeze_cases(cases))
        write_json(arms_path, old["arms"])
        result = self.invoke("eval-plan", "--cases", cases_path, "--arms", arms_path,
                             "--mode", "real", "--output", self.root / "unsafe-plan.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("exclusion snapshot", result.stderr)
        self.assertFalse((self.root / "unsafe-plan.json").exists())


if __name__ == "__main__":
    unittest.main()
