"""Synthetic development tests, not independent holdout or business acceptance."""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "am-style-r5" / "src"))
sys.path.insert(0, str(ROOT.parent / "am-conversation-r1" / "src"))

from am_acceptance.diagnostics import (
    DiagnosticError, SCHEMA, adapt_native_r5, adapt_r8_public,
    diagnose, main, render_markdown,
)


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture():
    identity = {"base_revision": "a" * 40, "tokenizer_sha256": h("tokenizer"),
                "model_manifest_sha256": h("model"),
                "generation_settings": {"temperature": 0.0, "seed": 221, "max_tokens": 192}}
    arms = {"production_q8": {"generation_settings": {"max_tokens": 650}},
            "mlx_base": {**identity, "adapter_sha256": None},
            "mlx_sft": {**identity, "adapter_sha256": h("adapter")}}
    rows = []
    for case in range(1, 5):
        for arm in arms:
            missing = case == 1 and arm == "production_q8"
            rows.append({
                "case_id": str(case), "arm": arm,
                "status": "stop_unknown" if missing else "completed",
                "record_sha256": h(f"record:{case}:{arm}"),
                "output_sha256": None if missing else h(f"q8:{case}" if arm == "production_q8" else f"mlx:{case}"),
                "input_sha256": h(f"input:{case}"),
                "schema_pass": not missing, "artifact_bindings_verified": not missing,
                "runner_source_sha256": h("runner"), "safety": {"decision": "indeterminate"},
                **arms[arm],
            })
    pilot = {
        "optimizer_steps": 6, "actual_train_samples": 24,
        "result_status": "completed", "adapter_sha256": h("adapter"),
        "final_parameter_delta": {"all_finite": True, "changed_tensors": 18, "l2_norm": 0.15},
        "phases": [{"phase": phase, "attempted": True, "status": "completed", "pid": pid,
                    "exit_code": 0, "timed_out": False, "stop_confirmed": True}
                   for phase, pid in (("fit", 100), ("reload", 101))],
        "adapter_tensor_roundtrip_verified": True, "adapter_complete_keyset_verified": True,
        "fresh_load_verified": True, "adapter_tensor_equality_verified": True,
        "reload_diagnostics_max_abs_delta": 0.0,
    }
    return {"schema": SCHEMA, "evidence_scope": "synthetic_development_fixture_not_holdout",
            "plan": {"case_ids": [str(i) for i in range(1, 5)], "arms": arms,
                     "plan_sha256": h("plan"), "case_manifest_sha256": h("manifest")},
            "records": rows, "pilot": pilot, "reviews": []}


def public_fixture(bundle):
    plan = {"planned_cases": 4, "planned_arms": 3, "planned_positions": 12,
            "arms": deepcopy(bundle["plan"]["arms"]),
            "plan_seal_sha256": bundle["plan"]["plan_sha256"],
            "case_manifest_sha256": bundle["plan"]["case_manifest_sha256"]}
    rows = []
    for row in bundle["records"]:
        rows.append({"scene": int(row["case_id"]), **{
            key: row[key] for key in ("arm", "status", "record_sha256", "output_sha256",
                                     "schema_pass", "artifact_bindings_verified", "safety", "runner_source_sha256")}})
    return plan, {"planned": 12, "recorded": 12, "missing": 0, "rows": rows}


def review(bundle, kind="gpt_proxy", case="2", arm="mlx_sft", **changes):
    row = next(r for r in bundle["records"] if (r["case_id"], r["arm"]) == (case, arm))
    return {"review_id": "review-1", "case_id": case, "arm": arm,
            "candidate_output_sha256": row["output_sha256"], "kind": kind,
            "human_authored": kind == "human", "reviewer_id": "reviewer-a",
            "authorization_ref": "user-authorized-GPT-proxy-review", "assessment": "adopt", **changes}


class DenominatorAndPairingTests(unittest.TestCase):
    def test_r8_shaped_fixture_preserves_twelve_positions_and_seven_distinct_texts(self):
        data = fixture()
        before = deepcopy(data)
        report = diagnose(data)
        self.assertEqual(report["counts"], {
            "planned_cases": 4, "planned_positions": 12, "provided_records": 12,
            "missing_records": 0, "completed_outputs": 11,
            "distinct_completed_texts": 7, "unscored_no_output_positions": 1})
        self.assertEqual(report["comparison"]["verified_comparable_pairs"], 4)
        self.assertEqual(report["comparison"]["identical_verified_pairs"], 4)
        self.assertEqual(report["arms"]["production_q8"]["fact_guard_states"],
                         {"not_run": 1, "indeterminate": 3})
        self.assertFalse(report["comparison"]["q8_used_as_causal_training_control"])
        self.assertEqual(data, before)

    def test_missing_record_is_kept_in_denominator_without_score(self):
        data = fixture()
        data["records"] = data["records"][:-1]
        report = diagnose(data)
        self.assertEqual(report["counts"]["planned_positions"], 12)
        self.assertEqual(report["counts"]["missing_records"], 1)
        self.assertEqual(report["comparison"]["verified_comparable_pairs"], 3)

    def test_missing_entire_scene_does_not_shrink_planned_cases(self):
        data = fixture()
        data["records"] = [r for r in data["records"] if r["case_id"] != "4"]
        self.assertEqual(diagnose(data)["counts"]["missing_records"], 3)
        self.assertEqual(diagnose(data)["counts"]["planned_positions"], 12)

    def test_each_execution_binding_must_match(self):
        variants = {"input_sha256": h("different-input"), "base_revision": "b" * 40,
                    "tokenizer_sha256": h("different-tokenizer"),
                    "generation_settings": {"temperature": 1.0},
                    "runner_source_sha256": h("different-runner"),
                    "model_manifest_sha256": h("different-model"), "adapter_sha256": h("wrong-adapter")}
        for key, value in variants.items():
            with self.subTest(binding=key):
                data = fixture()
                data["records"][2][key] = value
                self.assertEqual(diagnose(data)["comparison"]["verified_comparable_pairs"], 3)

    def test_both_arms_drifting_together_still_must_match_plan(self):
        data = fixture()
        for row in data["records"][1:3]:
            row["tokenizer_sha256"] = h("same-but-unplanned-tokenizer")
        self.assertFalse(diagnose(data)["mlx_pairs"][0]["comparable"])

    def test_missing_bindings_cannot_be_filled_from_matching_scene_ids(self):
        data = fixture()
        del data["records"][2]["input_sha256"]
        result = diagnose(data)["mlx_pairs"][0]
        self.assertFalse(result["comparable"])
        self.assertTrue(result["output_hashes_equal"])
        self.assertIn("input_sha256:missing", result["reasons"])

    def test_unverified_artifacts_and_invalid_schema_are_not_comparable(self):
        for field in ("artifact_bindings_verified", "schema_pass"):
            with self.subTest(field=field):
                data = fixture()
                data["records"][2][field] = False
                self.assertFalse(diagnose(data)["mlx_pairs"][0]["comparable"])

    def test_base_with_adapter_is_not_a_base_control(self):
        data = fixture()
        data["records"][1]["adapter_sha256"] = h("adapter")
        self.assertIn("mlx_base:unexpected_adapter", diagnose(data)["mlx_pairs"][0]["reasons"])

    def test_mutable_revision_label_is_rejected(self):
        data = fixture()
        for arm in ("mlx_base", "mlx_sft"):
            data["plan"]["arms"][arm]["base_revision"] = "main"
        for row in data["records"]:
            if row["arm"] != "production_q8":
                row["base_revision"] = "main"
        with self.assertRaises(DiagnosticError):
            diagnose(data)

    def test_changed_output_is_not_automatically_an_improvement(self):
        data = fixture()
        data["records"][2]["output_sha256"] = h("changed-writing")
        report = diagnose(data)
        self.assertEqual(report["comparison"]["changed_verified_pairs"], 1)
        self.assertEqual(report["comparison"]["naturalness_improvement"], "not_established_by_this_diagnostic")

    def test_fallback_or_truncation_cannot_masquerade_as_generated_success(self):
        for flag in ("fallback_used", "truncated"):
            with self.subTest(flag=flag):
                data = fixture()
                data["records"][2][flag] = True
                self.assertEqual(diagnose(data)["counts"]["completed_outputs"], 10)

    def test_duplicate_unplanned_and_inconsistent_output_are_rejected(self):
        for mutation in ("duplicate", "unplanned", "hash"):
            with self.subTest(mutation=mutation):
                data = fixture()
                if mutation == "duplicate":
                    data["records"][2] = deepcopy(data["records"][1])
                elif mutation == "unplanned":
                    data["records"][2]["case_id"] = "99"
                else:
                    data["records"][2]["output_text"] = "not the hashed output"
                with self.assertRaises(DiagnosticError):
                    diagnose(data)

    def test_absent_original_preserves_original_blocked_status(self):
        data = fixture()
        data["records"][0] = {"case_id": "1", "arm": "production_q8", "status": "blocked",
                              "record_present": False, "output_sha256": None}
        report = diagnose(data)
        self.assertEqual(report["counts"]["provided_records"], 11)
        self.assertEqual(report["arms"]["production_q8"]["raw_statuses"], {"blocked": 1, "completed": 3})

    def test_output_body_is_never_copied_to_report(self):
        data = fixture()
        data["records"][2]["output_text"] = "PRIVATE-CANDIDATE-BODY"
        data["records"][2]["output_sha256"] = h("PRIVATE-CANDIDATE-BODY")
        self.assertNotIn("PRIVATE-CANDIDATE-BODY", json.dumps(diagnose(data)))


class ReviewAndMechanicsTests(unittest.TestCase):
    def test_proxy_and_human_ratings_are_separate_and_do_not_override_guard(self):
        data = fixture()
        data["reviews"] = [review(data), review(data, "human", review_id="human-1")]
        report = diagnose(data)
        self.assertEqual(report["reviews"]["gpt_proxy"]["rating_count"], 1)
        self.assertEqual(report["reviews"]["human"]["rating_count"], 1)
        self.assertEqual(report["arms"]["mlx_sft"]["fact_guard_states"], {"indeterminate": 4})
        self.assertFalse(report["reviews"]["machine_guard_overridden_by_review"])

    def test_proxy_label_cannot_be_changed_to_human_authored(self):
        data = fixture()
        data["reviews"] = [review(data, human_authored=True)]
        with self.assertRaises(DiagnosticError):
            diagnose(data)

    def test_proxy_needs_explicit_authorization_reference(self):
        data = fixture()
        data["reviews"] = [review(data, authorization_ref="")]
        with self.assertRaises(DiagnosticError):
            diagnose(data)

    def test_missing_output_has_no_quality_score(self):
        data = fixture()
        data["reviews"] = [review(data, case="1", arm="production_q8")]
        with self.assertRaises(DiagnosticError):
            diagnose(data)

    def test_explicit_unscored_marker_is_not_a_rating(self):
        data = fixture()
        data["reviews"] = [review(data, case="1", arm="production_q8", assessment="unscored")]
        report = diagnose(data)
        self.assertEqual(report["reviews"]["gpt_proxy"]["rating_count"], 0)
        self.assertEqual(report["reviews"]["unscored_markers"], 1)

    def test_stale_review_and_duplicate_reviewer_are_rejected(self):
        data = fixture()
        data["reviews"] = [review(data, candidate_output_sha256=h("stale"))]
        with self.assertRaises(DiagnosticError):
            diagnose(data)
        data["reviews"] = [review(data), review(data, review_id="second-record-same-rating")]
        with self.assertRaises(DiagnosticError):
            diagnose(data)

    def test_mechanics_success_does_not_prove_expression_improvement(self):
        report = diagnose(fixture())
        self.assertEqual(report["training"]["status"], "evidence_consistent")
        self.assertEqual(report["training"]["quality_inference"], "not_established_by_training")
        self.assertEqual(report["distribution_probe"]["status"], "unobserved")
        self.assertFalse(report["training"]["reload_diagnostic"]["is_base_vs_sft_distribution_probe"])

    def test_same_process_id_or_zero_parameter_change_does_not_verify_mechanics(self):
        for mutation in ("same_pid", "zero_change", "wrong_adapter"):
            with self.subTest(mutation=mutation):
                data = fixture()
                if mutation == "same_pid":
                    data["pilot"]["phases"][1]["pid"] = 100
                elif mutation == "zero_change":
                    data["pilot"]["final_parameter_delta"]["l2_norm"] = 0.0
                else:
                    data["pilot"]["adapter_sha256"] = h("wrong-adapter")
                self.assertEqual(diagnose(data)["training"]["status"], "evidence_incomplete_or_inconsistent")

    def test_claimed_single_pass_cannot_hide_duplicate_sample_consumption(self):
        data = fixture()
        data["pilot"]["single_pass"] = True
        data["pilot"]["step_records"] = [
            {"optimizer_step": i + 1, "ids": [f"sample-{4*i+j}" for j in range(4)]}
            for i in range(6)]
        self.assertEqual(diagnose(data)["training"]["sample_consumption_trace"], "consistent")
        data["pilot"]["step_records"][5]["ids"][3] = "sample-0"
        report = diagnose(data)
        self.assertEqual(report["training"]["sample_consumption_trace"], "inconsistent")
        self.assertEqual(report["training"]["status"], "evidence_incomplete_or_inconsistent")

    def test_distribution_probe_reports_observation_not_cause(self):
        data = fixture()
        row = data["records"][2]
        data["distribution_probe"] = {k: row[k] for k in (
            "case_id", "input_sha256", "base_revision", "tokenizer_sha256", "generation_settings",
            "runner_source_sha256", "model_manifest_sha256", "adapter_sha256")}
        data["distribution_probe"].update(same_prefix_verified=True, compared_positions=12,
                                           top1_changed_positions=0, max_abs_logit_delta=0.03)
        report = diagnose(data)
        self.assertEqual(report["distribution_probe"]["observation"], "logits_differ")
        self.assertEqual(report["distribution_probe"]["adapter_not_loaded_inference"], "not_supported")
        data["distribution_probe"]["input_sha256"] = h("foreign-prefix")
        with self.assertRaises(DiagnosticError):
            diagnose(data)


class PublicAdapterAndCLITests(unittest.TestCase):
    def test_public_summary_does_not_invent_per_case_input_bindings(self):
        source = fixture()
        plan, imported = public_fixture(source)
        report = diagnose(adapt_r8_public(plan, imported, source["pilot"]))
        self.assertEqual(report["comparison"]["verified_comparable_pairs"], 0)
        self.assertEqual(report["comparison"]["equal_output_hash_pairs_with_or_without_complete_bindings"], 4)
        self.assertEqual(report["counts"]["planned_positions"], 12)

    def test_wrong_public_denominator_is_rejected(self):
        source = fixture()
        plan, imported = public_fixture(source)
        plan["planned_positions"] = 11
        with self.assertRaises(DiagnosticError):
            adapt_r8_public(plan, imported, source["pilot"])

    def test_public_adapter_never_overwrites_conflicting_record_identity(self):
        source = fixture()
        plan, imported = public_fixture(source)
        imported["rows"][2]["tokenizer_sha256"] = h("wrong-tokenizer")
        with self.assertRaises(DiagnosticError):
            adapt_r8_public(plan, imported, source["pilot"])

    def test_exact_record_bound_sidecar_can_fill_missing_inputs(self):
        source = fixture()
        plan, imported = public_fixture(source)
        side_rows = []
        for row in source["records"]:
            if row["arm"] == "production_q8":
                continue
            side_rows.append({"scene": int(row["case_id"]), **{k: row[k] for k in (
                "arm", "record_sha256", "artifact_bindings_verified", "input_sha256", "base_revision",
                "tokenizer_sha256", "generation_settings", "runner_source_sha256", "model_manifest_sha256")}})
        sidecar = {"schema": "am.expression-input-bindings.v1",
                   "plan_seal_sha256": plan["plan_seal_sha256"],
                   "case_manifest_sha256": plan["case_manifest_sha256"], "rows": side_rows}
        report = diagnose(adapt_r8_public(plan, imported, source["pilot"], input_bindings=sidecar))
        self.assertEqual(report["comparison"]["verified_comparable_pairs"], 4)
        sidecar["rows"][0]["record_sha256"] = h("another-record")
        with self.assertRaises(DiagnosticError):
            adapt_r8_public(plan, imported, source["pilot"], input_bindings=sidecar)

    def test_markdown_contains_counts_and_no_enablement(self):
        text = render_markdown(diagnose(fixture()))
        self.assertIn("计划 12 个位置", text)
        self.assertIn("保持未评分 1 个", text)
        self.assertIn("不会启动训练", text)

    def test_cli_writes_only_new_reports_and_never_overwrites_original(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "input.json", Path(directory) / "report.json"
            source.write_text(json.dumps(fixture()), encoding="utf-8")
            original = source.read_bytes()
            self.assertEqual(main(["diagnose", "--bundle", str(source), "--output", str(target)]), 0)
            self.assertEqual(json.loads(target.read_text())["counts"]["planned_positions"], 12)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["diagnose", "--bundle", str(source), "--output", str(source)]), 2)
            self.assertEqual(source.read_bytes(), original)

    def test_cli_rejects_duplicate_json_keys_and_nan_before_writing(self):
        for text in ('{"schema": "a", "schema": "b"}', '{"value": NaN}'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                source, target = Path(directory) / "bad.json", Path(directory) / "report.json"
                source.write_text(text, encoding="utf-8")
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["diagnose", "--bundle", str(source), "--output", str(target)]), 2)
                self.assertFalse(target.exists())


class NativeR5AdapterTests(unittest.TestCase):
    def native_fixture(self):
        from am_style_r5.evaluation import build_plan, import_results, make_result_record
        from am_style_r5.scenarios import calibration_specs, evaluation_cases
        data = fixture()
        arms = deepcopy(data["plan"]["arms"])
        arms["production_q8"]["model_digest"] = h("fixture-q8")
        cases = evaluation_cases(calibration_specs()[:1])
        plan = build_plan(cases, arms, mode="fixture")
        records = []
        for arm in arms:
            if arm == "production_q8":
                records.append(make_result_record(plan, cases[0]["case_id"], arm,
                                                   status="stop_unknown", runner_source_sha256=h("runner")))
                continue
            request = json.dumps({"wire": cases[0]["student_wire_messages"],
                                  "settings": arms[arm]["generation_settings"]}, ensure_ascii=False)
            output = json.dumps({"text": "开发夹具正文，不能作为真实业务结果。"}, ensure_ascii=False)
            records.append(make_result_record(
                plan, cases[0]["case_id"], arm, status="completed", runner_source_sha256=h("runner"),
                request_artifact=request, response_artifact=output, raw_output=output,
                request_binding={"wire_messages": {"path": ["wire"]},
                                 "generation_settings": {"path": ["settings"]}},
                response_binding={"format": "text"},
            ))
        imported = import_results(plan, records, verifier=lambda _c, _t: {
            "decision": "reject", "reason": "synthetic_guard_result", "verifier": "fixture"})
        return plan, imported, data["pilot"]

    def test_existing_native_schema_is_revalidated_without_writes_or_guard_changes(self):
        plan, imported, pilot = self.native_fixture()
        originals = deepcopy((plan, imported, pilot))
        with patch("builtins.open", side_effect=AssertionError("native fixture must not open files")):
            bundle = adapt_native_r5(plan, imported, pilot)
            report = diagnose(bundle)
        self.assertEqual((plan, imported, pilot), originals)
        self.assertEqual(report["counts"]["planned_positions"], 3)
        self.assertEqual(report["comparison"]["verified_comparable_pairs"], 1)
        self.assertEqual(report["arms"]["mlx_sft"]["fact_guard_states"], {"reject": 1})
        self.assertEqual(report["mlx_pairs"][0]["case_id"], "1")
        self.assertNotIn("开发夹具正文", json.dumps(bundle, ensure_ascii=False))

    def test_resealed_but_changed_request_is_rejected_by_original_importer(self):
        from am_style_r5.common import seal, text_hash
        plan, imported, pilot = self.native_fixture()
        row = imported["rows"][1]
        record = row["record"]
        request = json.loads(record["request_artifact"])
        request["wire"][0]["content"] += "changed"
        record["request_artifact"] = json.dumps(request, ensure_ascii=False)
        record["request_artifact_sha256"] = text_hash(record["request_artifact"])
        row["record"] = seal(record)
        row["record_sha256"] = row["record"]["sha256"]
        imported = seal(imported)
        with self.assertRaises(DiagnosticError):
            adapt_native_r5(plan, imported, pilot)

    def test_native_reviews_bind_original_case_id_but_export_numbered_scene(self):
        plan, imported, pilot = self.native_fixture()
        case_id = plan["cases"][0]["case_id"]
        native_review = {
            "review_id": "native-proxy-1", "case_id": case_id, "arm": "mlx_sft",
            "candidate_output_sha256": imported["rows"][2]["record"]["output_sha256"],
            "kind": "gpt_proxy", "human_authored": False, "reviewer_id": "gpt",
            "authorization_ref": "synthetic-development-authorization", "assessment": "revise",
        }
        report = diagnose(adapt_native_r5(plan, imported, pilot, reviews=[native_review]))
        self.assertEqual(report["reviews"]["gpt_proxy"]["rating_count"], 1)
        self.assertEqual(report["reviews"]["human"]["rating_count"], 0)
        self.assertNotIn(case_id, json.dumps(report))


if __name__ == "__main__":
    unittest.main()
