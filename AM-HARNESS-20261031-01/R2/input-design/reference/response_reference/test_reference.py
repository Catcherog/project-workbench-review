"""Reference contract tests: no real model, platform, database or consumer.

These tests intentionally expose that source references do not prove meaning.
"""
from dataclasses import replace
import json
import unittest
from .types import *
from .policy import ResponsePolicy
from .protocols import GuardRejected, ModelNotDispatched, ModelStoppedFailure, ModelStopUnknown
from .orchestrator import ResponseOrchestrator
from .validation import PlanError, parse_plan, validate_plan


def fixture(family=TaskFamily.READ):
    source = SourceStamp("s1", "content-v1", "acl-v1", "2026-10-31T12:00:00+08:00", None, "digest")
    claim = SemanticClaim("c1", "project-a", "test_state", "已开始测试", None,
        "positive", "asserted", "source_record", None, None, (), ("s1",), risk=Risk.LOW, required=True)
    fence = RunBinding("scope", "run", 1, 0, 1, "acl-v1")
    return OutcomeEnvelope("o1", family, fence, (), (claim,), (source,), (), ())


def candidate(e, text="测试已经开始了。"):
    return ResponsePlan(e.fingerprint, (TextSegment(text, ("c1",), "answer"),))


class Guard:
    def __init__(self): self.valid = True; self.phases = []
    def check(self, envelope, phase):
        self.phases.append(phase)
        if not self.valid: raise GuardRejected("SOURCE_OR_FENCE_CHANGED")


class Renderer:
    def __init__(self): self.calls = 0
    def render(self, envelope, *, reason):
        self.calls += 1
        return "\n".join([b.exact_text for b in envelope.protected] or ["现有记录显示，测试已开始。"])


class Model:
    def __init__(self, output, during=None): self.calls = 0; self.output = output; self.during = during
    def generate(self, envelope, **options):
        self.calls += 1
        if self.during: self.during()
        if isinstance(self.output, Exception): raise self.output
        return self.output


class Assessor:
    # Test double only. This is NOT a usable semantic evaluator.
    def assess(self, *args):
        return SemanticAssessment("accepted", "test-fixture-only")


class ResponseReferenceTests(unittest.TestCase):
    def setUp(self):
        self.e = fixture(); self.guard = Guard(); self.renderer = Renderer()
        self.policy = ResponsePolicy(mode="enforce", generated_families=frozenset({TaskFamily.READ}))

    def runner(self, model=None):
        return ResponseOrchestrator(policy=self.policy, guard=self.guard,
            host_renderer=self.renderer, model=model, semantic_assessor=Assessor(), clock=lambda: 10)

    def test_main_final_reuses_candidate_without_another_call(self):
        model = Model(AssertionError("no extra model"))
        r = self.runner(model).prepare(self.e, route=Route.MAIN_FINAL, deadline=30, existing_plan=candidate(self.e))
        self.assertEqual((r.origin, r.extra_model_calls, model.calls), ("main_model", 0, 0))

    def test_fast_read_never_opens_model_lane(self):
        model = Model(candidate(self.e))
        r = self.runner(model).prepare(self.e, route=Route.READONLY_FAST, deadline=30)
        self.assertEqual((r.origin, model.calls), ("host", 0))

    def test_durable_expression_calls_existing_model_once(self):
        model = Model(candidate(self.e))
        r = self.runner(model).prepare(self.e, route=Route.DURABLE_EXPRESSION, deadline=30)
        self.assertEqual((r.origin, r.extra_model_calls, model.calls), ("expression_model", 1, 1))

    def test_revocation_after_generation_never_returns_fallback(self):
        model = Model(candidate(self.e), during=lambda: setattr(self.guard, "valid", False))
        with self.assertRaises(GuardRejected):
            self.runner(model).prepare(self.e, route=Route.DURABLE_EXPRESSION, deadline=30)
        self.assertEqual(self.renderer.calls, 0)

    def test_revocation_with_model_error_is_not_swallowed(self):
        model = Model(ModelStoppedFailure("stopped"), during=lambda: setattr(self.guard, "valid", False))
        with self.assertRaises(GuardRejected):
            self.runner(model).prepare(self.e, route=Route.DURABLE_EXPRESSION, deadline=30)
        self.assertEqual(self.renderer.calls, 0)

    def test_fingerprint_mismatch_rejects_old_outcome(self):
        p = candidate(self.e); new = replace(self.e, fence=replace(self.e.fence, revision=2))
        with self.assertRaisesRegex(PlanError, "FINGERPRINT"):
            validate_plan(new, p, self.policy)

    def test_critical_claim_requires_locked_host_realization(self):
        claim = replace(self.e.claims[0], risk=Risk.CRITICAL)
        e = replace(self.e, claims=(claim,))
        with self.assertRaisesRegex(PlanError, "LOCKED"):
            validate_plan(e, candidate(e), self.policy)

    def test_locked_text_is_host_text_and_cannot_be_modified_in_json(self):
        block = ProtectedBlock("p1", "preview", "目标：测试群\n正文：请核对报告。")
        e = replace(self.e, claims=(), protected=(block,))
        p = ResponsePlan(e.fingerprint, (LockedSegment("p1"),))
        r = validate_plan(e, p, self.policy)
        self.assertEqual(r.text, block.exact_text)
        bad = '{"envelope_fingerprint":"x","segments":[{"kind":"locked","block_id":"p1","text":"改掉"}],"omitted_optional_claim_ids":[]}'
        with self.assertRaises(PlanError): parse_plan(bad)

    def test_missing_conflicting_source_is_rejected(self):
        c1 = replace(self.e.claims[0], conflicts_with=("c2",))
        c2 = replace(c1, claim_id="c2", value="尚未开始", polarity="negative", conflicts_with=("c1",), required=False)
        e = replace(self.e, claims=(c1,c2))
        with self.assertRaisesRegex(PlanError, "CONFLICT"):
            validate_plan(e, candidate(e), self.policy)

    def test_unknown_receipt_family_stays_host_only(self):
        e = replace(self.e, family=TaskFamily.UNKNOWN)
        m = Model(candidate(e))
        r = self.runner(m).prepare(e, route=Route.DURABLE_EXPRESSION, deadline=30)
        self.assertEqual((r.origin,m.calls),("host",0))

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(PlanError, "DUPLICATE"):
            parse_plan('{"envelope_fingerprint":"a","envelope_fingerprint":"b"}')

    def test_citations_do_not_prove_arbitrary_paraphrase_meaning(self):
        # Deliberately wrong paraphrase with a valid reference. Mechanical
        # checks alone cannot distinguish "started" from "finished" here.
        r = validate_plan(self.e, candidate(self.e,"测试已经全部完成。"), self.policy)
        self.assertFalse(r.semantic_equivalence_proven)
        self.assertEqual(r.locked_claim_coverage, ())
        self.assertEqual(r.declared_claim_coverage, ("c1",))

    def test_no_semantic_assessor_returns_canonical_current_outcome(self):
        runner = ResponseOrchestrator(policy=self.policy, guard=self.guard,
            host_renderer=self.renderer, clock=lambda: 10)
        r = runner.prepare(self.e, route=Route.MAIN_FINAL, deadline=30,
                           existing_plan=candidate(self.e, "测试已经全部完成。"))
        self.assertEqual(r.origin, "host")
        self.assertEqual(r.disposition, "semantic_assessment_unavailable")
        self.assertNotIn("全部完成", r.text)

    def test_stop_unknown_propagates_without_rendering(self):
        with self.assertRaises(ModelStopUnknown):
            self.runner(Model(ModelStopUnknown())).prepare(self.e, route=Route.DURABLE_EXPRESSION, deadline=30)
        self.assertEqual(self.renderer.calls, 0)

    def test_raw_timeout_does_not_imply_coordinator_stopped(self):
        with self.assertRaises(TimeoutError):
            self.runner(Model(TimeoutError())).prepare(self.e, route=Route.DURABLE_EXPRESSION, deadline=30)
        self.assertEqual(self.renderer.calls, 0)

    def test_predispatch_denial_is_zero_dispatched_calls(self):
        r = self.runner(Model(ModelNotDispatched())).prepare(self.e, route=Route.DURABLE_EXPRESSION, deadline=30)
        self.assertEqual((r.extra_model_calls, r.disposition), (0, "model_not_dispatched"))

    def test_fast_event_binding_has_no_fake_run(self):
        e = replace(self.e, fence=EventBinding("scope", "event-1", 1, "acl-v1"))
        r = self.runner().prepare(e, route=Route.READONLY_FAST, deadline=30)
        self.assertIsInstance(r.fence, EventBinding)
        self.assertFalse(hasattr(r.fence, "run_id"))

    def test_metadata_only_rejects_old_source_content(self):
        e = replace(self.e, family=TaskFamily.UNKNOWN, content_mode="metadata_only")
        with self.assertRaisesRegex(ValueError, "MUST_NOT_CARRY"):
            self.runner().prepare(e, route=Route.HOST_ONLY, deadline=30)
        self.assertEqual(self.renderer.calls, 0)

    def test_partial_work_unit_must_have_required_status_block(self):
        unit = WorkUnit("w1", "save_note", "note", "partial", unresolved=("write unknown",), effect="local")
        e = replace(self.e, work_units=(unit,))
        with self.assertRaisesRegex(ValueError, "WORK_UNIT_STATUS"):
            self.runner().prepare(e, route=Route.MAIN_FINAL, deadline=30, existing_plan=candidate(e))

    def test_important_gap_must_be_host_reported(self):
        e = replace(self.e, coverage_gaps=(CoverageGap("g1", "项目 B 尚无读取权限"),))
        with self.assertRaisesRegex(ValueError, "IMPORTANT_GAP"):
            self.runner().prepare(e, route=Route.MAIN_FINAL, deadline=30, existing_plan=candidate(e))

    def test_generated_plan_cannot_skip_unknown_work_unit(self):
        unit = WorkUnit("w1", "save_note", "note", "unknown", effect="local")
        block = ProtectedBlock("status", "receipt", "笔记保存结果尚未核实。", work_unit_ids=("w1",))
        e = replace(self.e, work_units=(unit,), protected=(block,))
        with self.assertRaisesRegex(PlanError, "REQUIRED_BLOCK"):
            validate_plan(e, candidate(e), self.policy)

    def test_host_renderer_must_keep_protected_order(self):
        b1 = ProtectedBlock("a", "control", "取消的是后续执行。", order=0)
        b2 = ProtectedBlock("b", "receipt", "已发送的消息仍保留。", order=1)
        e = replace(self.e, protected=(b2, b1))
        # Fixture renderer follows tuple order; a real renderer must obey order.
        with self.assertRaisesRegex(ValueError, "PROTECTED_BLOCK"):
            self.runner().prepare(e, route=Route.HOST_ONLY, deadline=30)

    def test_durable_expression_rejects_event_binding_before_model(self):
        e = replace(self.e, fence=EventBinding("scope", "event-1", 1, "acl-v1"))
        m = Model(candidate(e))
        with self.assertRaisesRegex(ValueError, "REQUIRES_RUN_BINDING"):
            self.runner(m).prepare(e, route=Route.DURABLE_EXPRESSION, deadline=30)
        self.assertEqual((m.calls, self.renderer.calls), (0, 0))

    def test_unhashable_json_intent_is_rejected_and_falls_back(self):
        for bad_intent in ([], {}):
            with self.subTest(intent=bad_intent):
                raw = json.dumps({"envelope_fingerprint": self.e.fingerprint,
                    "segments": [{"kind": "text", "text": "测试已经开始。", "claim_ids": ["c1"], "intent": bad_intent}],
                    "omitted_optional_claim_ids": []})
                with self.assertRaisesRegex(PlanError, "INVALID_TEXT_SEGMENT"):
                    parse_plan(raw)
                r = self.runner().prepare(self.e, route=Route.MAIN_FINAL, deadline=30, existing_plan=raw)
                self.assertEqual((r.origin, r.disposition), ("host", "candidate_mechanically_rejected"))

    def test_unhashable_typed_intent_is_plan_error(self):
        for bad_intent in ([], {}):
            with self.subTest(intent=bad_intent):
                p = ResponsePlan(self.e.fingerprint, (TextSegment("测试开始了。", ("c1",), bad_intent),))
                with self.assertRaisesRegex(PlanError, "INVALID_TYPED_TEXT_SEGMENT"):
                    validate_plan(self.e, p, self.policy)

    def test_schedule_has_explicit_family_and_preserves_host_preview(self):
        block = ProtectedBlock("schedule-preview", "preview", "提醒计划待确认：11月2日09:00发送。")
        e = replace(self.e, family=TaskFamily.SCHEDULE, claims=(), protected=(block,))
        m = Model(AssertionError("no scheduling model call"))
        r = self.runner(m).prepare(e, route=Route.HOST_ONLY, deadline=30)
        self.assertEqual((r.text, r.origin, m.calls), (block.exact_text, "host", 0))


if __name__ == "__main__": unittest.main()
