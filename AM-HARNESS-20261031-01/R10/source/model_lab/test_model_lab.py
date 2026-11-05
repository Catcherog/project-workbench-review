import csv
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from model_lab.blind import FIELDS, RATINGS, export_blind, import_blind
from model_lab.core import LabError, freeze_manifest, read_json, read_jsonl, seal, validate_manifest
from model_lab.fixtures import fixture_spec
from model_lab.providers import preflight_manifest
from model_lab.quality import score_candidate
from model_lab.report import build_report, distribution, propose_selection
from model_lab.runner import run_manifest


class ModelLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = freeze_manifest(fixture_spec())

    def tearDown(self):
        self.temp.cleanup()

    def run_fixture(self, spec=None):
        m = freeze_manifest(spec) if spec is not None else self.manifest
        report = run_manifest(m, self.root / "run")
        return m, read_jsonl(self.root / "run/results.jsonl"), report

    def test_manifest_freezes_denominator_and_detects_fact_change(self):
        self.assertEqual(self.manifest["expected_results"], 15)
        self.assertEqual(validate_manifest(self.manifest), self.manifest)
        changed = deepcopy(self.manifest)
        changed["cases"][0]["facts"][0]["text"] = "changed"
        with self.assertRaises(LabError): validate_manifest(changed)
        with self.assertRaises(LabError): validate_manifest(seal(changed))

    def test_authorized_redacted_material_not_mislabeled_synthetic(self):
        spec = fixture_spec(); spec["data_classification"] = "authorized_redacted"
        with self.assertRaises(LabError): freeze_manifest(spec)

    def test_fixture_runs_all_arms_without_real_provider(self):
        with patch("model_lab.providers.subprocess.Popen", side_effect=AssertionError("real call forbidden")):
            m, records, report = self.run_fixture()
        self.assertEqual(len(records), 15)
        self.assertEqual(report["result_scope"], "fixture_only_no_real_score")
        self.assertEqual(report["real_model_attempt_records"], 0)
        self.assertTrue(report["data_complete"])
        self.assertEqual(set(report["phases"]), {"module", "end_to_end"})
        self.assertTrue(all(r["quality"]["schema"] == "pass" for r in records))
        self.assertTrue(all(not r["model_attempted"] for r in records))
        self.assertEqual(len(next(r for r in records if r["arm"] == "qwen_then_codex")["stages"]), 2)

    def test_real_missing_pins_are_blocked_without_model_call(self):
        spec = fixture_spec(); spec["mode"] = "real"
        for c in spec["cases"]: c["split"] = "regression"
        manifest = freeze_manifest(spec)
        with patch("model_lab.providers.subprocess.Popen", side_effect=AssertionError("no runtime permitted")):
            pf = preflight_manifest(manifest)
            report = run_manifest(manifest, self.root / "blocked", execute=True)
        self.assertTrue(all(v["status"] == "blocked" for v in pf["arms"].values()))
        records = read_jsonl(self.root / "blocked/results.jsonl")
        self.assertEqual(len(records), 15)
        self.assertTrue(all(r["status"] == "blocked" for r in records))
        self.assertEqual(report["real_model_attempt_records"], 0)
        self.assertIsNone(report["winner"])

    def test_run_directory_cannot_be_resumed_or_overwritten(self):
        self.run_fixture()
        with self.assertRaises(LabError): run_manifest(self.manifest, self.root / "run")

    def test_stop_unknown_preserved_and_halts_subsequent_arms(self):
        spec = fixture_spec()
        spec["cases"][0]["fixture_outputs"]["codex"] = {"status": "stop_unknown", "error": "remote_not_confirmed"}
        m, rows, report = self.run_fixture(spec)
        first = next(i for i,r in enumerate(rows) if r["status"] == "stop_unknown")
        # Already-returned fixture batch rows may coexist, but every later batch stops.
        subsequent = [r for r in rows[first+1:] if r["arm"] != "codex"]
        self.assertTrue(subsequent and all(r["status"] == "not_run" for r in subsequent))
        self.assertTrue(report["halted_on_unknown"])
        self.assertEqual(report["planned"], 15)
        self.assertFalse(report["data_complete"])

    def test_cascade_guard_pass_skips_second_call(self):
        spec = fixture_spec(); spec["arms"]["qwen_then_codex"]["route"]["policy"] = "on_guard_failure"
        m, rows, _ = self.run_fixture(spec)
        cascades = [r for r in rows if r["arm"] == "qwen_then_codex"]
        self.assertTrue(all(len(r["stages"]) == 1 and r["route_decision"] == "guard_pass_keep_qwen" for r in cascades))

    def test_failure_is_counted_in_planned_not_only_success_denominator(self):
        spec = fixture_spec(); spec["cases"][0]["fixture_outputs"]["mlx_base"]["status"] = "provider_failed"
        m, rows, report = self.run_fixture(spec)
        metric = report["phases"]["module"]["mlx_base"]["completed_rate"]
        self.assertEqual(metric, {"numerator": 1, "denominator": 2, "value": .5})
        partial = build_report(m, rows[:-1])
        self.assertEqual(partial["missing"], 1)
        self.assertEqual(partial["planned"], 15)

    def test_raw_capture_tampering_fails_report(self):
        m, rows, _ = self.run_fixture()
        Path(rows[0]["raw"][0]["path"]).write_text("tampered")
        with self.assertRaises(LabError): build_report(m, rows)

    def test_no_zeros_for_unobserved_costs_tokens_or_resources(self):
        m, rows, report = self.run_fixture()
        value = report["phases"]["module"]["q8"]
        self.assertIsNone(value["cost"]["total"])
        self.assertIsNone(value["tokens"]["input"]["sum"])
        self.assertIsNone(value["resources"]["peak_rss_mib"]["mean"])
        self.assertTrue(distribution([1, 2, 3])["p95_small_sample"])
        self.assertIsNone(distribution([])["p95"])

    def test_blind_empty_export_does_not_invent_human_scores(self):
        m, rows, _ = self.run_fixture()
        exported = export_blind(m, rows, self.root / "blind")
        packet, mapping = read_json(exported["packet"]), read_json(exported["private_mapping"])
        imported = import_blind(m, packet, mapping, exported["ratings"])
        self.assertEqual(imported["human_ratings"], 0)
        self.assertEqual(imported["unfilled_rows"], 15)
        self.assertFalse(any("arm" in c for c in packet["candidates"]))

    def test_human_import_binds_packet_and_prevents_duplicate_scores(self):
        m, rows, _ = self.run_fixture()
        exported = export_blind(m, rows, self.root / "blind")
        packet, mapping = read_json(exported["packet"]), read_json(exported["private_mapping"])
        with Path(exported["ratings"]).open(encoding="utf-8-sig", newline="") as f:
            ratings = list(csv.DictReader(f))
        ratings[0].update(reviewer_id="human-reviewer-1", rater_type="human", **{k: "4" for k in RATINGS})
        filled = self.root / "filled.csv"
        def save(values):
            with filled.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS); writer.writeheader(); writer.writerows(values)
        save(ratings)
        imported = import_blind(m, packet, mapping, filled)
        self.assertEqual(imported["human_ratings"], 1)
        self.assertEqual(build_report(m, rows, imported)["human_reviewed_slots"], 1)
        save(ratings + [ratings[0]])
        with self.assertRaises(LabError): import_blind(m, packet, mapping, filled)
        ratings[0]["packet_sha256"] = "0"*64; save(ratings)
        with self.assertRaises(LabError): import_blind(m, packet, mapping, filled)

    def test_quality_keeps_unknown_original_fact_guard(self):
        case = self.manifest["cases"][0]
        from model_lab.core import canonical
        output = canonical(case["fixture_outputs"]["q8"]["output"])
        quality = score_candidate(case, output, inherited_guard={"decision": "indeterminate"})
        self.assertEqual(quality["fact_guard"], "indeterminate")
        bad = score_candidate(case, "not json")
        self.assertIn("schema_invalid", bad["errors"])

    def test_selection_is_report_bound_proposal_never_activation(self):
        m, rows, report = self.run_fixture()
        chosen = propose_selection(m, report, "qwen_then_codex", "review this route")
        self.assertFalse(chosen["production_activation"])
        self.assertEqual(chosen["writes_to_production"], 0)
        self.assertIn("fixture_evidence_cannot_choose_real_winner", chosen["blockers"])
        bad = deepcopy(report); bad["manifest_sha256"] = "0"*64
        with self.assertRaises(LabError): propose_selection(m, seal(bad), "q8", "test")

    def test_json_schemas_accept_frozen_outputs(self):
        import jsonschema
        m, rows, report = self.run_fixture()
        root = Path(__file__).parent/"schemas"
        proposal = propose_selection(m, report, "q8", "fixture schema check")
        for name, objects in (("manifest", [m]), ("result", rows), ("report", [report]), ("selection", [proposal])):
            validator = jsonschema.Draft202012Validator(read_json(root/(name+".schema.json")))
            for obj in objects: validator.validate(obj)
        self.assertIn("每个计划槽位", (self.root/"run/report.md").read_text())

    def test_human_pairs_require_same_case_repeat_and_common_reviewer(self):
        m, rows, _ = self.run_fixture()
        ratings = []
        for row in rows:
            if row["case_id"] == "FACT-001" and row["arm"] in {"q8", "codex"}:
                ratings.append({"slot_id": row["slot_id"], "record_sha256": row["sha256"],
                    "reviewer_id": "protocol-fixture-common-reviewer", "rater_type": "human",
                    **{k: (5 if row["arm"] == "q8" else 3) for k in RATINGS}})
        reviews = seal({"schema": "am-model-lab-human-reviews/1", "manifest_sha256": m["sha256"], "ratings": ratings})
        report = build_report(m, rows, reviews)
        pair = next(p for p in report["paired_comparisons"] if p["phase"] == "module" and p["left"] == "q8" and p["right"] == "codex")
        self.assertEqual(pair["human_paired"]["same_case_repeat_reviewer_pairs"], 1)
        self.assertEqual(pair["human_paired"]["by_dimension"]["usefulness"]["left_wins"], 1)
        ratings[-1]["reviewer_id"] = "different-fixture-reviewer"
        report = build_report(m, rows, seal({**reviews, "ratings": ratings}))
        pair = next(p for p in report["paired_comparisons"] if p["phase"] == "module" and p["left"] == "q8" and p["right"] == "codex")
        self.assertEqual(pair["human_paired"]["same_case_repeat_reviewer_pairs"], 0)
        self.assertIn("unknown", pair["human_paired"]["status"])


if __name__ == "__main__":
    unittest.main()
