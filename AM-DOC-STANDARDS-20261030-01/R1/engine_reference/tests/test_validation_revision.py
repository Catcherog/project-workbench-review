from __future__ import annotations

import unittest
from dataclasses import replace

from am_doc_engine.adapters import EvidenceBoundModelComposer, ExtractiveComposer, extractive_text
from am_doc_engine.content_checks import numeric_tokens, positive_business_claims
from am_doc_engine.models import (
    ContractError, DraftDocument, DraftField, DraftRequest, Evidence, FieldResolution, FieldRule,
    RevisionConflict, SectionSpec, SourceAsset, TemplateProfile,
)
from am_doc_engine.revision import plan_revision, plan_template_migration
from am_doc_engine.validation import validate_document


def profile(*, mode="extractive", value_type="any", revision="1"):
    return TemplateProfile(
        tenant_id="tenant", template_id="closure", revision=revision, rule_version="1",
        doc_type="closure", title="结项报告", project_types=("light",), stages=("close",),
        sections=(SectionSpec("result", "结果"),),
        fields=(FieldRule("result", "result", "验收结果", ("acceptance",), "照实填写结果", ("template",), mode=mode, value_type=value_type),),
        assets=(SourceAsset("template", "template", "synthetic://template", revision, "# 结果"),),
        status="effective", effective_at="2026-10-30T08:00:00+08:00", activation_ref="synthetic://ledger/effective",
    )


def evidence(value="验收通过", **changes):
    values = dict(
        evidence_id="E1", tenant_id="tenant", project_id="P1", key="acceptance", value=value,
        semantic="actual", state="confirmed", source_id="report", source_uri="synthetic://report",
        source_revision="1", locator="result:1", observed_at="2026-10-30T09:00:00+08:00",
    )
    values.update(changes)
    return Evidence(**values)


def request(**changes):
    values = dict(request_id="request", tenant_id="tenant", project_id="P1", doc_type="closure", project_type="light", stage="close")
    values.update(changes)
    return DraftRequest(**values)


def document(*, fields=None, revision=1, template=None, **changes):
    template = template or profile()
    values = dict(
        document_id="doc", tenant_id="tenant", project_id="P1", doc_type="closure", title="项目结项报告",
        template_id=template.template_id, template_revision=template.revision,
        template_hash=template.content_hash, rule_version=template.rule_version,
        snapshot_id="snapshot1", snapshot_hash="hash1", as_of="2026-10-30T09:00:00+08:00",
        revision=revision, sections=template.sections,
        fields=fields if fields is not None else (DraftField("result", "实际结果：验收通过", ("E1",)),),
        issues=(), questions=(), state="draft_complete", created_at="2026-10-30T09:01:00+08:00",
    )
    values.update(changes)
    return DraftDocument(**values)


class ValidationTests(unittest.TestCase):
    def check(self, facts, draft=None, template=None, req=None):
        template, req = template or profile(), req or request()
        resolution = FieldResolution("result", tuple(facts))
        if draft is None:
            draft = ExtractiveComposer().compose(template.fields[0], resolution, req, template)
        return validate_document(template, req, (draft,), (resolution,))

    def test_complete_extractive_document_uses_actual_source(self):
        self.assertEqual(self.check([evidence()]), ())

    def test_foreign_example_and_project_cannot_be_used_as_facts(self):
        cases = [evidence(role="example"), evidence(project_id="P2"), evidence(tenant_id="foreign")]
        for fact in cases:
            with self.subTest(fact=fact):
                direct = DraftField("result", extractive_text((fact,)), (fact.evidence_id,))
                self.assertTrue(any(issue.severity == "error" for issue in self.check([fact], direct)))

    def test_citation_from_other_field_is_rejected(self):
        draft = DraftField("result", "实际结果：验收通过", ("E9",))
        codes = {x.code for x in self.check([evidence()], draft)}
        self.assertIn("foreign_evidence_reference", codes)

    def test_duplicate_and_unknown_generated_field(self):
        p, req = profile(), request()
        facts = (FieldResolution("result", (evidence(),)),)
        f = DraftField("result", "实际结果：验收通过", ("E1",))
        issues = validate_document(p, req, (f, f, replace(f, field_id="invented")), facts)
        self.assertTrue({"duplicate_field", "unknown_field"} <= {x.code for x in issues})

    def test_missing_required_fact_leaves_observable_gap(self):
        resolution = FieldResolution("result", (), missing_keys=("acceptance",))
        p, req = profile(), request()
        item = ExtractiveComposer().compose(p.fields[0], resolution, req, p)
        self.assertIn("field_missing", {x.code for x in validate_document(p, req, (item,), (resolution,))})

    def test_only_effective_stage_condition_is_required(self):
        p = profile()
        rule = replace(p.fields[0], applies_when={"stage": ("close",)})
        p = replace(p, fields=(rule,), stages=("*",))
        req = request(stage="executing")
        f = DraftField("result", "不适用", (), "not_applicable")
        self.assertEqual(validate_document(p, req, (f,), (FieldResolution("result", ()),)), ())
        invalid = replace(f, text="验收通过", status="filled", evidence_ids=("E1",))
        self.assertIn("inapplicable_field_filled", {x.code for x in validate_document(p, req, (invalid,), ())})

    def test_conditional_requiredness_differs_between_draft_and_submission(self):
        p = profile()
        p = replace(p, fields=(replace(p.fields[0], required=False, required_when={"mode": ("submit",)}),))
        draft = DraftField("result", "待补", (), "missing")
        resolution = (FieldResolution("result", (), missing_keys=("acceptance",)),)
        draft_issues = validate_document(p, request(), (draft,), resolution)
        submit_issues = validate_document(p, request(mode="submit"), (draft,), resolution)
        self.assertFalse(any(x.severity == "error" for x in draft_issues))
        self.assertTrue(any(x.severity == "error" for x in submit_issues))

    def test_planned_date_must_not_be_substituted_for_actual(self):
        fact = evidence("2026-11-01", semantic="forecast")
        direct = DraftField("result", extractive_text((fact,)), (fact.evidence_id,))
        self.assertIn("evidence_rule_mismatch", {x.code for x in self.check([fact], direct, template=profile(value_type="date"))})

    def test_invalid_calendar_date_does_not_pass_date_field(self):
        self.assertIn("invalid_evidence_value", {x.code for x in self.check([evidence("2026-02-30")], template=profile(value_type="date"))})

    def test_boolean_is_not_a_budget_number(self):
        self.assertIn("invalid_evidence_value", {x.code for x in self.check([evidence(True)], template=profile(value_type="number"))})

    def test_new_numbers_and_dates_are_flagged(self):
        p = profile(mode="narrative")
        f = DraftField("result", "完成 9 台，日期 2026-11-01。", ("E1",), origin="model")
        issues = self.check([evidence("完成 3 台，日期 2026-10-30。")], f, p)
        self.assertIn("unsupported_number_or_date", {x.code for x in issues})

    def test_model_identifier_and_list_ordinal_are_not_counts(self):
        p = profile(mode="narrative")
        f = DraftField("result", "1. eRob70I：完成测试。", ("E1",), origin="model")
        issues = self.check([evidence("eRob70I：完成测试。")], f, p)
        self.assertNotIn("unsupported_number_or_date", {x.code for x in issues})
        self.assertIn("semantic_review_required", {x.code for x in issues})

    def test_negated_source_cannot_support_positive_acceptance(self):
        p = profile(mode="narrative")
        f = DraftField("result", "验收通过。", ("E1",), origin="model")
        self.assertIn("unsupported_business_conclusion", {x.code for x in self.check([evidence("尚未验收通过")], f, p)})

    def test_test_completion_is_not_acceptance_pass(self):
        p = profile(mode="narrative")
        f = DraftField("result", "验收通过。", ("E1",), origin="model")
        self.assertIn("unsupported_business_conclusion", {x.code for x in self.check([evidence("测试已完成")], f, p)})

    def test_confirmed_acceptance_supports_its_own_statement(self):
        p = profile(mode="narrative")
        f = DraftField("result", "验收通过。", ("E1",), origin="model")
        issues = self.check([evidence()], f, p)
        self.assertNotIn("unsupported_business_conclusion", {x.code for x in issues})
        self.assertIn("semantic_review_required", {x.code for x in issues})

    def test_source_placeholder_does_not_become_complete_content(self):
        self.assertIn("invalid_evidence_value", {x.code for x in self.check([evidence("待确认")])})

    def test_extractive_rephrasing_is_detected(self):
        f = DraftField("result", "已经通过验收。", ("E1",))
        self.assertIn("extractive_value_changed", {x.code for x in self.check([evidence()], f)})

    def test_narrative_rule_with_deterministic_fallback_needs_no_model_review(self):
        issues = self.check([evidence()], template=profile(mode="narrative"))
        self.assertNotIn("semantic_review_required", {x.code for x in issues})
        self.assertFalse(any(x.severity == "error" for x in issues))

    def test_tampered_extractive_origin_cannot_skip_narrative_review(self):
        p = profile(mode="narrative")
        f = DraftField("result", "验收已顺利通过。", ("E1",), origin="extractive")
        self.assertTrue({"semantic_review_required", "extractive_value_changed"} <= {x.code for x in self.check([evidence()], f, p)})

    def test_explicit_empty_action_list_is_a_valid_known_value(self):
        for kind in ("list", "any"):
            with self.subTest(kind=kind):
                self.assertEqual(self.check([evidence([])], template=profile(value_type=kind)), ())

    def test_zero_is_a_real_number_not_a_missing_value(self):
        self.assertEqual(self.check([evidence(0)], template=profile(value_type="number")), ())

    def test_controlled_planned_proposed_and_forecast_passage_stays_attributed(self):
        for semantic, state in [("baseline", "confirmed"), ("proposal", "proposed"), ("forecast", "reported")]:
            with self.subTest(semantic=semantic):
                p = profile(mode="narrative")
                p = replace(p, fields=(replace(p.fields[0], semantics=(semantic,), accepted_states=(state,)),))
                issues = self.check([evidence("通过验收", semantic=semantic, state=state)], template=p)
                self.assertNotIn("unsupported_business_conclusion", {x.code for x in issues})
                self.assertNotIn("semantic_review_required", {x.code for x in issues})

    def test_model_cannot_turn_anticipated_acceptance_into_actual_acceptance(self):
        p = profile(mode="narrative")
        p = replace(p, fields=(replace(p.fields[0], semantics=("forecast",), accepted_states=("reported",)),))
        f = DraftField("result", "验收通过。", ("E1",), origin="model")
        issues = self.check([evidence("通过验收", semantic="forecast", state="reported")], f, p)
        self.assertIn("unsupported_business_conclusion", {x.code for x in issues})


class SharedContentCheckRegressionTests(unittest.TestCase):
    def validate_model_text(self, text, facts):
        p = profile(mode="narrative")
        f = DraftField("result", text, tuple(item.evidence_id for item in facts), origin="model")
        return validate_document(p, request(), (f,), (FieldResolution("result", tuple(facts)),))

    def assert_shared_passes(self, text, facts):
        EvidenceBoundModelComposer._lexical_guard(text, facts)
        codes = {issue.code for issue in self.validate_model_text(text, facts)}
        self.assertNotIn("unsupported_number_or_date", codes)
        self.assertNotIn("unsupported_business_conclusion", codes)

    def assert_shared_rejects_conclusion(self, text, facts):
        with self.assertRaises(ContractError):
            EvidenceBoundModelComposer._lexical_guard(text, facts)
        self.assertIn("unsupported_business_conclusion", {issue.code for issue in self.validate_model_text(text, facts)})

    def test_list_marker_does_not_become_a_new_quantity(self):
        self.assert_shared_passes("1. 当前进度稳定", [evidence("当前进度稳定")])
        self.assertEqual(numeric_tokens("1. 当前进度稳定\n2、资料齐全\n(3) 稍后归档"), set())

    def test_thousands_separator_does_not_change_numeric_fact(self):
        self.assert_shared_passes("成本为1000元", [evidence("成本为1,000元")])
        self.assert_shared_passes("成本为1,000.00元", [evidence("成本为１０００元")])

    def test_normalization_does_not_round_long_numbers(self):
        first, second = "1234567890123456789012345678901", "1234567890123456789012345678902"
        self.assertEqual(numeric_tokens(first), {first})
        with self.assertRaises(ContractError):
            EvidenceBoundModelComposer._lexical_guard(second, [evidence(first)])

    def test_real_decimal_at_start_of_line_is_not_a_list_marker(self):
        self.assertEqual(numeric_tokens("1.5 台"), {"1.5"})
        with self.assertRaises(ContractError):
            EvidenceBoundModelComposer._lexical_guard("1.5 台", [evidence("1 台")])

    def test_percent_and_plain_quantity_are_distinct(self):
        with self.assertRaises(ContractError):
            EvidenceBoundModelComposer._lexical_guard("50%", [evidence("50")])
        self.assert_shared_passes("50％", [evidence("50.0%")])

    def test_uncertain_confirmation_is_not_a_positive_success_claim(self):
        facts = [evidence("测试已完成")]
        for text in ["尚不能确认测试通过", "目前无法据此确认测试通过", "没有证据表明测试通过", "测试通过的说法未经证实"]:
            with self.subTest(text=text):
                self.assert_shared_passes(text, facts)

    def test_negated_source_cannot_be_reused_as_positive_support(self):
        self.assert_shared_rejects_conclusion("测试通过", [evidence("未测试通过")])
        self.assert_shared_rejects_conclusion("已批准", [evidence("尚不能确认已批准")])

    def test_uncertain_source_cannot_support_actual_success(self):
        for source in ["尚不能确认测试通过", "没有证据表明测试通过", "测试通过尚未确认", "测试通过的说法未经证实"]:
            with self.subTest(source=source):
                self.assert_shared_rejects_conclusion("测试通过", [evidence(source)])

    def test_negation_about_budget_does_not_mask_test_claim(self):
        self.assert_shared_rejects_conclusion("预算尚未确认，测试通过", [evidence("测试已完成")])
        self.assertEqual(positive_business_claims("预算尚未确认，测试通过"), {"test_passed"})

    def test_negation_scope_stops_at_next_clause(self):
        source = "尚不能确认测试通过，验收通过"
        self.assertEqual(positive_business_claims(source), {"acceptance_passed"})
        self.assert_shared_rejects_conclusion("测试通过", [evidence(source)])
        self.assert_shared_passes("验收通过", [evidence(source)])

    def test_negation_scope_stops_at_contrast(self):
        self.assertEqual(positive_business_claims("尚不能确认测试通过但验收通过"), {"acceptance_passed"})

    def test_later_unrelated_uncertainty_does_not_remove_confirmed_passage(self):
        source = "测试通过，材料尚未归档"
        self.assertEqual(positive_business_claims(source), {"test_passed"})
        self.assert_shared_passes("测试通过", [evidence(source)])

    def test_conditional_success_statement_does_not_prove_success(self):
        self.assertEqual(positive_business_claims("验收通过后安排归档"), set())
        self.assert_shared_rejects_conclusion("验收通过", [evidence("验收通过后安排归档")])

    def test_unreadable_source_rejected_at_independent_validator_boundary(self):
        fact = evidence("验收通过", source_read_state="unavailable")
        item = DraftField("result", extractive_text((fact,)), (fact.evidence_id,))
        issues = validate_document(profile(), request(), (item,), (FieldResolution("result", (fact,)),))
        self.assertTrue(any(issue.code == "evidence_source_unavailable" and issue.severity == "error" for issue in issues))

    def test_partial_source_retains_coverage_warning(self):
        fact = evidence("验收通过", source_read_state="partial")
        item = DraftField("result", extractive_text((fact,)), (fact.evidence_id,))
        issues = validate_document(profile(), request(), (item,), (FieldResolution("result", (fact,)),))
        self.assertTrue(any(issue.code == "evidence_source_partial" and issue.severity == "warning" for issue in issues))


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.base = document(fields=(
            DraftField("background", "原背景", ("E1",)),
            DraftField("progress", "原进度", ("E2",)),
        ))

    def proposal(self, **changes):
        return replace(self.base, revision=self.base.revision + 1, **changes)

    def test_only_requested_field_changes_and_result_needs_revalidation(self):
        new = self.proposal(fields=(DraftField("background", "模型重写背景", ("E1",)), DraftField("progress", "新进度", ("E3",))), snapshot_id="snapshot2", snapshot_hash="hash2")
        plan = plan_revision(self.base, self.base, new, ["progress"], expected_current_revision=1)
        self.assertEqual(plan.merged.fields[0].text, "原背景")
        self.assertEqual(plan.merged.fields[1].text, "新进度")
        self.assertEqual(plan.ignored_field_ids, ("background",))
        self.assertEqual(plan.merged.snapshot_id, "snapshot1")
        self.assertEqual(plan.proposed_snapshot_id, "snapshot2")
        self.assertTrue(plan.requires_validation)
        self.assertEqual(plan.merged.state, "draft_with_gaps")

    def test_human_rewording_survives_regeneration(self):
        current = replace(self.base, revision=2, fields=(replace(self.base.fields[0], text="人工背景", origin="human"), self.base.fields[1]), human_modified_fields=("background",))
        proposed = self.proposal(fields=(replace(self.base.fields[0], text="新背景"), self.base.fields[1]))
        plan = plan_revision(self.base, current, proposed, ["background"], expected_current_revision=2)
        self.assertEqual(plan.merged.fields[0].text, "人工背景")
        self.assertEqual(plan.conflicts[0].code, "human_content_protected")
        self.assertEqual(plan.merged.state, "draft_with_gaps")

    def test_parallel_changes_to_same_field_are_not_overwritten(self):
        current = replace(self.base, revision=2, fields=(self.base.fields[0], replace(self.base.fields[1], text="同事新进度")))
        proposed = self.proposal(fields=(self.base.fields[0], replace(self.base.fields[1], text="机器人新进度")))
        plan = plan_revision(self.base, current, proposed, ["progress"], expected_current_revision=2)
        self.assertEqual(plan.merged.fields[1].text, "同事新进度")
        self.assertEqual(plan.conflicts[0].code, "concurrent_field_change")

    def test_stale_live_revision_fails_before_plan(self):
        with self.assertRaises(RevisionConflict):
            plan_revision(self.base, replace(self.base, revision=2), self.proposal(), ["progress"], expected_current_revision=1)

    def test_candidate_requires_explicit_base_revision(self):
        with self.assertRaises(RevisionConflict):
            plan_revision(self.base, self.base, replace(self.base, revision=7), ["progress"], expected_current_revision=1)

    def test_cross_project_update_rejected(self):
        with self.assertRaises(RevisionConflict):
            plan_revision(self.base, self.base, self.proposal(project_id="P2"), ["progress"], expected_current_revision=1)

    def test_template_change_requires_explicit_migration(self):
        with self.assertRaises(RevisionConflict):
            plan_revision(self.base, self.base, self.proposal(template_revision="2"), ["progress"], expected_current_revision=1)

    def test_same_template_field_deletion_also_requires_migration(self):
        with self.assertRaises(RevisionConflict):
            plan_revision(self.base, self.base, self.proposal(fields=(self.base.fields[1],)), ["progress"], expected_current_revision=1)

    def test_identical_proposal_is_no_op(self):
        plan = plan_revision(self.base, self.base, self.proposal(), ["progress"], expected_current_revision=1)
        self.assertEqual(plan.merged, self.base)
        self.assertFalse(plan.requires_validation)

    def test_published_document_cannot_be_mutated_by_draft_api(self):
        current = replace(self.base, state="approved")
        with self.assertRaises(RevisionConflict):
            plan_revision(self.base, current, self.proposal(), ["progress"], expected_current_revision=1)

    def test_explicit_migration_adds_field_without_silently_approving(self):
        old = profile()
        new = replace(profile(revision="2"), fields=(*old.fields, replace(old.fields[0], field_id="handover", fact_keys=("owner",), label="移交人")))
        base = document(template=old)
        proposed = document(template=new, revision=2, fields=(*base.fields, DraftField("handover", "负责人：工程师甲", ("E2",))))
        plan = plan_template_migration(base, base, proposed, new, expected_current_revision=1, migration_ref="task:template-upgrade")
        self.assertEqual(plan.merged.template_revision, "2")
        self.assertIn("handover", plan.affected_field_ids)
        self.assertEqual(plan.merged.state, "draft_with_gaps")
        self.assertTrue(plan.requires_validation)

    def test_migration_does_not_delete_human_content(self):
        old = profile()
        base = document(template=old)
        current = replace(base, fields=(replace(base.fields[0], text="人工验收口径", origin="human"),), revision=2, human_modified_fields=("result",))
        new = replace(profile(revision="2"), fields=(replace(old.fields[0], field_id="summary"),))
        proposed = document(template=new, revision=2, fields=(DraftField("summary", "总结", ("E1",)),))
        plan = plan_template_migration(base, current, proposed, new, expected_current_revision=2, migration_ref="task:migrate", accepted_removed_field_ids=("result",))
        self.assertTrue(plan.conflicts)
        self.assertEqual(plan.merged.template_revision, "1")
        self.assertEqual(plan.merged.fields[0].text, "人工验收口径")
        self.assertEqual(plan.changes, ())


if __name__ == "__main__":
    unittest.main()
