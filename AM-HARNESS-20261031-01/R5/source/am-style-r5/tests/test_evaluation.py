from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from am_style_r5.common import R5Error, canonical, object_hash, read_json, read_jsonl, seal, text_hash
from am_style_r5.evaluation import (
    PRIMARY_ARMS, blind_batch, build_plan, feedback_report, import_results, freeze_cases,
    latency_summary, make_result_record, preference_content_hash, validate_plan,
)
from am_style.contracts import StylePolicy
from am_style.prompt import build_messages, coordinator_messages
from am_style.render import make_frame


def fixtures():
    shared = {"base_revision": "a" * 40, "model_manifest_sha256": "b" * 64,
              "tokenizer_sha256": "c" * 64, "generation_settings": {"temperature": 0.0, "seed": 221, "max_tokens": 192}}
    arms = {"production_q8": {"model_digest": "d" * 64, "generation_settings": {"max_tokens": 650, "temperature": None}},
            "mlx_base": {**deepcopy(shared), "adapter_sha256": None},
            "mlx_sft": {**deepcopy(shared), "adapter_sha256": "e" * 64}}
    cases = []
    for number in (1, 2):
        policy = StylePolicy()
        frame = make_frame(binding={"turn_id": f"test-{number}", "scope_id": "fixture-test", "outcome_hash": "0" * 64,
                                    "source_revision": "fixture", "revision": 0, "cancel_epoch": 0},
                           expires_at=2000000000, question="谁负责？", family="query",
                           facts=[{"id": f"owner-{number}", "kind": "owner", "subject": "演示项目", "value": "林工"}],
                           policy=policy)
        logical = build_messages(frame, policy)
        cases.append({"case_id": f"case-{number}", "group_id": f"group-{number}", "split": "calibration",
                      "frame": frame.data, "style_policy": policy.as_dict(),
                      "logical_messages": logical,
                      "student_wire_messages": coordinator_messages(logical),
                      "review_context": "事实：林工负责演示项目。", "public_exposed": True,
                      "independent_test_eligible": False})
    return cases, arms


def plan_fixture(**kwargs):
    cases, arms = fixtures()
    return build_plan(cases, arms, mode="fixture", **kwargs)


def good_record(plan, case_id, arm, text="演示项目由林工负责。", status="completed", source="f" * 64):
    case = next(c for c in plan["cases"] if c["case_id"] == case_id)
    raw = canonical({"text": text})
    request = canonical({"actual_messages": case["student_wire_messages"],
                         "generation_settings": plan["arms"][arm]["generation_settings"],
                         "provider_request": {"messages": case["student_wire_messages"]}})
    return make_result_record(plan, case_id, arm, status=status, runner_source_sha256=source,
        request_artifact=request, response_artifact=canonical({"generated": raw}), raw_output=raw,
        request_binding={"wire_messages": {"path": ["actual_messages"]}, "generation_settings": {"path": ["generation_settings"]}},
        response_binding={"path": ["generated"]}, latency_ms={"end_to_end": 100, "provider": 90},
        capture_kind="fixture" if plan["mode"] == "fixture" else "actual_provider_exchange")


def imported(plan, *, texts=None):
    records = [good_record(plan, c["case_id"], arm, text=(texts or {}).get(arm, "演示项目由林工负责。"))
               for c in plan["cases"] for arm in plan["arms"]]
    return import_results(plan, records, verifier=lambda case, text: {"decision": "pass", "reason": "fixture-only"})


def full_feedback(public, private, *, outcome="left", fact="pass", absolute=True):
    ratings = []
    for task in public["tasks"]:
        for option in task["options"]:
            ratings.append({"option_id": option["option_id"], "text_sha256": option["text_sha256"],
                            "fact": fact, "naturalness": 4, "absolute_usable": absolute})
    task = public["tasks"][0]
    chosen = sorted([x for x in task["options"] if private["options"][x["option_id"]]["arm"] in {"mlx_base", "mlx_sft"}],
                    key=lambda x: private["options"][x["option_id"]]["arm"])
    return {"public_sha256": public["sha256"], "mode": public["mode"], "reviewer": "fixture reviewer", "reviewed_at": "2026-11-02",
            "ratings": ratings, "preferences": [{"task_id": task["task_id"], "option_ids": [x["option_id"] for x in chosen],
                "content_sha256": preference_content_hash(task["task_id"], *chosen), "outcome": outcome}]}


class PlanTests(unittest.TestCase):
    def test_case_freeze_precedes_adapter_without_changing_manifest(self):
        cases, arms = fixtures()
        frozen = freeze_cases(cases)
        self.assertNotIn("arms", frozen)
        self.assertEqual(frozen["independence"], "not_assessed")
        self.assertEqual(freeze_cases(frozen), frozen)
        plan = build_plan(frozen, arms, mode="fixture")
        self.assertEqual(plan["case_manifest_sha256"], frozen["case_manifest_sha256"])
        arms["mlx_sft"]["adapter_sha256"] = "0" * 64
        different_adapter = build_plan(frozen, arms, mode="fixture")
        self.assertNotEqual(plan["sha256"], different_adapter["sha256"])
        self.assertEqual(plan["case_manifest_sha256"], different_adapter["case_manifest_sha256"])

    def test_case_freeze_does_not_approve_independence_or_skip_exclusion(self):
        cases, arms = fixtures()
        for case in cases:
            case.update(split="sealed_test", public_exposed=False, independent_test_eligible=True)
        frozen = freeze_cases(cases)
        self.assertEqual(frozen["independence"], "not_assessed")
        with self.assertRaises(R5Error):
            build_plan(frozen, arms, mode="real")

    def test_three_arms_are_mandatory(self):
        cases, arms = fixtures()
        del arms["mlx_sft"]
        with self.assertRaises(R5Error):
            build_plan(cases, arms, mode="fixture")

    def test_calibration_actual_calls_do_not_become_holdout(self):
        cases, arms = fixtures()
        plan = build_plan(cases, arms, mode="real", training_groups=["group-1"])
        self.assertEqual(plan["sample_status"], "not_independent")
        self.assertEqual(plan["holdout_groups"], [])

    def test_mlx_base_revision_tokenizer_settings_and_model_must_match(self):
        for field, value in [("base_revision", "f" * 40), ("tokenizer_sha256", "9" * 64),
                             ("model_manifest_sha256", "8" * 64), ("generation_settings", {"max_tokens": 100})]:
            with self.subTest(field=field):
                cases, arms = fixtures()
                arms["mlx_sft"][field] = value
                with self.assertRaises(R5Error):
                    build_plan(cases, arms, mode="fixture")

    def test_base_cannot_load_adapter(self):
        cases, arms = fixtures()
        arms["mlx_base"]["adapter_sha256"] = "a" * 64
        with self.assertRaises(R5Error):
            build_plan(cases, arms, mode="fixture")

    def test_public_example_cannot_be_relabeled_independent(self):
        cases, arms = fixtures()
        cases[0]["split"] = "sealed_test"
        with self.assertRaises(R5Error):
            build_plan(cases, arms, mode="real")

    def test_sealed_group_overlap_and_missing_declaration_rejected(self):
        cases, arms = fixtures()
        for case in cases:
            case.update(split="sealed_test", public_exposed=False, independent_test_eligible=True)
        with self.assertRaises(R5Error):
            build_plan(cases, arms, mode="fixture", training_groups=["group-1"])
        with self.assertRaises(R5Error):
            build_plan(cases, arms, mode="real")
        provisional = build_plan(cases, arms, mode="fixture")
        declaration = {"case_manifest_sha256": provisional["case_manifest_sha256"], "not_used_for_tuning": True,
                       "declared_by": "human", "declared_at": "2026-11-02", "source_evidence_sha256": "0" * 64}
        with self.assertRaises(R5Error):
            build_plan(cases, arms, mode="real", holdout_declaration=declaration)
        cases[0]["logical_messages"][0]["content"] = "changed"
        with self.assertRaises(R5Error):
            build_plan(cases, arms, mode="real", holdout_declaration=declaration)

    def test_duplicate_cases_rejected(self):
        cases, arms = fixtures()
        with self.assertRaises(R5Error):
            build_plan(cases + cases, arms, mode="fixture")

    def test_resealed_frame_cannot_keep_stale_prompt(self):
        plan = plan_fixture()
        plan["cases"][0]["frame"]["question"] = "现在进展呢？"
        with self.assertRaises(R5Error):
            validate_plan(seal(plan))

    def test_optional_unavailable_stays_in_denominator(self):
        cases, arms = fixtures()
        arms["codex"] = {"availability": "blocked", "reason": "raw empty-tool proof unavailable"}
        plan = build_plan(cases, arms, mode="fixture")
        result = import_results(plan, [])
        report = feedback_report(plan, result)
        self.assertEqual(report["planned_results"], 8)
        self.assertEqual(report["arms"]["codex"]["statuses"], {"blocked": 2})


class ImportTests(unittest.TestCase):
    def test_missing_unknown_error_and_blocked_keep_denominator(self):
        plan = plan_fixture()
        rows = [good_record(plan, "case-1", arm, status=status) for arm, status in zip(PRIMARY_ARMS, ["unknown", "error", "blocked"])]
        result = import_results(plan, rows)
        self.assertEqual(len(result["rows"]), 6)
        self.assertEqual(sum(r["status"] == "missing" for r in result["rows"]), 3)
        self.assertFalse(result["production_enabled"])

    def test_duplicate_results_not_cherry_picked(self):
        plan = plan_fixture()
        row = good_record(plan, "case-1", "mlx_base")
        with self.assertRaises(R5Error):
            import_results(plan, [row, row])

    def test_changed_input_even_resealed_rejected(self):
        plan = plan_fixture()
        row = good_record(plan, "case-1", "mlx_base")
        row["frame_sha256"] = "1" * 64
        with self.assertRaises(R5Error):
            import_results(plan, [seal(row)])

    def test_artifact_hash_mismatch_rejected(self):
        plan = plan_fixture()
        row = good_record(plan, "case-1", "mlx_base")
        row["response_artifact"] = "changed"
        with self.assertRaises(R5Error):
            import_results(plan, [seal(row)])

    def test_actual_payload_different_input_cannot_pass_self_reported_hashes(self):
        plan = plan_fixture()
        row = good_record(plan, "case-1", "mlx_base")
        body = {"actual_messages": [{"role": "user", "content": "wrong prompt"}], "generation_settings": plan["arms"]["mlx_base"]["generation_settings"]}
        row["request_artifact"] = canonical(body)
        row["request_artifact_sha256"] = text_hash(row["request_artifact"])
        with self.assertRaises(R5Error):
            import_results(plan, [seal(row)])

    def test_actual_generation_settings_mismatch_rejected(self):
        plan = plan_fixture()
        row = good_record(plan, "case-1", "mlx_base")
        body = {"actual_messages": plan["cases"][0]["student_wire_messages"], "generation_settings": {"temperature": 1}}
        row["request_artifact"] = canonical(body)
        row["request_artifact_sha256"] = text_hash(row["request_artifact"])
        with self.assertRaises(R5Error):
            import_results(plan, [seal(row)])

    def test_actual_response_mismatch_rejected(self):
        plan = plan_fixture()
        row = good_record(plan, "case-1", "mlx_base")
        row["response_artifact"] = canonical({"generated": "other output"})
        row["response_artifact_sha256"] = text_hash(row["response_artifact"])
        with self.assertRaises(R5Error):
            import_results(plan, [seal(row)])

    def test_fixture_cannot_be_counted_real(self):
        cases, arms = fixtures()
        plan = build_plan(cases, arms, mode="real")
        row = good_record(plan, "case-1", "mlx_base")
        row["capture_kind"] = "fixture"
        with self.assertRaises(R5Error):
            import_results(plan, [seal(row)])

    def test_real_flag_without_artifacts_does_not_pass(self):
        cases, arms = fixtures()
        plan = build_plan(cases, arms, mode="real")
        row = make_result_record(plan, "case-1", "mlx_base", status="completed", runner_source_sha256="f" * 64,
                                 capture_kind="actual_provider_exchange", raw_output='{"text":"林工负责。"}')
        with self.assertRaises(R5Error):
            import_results(plan, [row])

    def test_schema_fail_retained_and_human_naturalness_unclaimed(self):
        plan = plan_fixture()
        row = good_record(plan, "case-1", "mlx_base")
        raw = 'not JSON'
        row.update(raw_output=raw, raw_output_sha256=text_hash(raw), output_text=None, output_sha256=None,
                   response_artifact=canonical({"generated": raw}))
        row["response_artifact_sha256"] = text_hash(row["response_artifact"])
        result = import_results(plan, [seal(row)])
        found = next(r for r in result["rows"] if r["arm"] == "mlx_base" and r["case_id"] == "case-1")
        self.assertEqual(found["status"], "completed")
        self.assertFalse(found["schema_pass"])
        self.assertEqual(found["naturalness"], "not_evaluated_by_machine")

    def test_negative_and_nonfinite_latency_rejected(self):
        plan = plan_fixture()
        row = good_record(plan, "case-1", "mlx_base")
        row["latency_ms"]["end_to_end"] = -1
        with self.assertRaises(R5Error):
            import_results(plan, [seal(row)])


class BlindReviewTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan_fixture()
        self.result = imported(self.plan, texts={"mlx_sft": "林工负责演示项目。"})
        self.public, self.private = blind_batch(self.plan, self.result)

    def test_public_task_contains_no_arm_or_private_mapping(self):
        serialized = canonical(self.public)
        self.assertTrue(all(arm not in serialized for arm in PRIMARY_ARMS))
        self.assertNotIn("case-1", serialized)
        self.assertNotIn("record_sha256", serialized)
        self.assertEqual(self.public["sample_status"], "not_independent")
        self.assertEqual(self.public["tasks"][0]["question"], "谁负责？")

    def test_fresh_secure_mapping_each_batch(self):
        other, other_private = blind_batch(self.plan, self.result)
        ids = set(self.private["options"])
        self.assertFalse(ids & set(other_private["options"]))
        self.assertNotEqual(self.public["batch_id"], other["batch_id"])

    def test_fact_naturalness_absolute_and_preference_remain_separate(self):
        feedback = full_feedback(self.public, self.private, outcome="right")
        report = feedback_report(self.plan, self.result, self.public, self.private, feedback)
        self.assertEqual(report["mlx_comparison"]["relative_votes"], {"mlx_sft": 1})
        self.assertEqual(report["mlx_comparison"]["eligible_preference_evidence"], 1)
        self.assertEqual(report["arms"]["mlx_sft"]["human_usable_cases"], 2)
        self.assertEqual(report["naturalness_improvement"], "not_established_by_automated_report")
        self.assertFalse(report["production_enabled"])

    def test_tie_both_bad_and_cannot_judge_are_not_forced_winners(self):
        for outcome in ("tie", "both_bad", "cannot_judge"):
            with self.subTest(outcome=outcome):
                report = feedback_report(self.plan, self.result, self.public, self.private,
                                         full_feedback(self.public, self.private, outcome=outcome))
                self.assertEqual(report["mlx_comparison"]["relative_votes"], {outcome: 1})
                self.assertEqual(report["mlx_comparison"]["eligible_preference_evidence"], 0)

    def test_least_bad_not_eligible_preference_training_evidence(self):
        feedback = full_feedback(self.public, self.private, absolute=False)
        report = feedback_report(self.plan, self.result, self.public, self.private, feedback)
        self.assertEqual(report["mlx_comparison"]["eligible_preference_evidence"], 0)

    def test_modified_text_cannot_reuse_approval(self):
        feedback = full_feedback(self.public, self.private)
        feedback["ratings"][0]["edited_text"] = "周工负责。"
        with self.assertRaises(R5Error):
            feedback_report(self.plan, self.result, self.public, self.private, feedback)

    def test_unknown_text_rewrite_field_cannot_be_ignored(self):
        feedback = full_feedback(self.public, self.private)
        feedback["ratings"][0]["text"] = "用户另改的完整回复"
        with self.assertRaises(R5Error):
            feedback_report(self.plan, self.result, self.public, self.private, feedback)

    def test_wrong_content_hash_and_replayed_batch_rejected(self):
        feedback = full_feedback(self.public, self.private)
        feedback["preferences"][0]["content_sha256"] = "0" * 64
        with self.assertRaises(R5Error):
            feedback_report(self.plan, self.result, self.public, self.private, feedback)
        other, other_private = blind_batch(self.plan, self.result)
        with self.assertRaises(R5Error):
            feedback_report(self.plan, self.result, other, other_private, full_feedback(self.public, self.private))

    def test_cross_input_preference_rejected(self):
        feedback = full_feedback(self.public, self.private)
        preference = feedback["preferences"][0]
        other = self.public["tasks"][1]["options"][0]
        preference["option_ids"][1] = other["option_id"]
        with self.assertRaises(R5Error):
            feedback_report(self.plan, self.result, self.public, self.private, feedback)

    def test_duplicate_reviewer_rating_not_double_counted(self):
        feedback = full_feedback(self.public, self.private)
        feedback["ratings"].append(feedback["ratings"][0])
        with self.assertRaises(R5Error):
            feedback_report(self.plan, self.result, self.public, self.private, feedback)

    def test_identity_disclosure_is_not_silently_removed(self):
        result = imported(self.plan, texts={"mlx_sft": "mlx_sft says 林工负责。"})
        with self.assertRaises(R5Error):
            blind_batch(self.plan, result)

    def test_same_text_does_not_create_dpo_evidence(self):
        result = imported(self.plan)
        public, private = blind_batch(self.plan, result)
        report = feedback_report(self.plan, result, public, private, full_feedback(public, private))
        self.assertEqual(report["mlx_comparison"]["eligible_preference_evidence"], 0)

    def test_different_runner_sources_do_not_count_as_adapter_pairs(self):
        rows = [good_record(self.plan, c["case_id"], arm, source=("0" * 64 if arm == "mlx_sft" else "f" * 64))
                for c in self.plan["cases"] for arm in PRIMARY_ARMS]
        result = import_results(self.plan, rows, verifier=lambda c, t: {"decision": "pass"})
        public, private = blind_batch(self.plan, result)
        report = feedback_report(self.plan, result, public, private, full_feedback(public, private))
        self.assertEqual(report["mlx_comparison"]["completed_pairs"], 2)
        self.assertEqual(report["mlx_comparison"]["same_runner_source_pairs"], 0)
        self.assertEqual(report["mlx_comparison"]["relative_vote_count"], 0)


class MetricTests(unittest.TestCase):
    def test_linear_quantile_convention(self):
        summary = latency_summary([0, 10, 20, 30])
        self.assertEqual(summary["p50_ms"], 15)
        self.assertAlmostEqual(summary["p95_ms"], 28.5)
        self.assertEqual(summary["max_ms"], 30)
        self.assertEqual(latency_summary([])["p95_ms"], None)

    def test_missing_result_not_removed_from_quality_denominator(self):
        plan = plan_fixture()
        result = import_results(plan, [good_record(plan, "case-1", "mlx_sft")], verifier=lambda c, t: {"decision": "pass"})
        public, private = blind_batch(plan, result)
        option = public["tasks"][0]["options"][0]
        feedback = {"public_sha256": public["sha256"], "mode": "fixture", "reviewer": "fixture", "reviewed_at": "today",
                    "ratings": [{"option_id": option["option_id"], "text_sha256": option["text_sha256"], "fact": "pass", "naturalness": 5, "absolute_usable": True}]}
        report = feedback_report(plan, result, public, private, feedback)
        self.assertEqual(report["arms"]["mlx_sft"]["planned_cases"], 2)
        self.assertEqual(report["arms"]["mlx_sft"]["usable_over_planned"], .5)
        self.assertEqual(report["arms"]["mlx_base"]["statuses"], {"missing": 2})

    def test_pinned_verifier_is_separate_from_naturalness(self):
        plan = plan_fixture()
        result = import_results(plan, [good_record(plan, "case-1", "mlx_base")])
        row = next(r for r in result["rows"] if r["case_id"] == "case-1" and r["arm"] == "mlx_base")
        self.assertEqual(row["safety"]["decision"], "pass")
        self.assertEqual(row["safety"]["verifier"], "R4_bounded_plus_natural")
        self.assertEqual(row["naturalness"], "not_evaluated_by_machine")

    def test_failed_and_unknown_latency_not_hidden(self):
        plan = plan_fixture()
        success = good_record(plan, "case-1", "mlx_base")
        timeout = good_record(plan, "case-2", "mlx_base", status="stop_unknown")
        timeout["latency_ms"]["end_to_end"] = 9000
        result = import_results(plan, [success, seal(timeout)])
        arm = feedback_report(plan, result)["arms"]["mlx_base"]
        self.assertEqual(arm["attempt_end_to_end_latency"]["n"], 2)
        self.assertEqual(arm["attempt_end_to_end_latency"]["max_ms"], 9000)
        self.assertEqual(arm["completed_end_to_end_latency"]["n"], 1)
        self.assertEqual(arm["completed_end_to_end_latency"]["max_ms"], 100)


class SnapshotExclusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from am_style_r5.dataset import freeze_group_registry, export_gold_snapshot
        from am_style_r5.scenarios import calibration_specs
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(__file__).resolve().parents[1]
        base_train = cls.root / "baseline/data/r4-gold/sft.train.jsonl"
        base_dev = cls.root / "baseline/data/r4-gold/sft.dev.jsonl"
        registry = freeze_group_registry(calibration_specs(), baseline_train=base_train, baseline_dev=base_dev)
        output = Path(cls.temp.name) / "gold"
        export_gold_snapshot(registry, [], baseline_train=base_train, baseline_dev=base_dev, output_dir=output)
        cls.snapshot_path = output / "snapshot.json"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_verified_snapshot_and_declaration_bind_real_sealed_plan(self):
        cases, arms = fixtures()
        for case in cases:
            case.update(split="sealed_test", public_exposed=False, independent_test_eligible=True)
        provisional = build_plan(cases, arms, mode="fixture", exclusion_snapshot_path=self.snapshot_path)
        declaration = {"case_manifest_sha256": provisional["case_manifest_sha256"], "not_used_for_tuning": True,
                       "declared_by": "human", "declared_at": "2026-11-02", "source_evidence_sha256": "0" * 64}
        for split in ("train", "dev"):
            arms["mlx_sft"][split + "_file_sha256"] = provisional["exclusion_snapshot"]["files_sha256"][split]
        plan = build_plan(cases, arms, mode="real", holdout_declaration=declaration, exclusion_snapshot_path=self.snapshot_path)
        self.assertEqual(plan["sample_status"], "independent_declared")
        self.assertEqual(len(plan["exclusion_snapshot"]["records"]), 10)
        self.assertEqual(validate_plan(plan), plan)
        corrupt = deepcopy(plan)
        corrupt["exclusion_snapshot"]["records"][0]["prompt"][0]["content"] = "replaced old prompt"
        with self.assertRaises(R5Error):
            validate_plan(seal(corrupt))

    def test_selected_sft_different_training_hash_cannot_use_other_exclusion_snapshot(self):
        cases, arms = fixtures()
        for case in cases:
            case.update(split="sealed_test", public_exposed=False, independent_test_eligible=True)
        provisional = build_plan(cases, arms, mode="fixture", exclusion_snapshot_path=self.snapshot_path)
        declaration = {"case_manifest_sha256": provisional["case_manifest_sha256"], "not_used_for_tuning": True,
                       "declared_by": "human", "declared_at": "2026-11-02", "source_evidence_sha256": "0" * 64}
        for split in ("train", "dev"):
            arms["mlx_sft"][split + "_file_sha256"] = provisional["exclusion_snapshot"]["files_sha256"][split]
        for changed_split in ("train", "dev"):
            with self.subTest(split=changed_split):
                other_training = deepcopy(arms)
                other_training["mlx_sft"][changed_split + "_file_sha256"] = "9" * 64
                with self.assertRaisesRegex(R5Error, "training data differs"):
                    build_plan(cases, other_training, mode="real", holdout_declaration=declaration,
                               exclusion_snapshot_path=self.snapshot_path)
        missing_hash = deepcopy(arms)
        del missing_hash["mlx_sft"]["train_file_sha256"]
        with self.assertRaisesRegex(R5Error, "selected SFT train"):
            build_plan(cases, missing_hash, mode="real", holdout_declaration=declaration,
                       exclusion_snapshot_path=self.snapshot_path)

    def test_old_prompt_with_new_group_does_not_evade_exclusion(self):
        frozen = read_json(self.root / "baseline/data/r3-frozen-comparison.json")
        old_train = read_jsonl(self.root / "baseline/data/r4-gold/sft.train.jsonl")[0]
        source = next(c for c in frozen["cases"] if c["case_id"] == old_train["id"])
        policy = StylePolicy(**frozen["policy"])
        logical = build_messages(source["frame"], policy)
        case = {"case_id": "new-id", "group_id": "invented-new-group", "split": "sealed_test",
                "frame": source["frame"], "style_policy": policy.as_dict(), "logical_messages": logical,
                "student_wire_messages": coordinator_messages(logical), "review_context": "旧事实",
                "public_exposed": False, "independent_test_eligible": True}
        _, arms = fixtures()
        with self.assertRaisesRegex(R5Error, "leaks training/development prompt"):
            build_plan([case], arms, mode="fixture", exclusion_snapshot_path=self.snapshot_path)


if __name__ == "__main__":
    unittest.main()
