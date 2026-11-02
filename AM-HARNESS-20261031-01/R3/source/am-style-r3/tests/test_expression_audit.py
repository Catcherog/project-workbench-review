"""Independent behavioral audit: receipts, semantic limits, fences and prompt parity.

No live model or business API is used. These checks do not prove general semantic
equivalence or production integration; free paraphrases remain review candidates.
"""
import json
import unittest

from am_style.contracts import ContractError, ModelResult, StylePolicy
from am_style.prompt import build_messages
from am_style.render import make_frame, render_canonical
from am_style.runtime import (TerminalPresenter, StaleFrame, StopUnconfirmed,
                              recheck_before_send)
from am_style.verify import BoundedVerifier


def frame(**changes):
    values = dict(
        binding={"turn_id": "test-turn", "scope_id": "test-scope",
                 "outcome_hash": "a" * 64, "source_revision": "rev1",
                 "revision": 1, "cancel_epoch": 0},
        expires_at=4102444800, question="项目甲的进展如何？", family="query",
        facts=[{"id": "progress", "kind": "progress", "subject": "项目甲",
                "value": "测试还没完成"}],
    )
    values.update(changes)
    return make_frame(**values)


def success(uid="first", obj="第一条需求", native="item-1", receipt="receipt-1"):
    return {"id": uid, "kind": "create_followup", "object": obj,
            "state": "succeeded", "receipt": {"id": receipt,
                "operation_id": "op-" + uid, "object_id": native, "verified": True}}


class Provider:
    def __init__(self, text, mutate=None, error=None):
        self.text, self.mutate, self.error = text, mutate, error
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if self.mutate:
            self.mutate()
        if self.error:
            raise self.error
        return ModelResult(json.dumps({"text": self.text}, ensure_ascii=False),
                           "fake", "fixed", 1.0)


class ExpressionAudit(unittest.TestCase):
    def test_success_requires_verified_bound_receipt(self):
        for update in ({"verified": False}, {"operation_id": ""}, {"object_id": ""}):
            with self.subTest(update=update):
                effect = success()
                effect["receipt"].update(update)
                with self.assertRaises(ContractError):
                    frame(facts=[], effects=[effect])

    def test_same_native_object_cannot_complete_two_distinct_goals(self):
        # Different receipt wrapper IDs must not hide the same native object.
        effects = [success(), success("second", "第二条需求", "item-1", "receipt-2")]
        with self.assertRaises(ContractError):
            frame(facts=[], effects=effects)

    def test_distinct_followups_can_group_and_unknown_cannot_join_success(self):
        first = success()
        second = success("second", "第二条需求", "item-2", "receipt-2")
        complete = frame(facts=[], effects=[first, second])
        result = render_canonical(complete)
        self.assertIn("两个需求", result)
        self.assertIn("第一条需求", result)
        self.assertIn("第二条需求", result)
        second = {"id": "second", "kind": "create_followup", "object": "第二条需求", "state": "unknown"}
        partial = frame(facts=[], effects=[first, second])
        text = render_canonical(partial)
        self.assertIn("第一条需求的跟进已建好", text)
        self.assertIn("第二条需求", text)
        self.assertIn("还没确认", text)
        self.assertNotIn("两个需求都", text)
        self.assertNotEqual(BoundedVerifier().verify(partial, result, StylePolicy()).decision, "pass")

    def test_failure_and_unknown_cannot_be_rephrased_as_success(self):
        for state in ("failed", "unknown"):
            with self.subTest(state=state):
                f = frame(facts=[], effects=[{"id": "send", "kind": "send_message",
                          "object": "通知", "state": state}])
                verdict = BoundedVerifier().verify(f, "通知已发送。", StylePolicy())
                self.assertNotEqual(verdict.decision, "pass")

    def test_retry_promise_requires_real_scheduled_job(self):
        effect = {"id": "send", "kind": "send_message", "object": "通知",
                  "state": "failed", "reason": "连接中断"}
        f = frame(facts=[], effects=[effect])
        self.assertNotIn("重试", render_canonical(f))
        self.assertNotEqual(BoundedVerifier().verify(
            f, render_canonical(f) + "我会再试。", StylePolicy()).decision, "pass")
        for retry in ({"verified": False, "job_id": "job1"}, {"verified": True}):
            with self.subTest(retry=retry), self.assertRaises(ContractError):
                frame(facts=[], effects=[dict(effect, retry=retry)])
        accepted = frame(facts=[], effects=[dict(effect, retry={"verified": True, "job_id": "job1"})])
        self.assertIn("已安排重试", render_canonical(accepted))

    def test_explicit_scope_and_time_metadata_are_preserved_or_refused(self):
        for key, qualifier in (("scope", "仅样机"), ("time_scope", "截至2026-11-02")):
            with self.subTest(key=key):
                fact = {"id": "f", "kind": "progress", "subject": "项目甲",
                        "value": "测试完成", key: qualifier}
                try:
                    f = frame(facts=[fact])
                except ContractError:
                    continue  # Unsupported typed semantics must fail closed.
                self.assertIn(qualifier, render_canonical(f))

    def test_estimate_qualifier_cannot_disappear(self):
        f = frame(facts=[{"id": "date", "kind": "date", "subject": "项目甲完成测试",
                          "value": "2026-11-20", "modality": "estimated"}])
        canonical = render_canonical(f)
        self.assertIn("预计", canonical)
        verdict = BoundedVerifier().verify(f, canonical.replace("预计", ""), StylePolicy())
        self.assertNotEqual(verdict.decision, "pass")

    def test_list_normalization_must_not_erase_semantic_numbers(self):
        # The dots are date/decimal punctuation, not a list marker.
        for original, changed in (("2026.11.20完成测试。", "2025.11.20完成测试。"),
                                  ("1.5%的样品尚未验收。", "2.5%的样品尚未验收。")):
            with self.subTest(original=original):
                f = frame(facts=[{"id": "f", "kind": "statement", "value": original}])
                self.assertEqual(BoundedVerifier().verify(f, original, StylePolicy()).decision, "pass")
                self.assertNotEqual(BoundedVerifier().verify(f, changed, StylePolicy()).decision, "pass")
        listed = frame(family="todos", facts=[
            {"id": "a", "kind": "statement", "value": "2026.11.20完成测试。"},
            {"id": "b", "kind": "statement", "value": "提交验收报告。"},
        ])
        self.assertEqual(BoundedVerifier().verify(
            listed, render_canonical(listed), StylePolicy()).decision, "pass")

    def test_sources_are_internal_by_default_and_exact_when_requested(self):
        sources = [{"label": "项目记录", "url": "https://example.test/source1"}]
        f = frame(source_links=sources)
        self.assertNotIn("https://", render_canonical(f))
        self.assertEqual(f.data["provenance"]["sources"], sources)
        shown = frame(source_links=sources, sources_requested=True)
        original = render_canonical(shown)
        self.assertIn(sources[0]["url"], original)
        self.assertEqual(BoundedVerifier().verify(shown, original, StylePolicy()).decision, "pass")
        self.assertEqual(BoundedVerifier().verify(
            shown, original.replace("source1", "source2"), StylePolicy()).decision, "reject")

    def test_unrecognized_free_text_is_not_auto_approved(self):
        f = frame()
        candidate = "测试没有完成，是供应商拖延造成的，我会催一下。"
        provider = Provider(candidate)
        p = TerminalPresenter(provider, policy=StylePolicy(realization="free"),
                              mode="shadow", monotonic=lambda: 10, wall_clock=lambda: 100)
        result = p.prepare(f, legacy_text="旧回复", guard=lambda _: None,
                           task_deadline_monotonic=30)
        self.assertEqual(result.text, "旧回复")
        self.assertFalse(result.metrics["adopted"])
        self.assertFalse(result.metrics["semantic_pass"])

    def test_guard_revocation_after_model_never_falls_back(self):
        active = {"allowed": True}
        f = frame()
        provider = Provider(render_canonical(f), mutate=lambda: active.update(allowed=False))
        def guard(_):
            if not active["allowed"]:
                raise StaleFrame("cancelled")
        p = TerminalPresenter(provider, mode="enforce", monotonic=lambda: 10, wall_clock=lambda: 100)
        with self.assertRaises(StaleFrame):
            p.prepare(f, legacy_text="旧回复", guard=guard, task_deadline_monotonic=30)
        self.assertEqual(len(provider.requests), 1)

    def test_expiration_during_model_never_falls_back(self):
        clock = {"wall": 100}
        f = frame(expires_at=110)
        provider = Provider(render_canonical(f), mutate=lambda: clock.update(wall=111))
        p = TerminalPresenter(provider, mode="enforce", monotonic=lambda: 10,
                              wall_clock=lambda: clock["wall"])
        with self.assertRaises(StaleFrame):
            p.prepare(f, legacy_text="旧回复", guard=lambda _: None, task_deadline_monotonic=30)

    def test_fastpath_and_exhausted_deadline_never_call_provider(self):
        f = frame()
        for kwargs in ({"fastpath": True, "task_deadline_monotonic": 30},
                       {"task_deadline_monotonic": 10.1},
                       {"task_deadline_monotonic": None}):
            with self.subTest(kwargs=kwargs):
                provider = Provider(render_canonical(f))
                p = TerminalPresenter(provider, mode="enforce", monotonic=lambda: 10, wall_clock=lambda: 100)
                result = p.prepare(f, legacy_text="旧回复", guard=lambda _: None, **kwargs)
                self.assertFalse(provider.requests)
                self.assertEqual(result.metrics["presentation_calls"], 0)
                self.assertFalse(result.metrics["adopted"])

    def test_shared_budget_and_shadow_count_are_separate_from_delivery(self):
        f = frame()
        provider = Provider(render_canonical(f))
        p = TerminalPresenter(provider, mode="shadow", generation_budget_s=8,
                              send_reserve_s=0.25, monotonic=lambda: 10, wall_clock=lambda: 100)
        result = p.prepare(f, legacy_text="旧回复", guard=lambda _: None, task_deadline_monotonic=12)
        self.assertAlmostEqual(provider.requests[0].timeout_seconds, 1.75)
        self.assertEqual(result.text, "旧回复")
        self.assertEqual(result.selected, "legacy")
        self.assertTrue(result.metrics["semantic_pass"])
        self.assertFalse(result.metrics["adopted"])
        self.assertEqual(result.delivery, "prepared")

    def test_late_expression_result_is_discarded_within_longer_task_budget(self):
        clock = {"mono": 10}
        f = frame()
        provider = Provider(render_canonical(f), mutate=lambda: clock.update(mono=19))
        p = TerminalPresenter(provider, mode="enforce", generation_budget_s=8,
                              monotonic=lambda: clock["mono"], wall_clock=lambda: 100)
        result = p.prepare(f, legacy_text="旧回复", guard=lambda _: None, task_deadline_monotonic=100)
        self.assertEqual(result.reason, "late_result_discarded")
        self.assertFalse(result.metrics["adopted"])
        self.assertEqual(len(provider.requests), 1)

    def test_unconfirmed_stop_propagates_and_does_not_release_into_fallback(self):
        f = frame()
        p = TerminalPresenter(Provider("", error=StopUnconfirmed("stop not acknowledged")),
                              mode="enforce", monotonic=lambda: 10, wall_clock=lambda: 100)
        with self.assertRaises(StopUnconfirmed):
            p.prepare(f, legacy_text="旧回复", guard=lambda _: None, task_deadline_monotonic=30)

    def test_send_recheck_rejects_expired_frame_even_if_binding_unchanged(self):
        # Simulate successful preparation before expiry, then actual wall time later.
        f = frame(expires_at=1)
        p = TerminalPresenter(mode="off", monotonic=lambda: 0, wall_clock=lambda: 0)
        prepared = p.prepare(f, legacy_text="旧回复", guard=lambda _: None,
                             task_deadline_monotonic=1)
        with self.assertRaises(StaleFrame):
            recheck_before_send(prepared, f, lambda _: None)

    def test_send_recheck_rejects_changed_frame_and_revocation(self):
        f = frame()
        p = TerminalPresenter(mode="off", monotonic=lambda: 10, wall_clock=lambda: 100)
        prepared = p.prepare(f, legacy_text="旧回复", guard=lambda _: None,
                             task_deadline_monotonic=30)
        newer = frame(question="项目乙的进展如何？")
        with self.assertRaises(StaleFrame):
            recheck_before_send(prepared, newer, lambda _: None)
        def revoked(_):
            raise StaleFrame("cancelled")
        with self.assertRaises(StaleFrame):
            recheck_before_send(prepared, f, revoked)

    def test_synthetic_training_prompt_matches_runtime_builder(self):
        from am_style.synthetic import generate_projected_seeds
        from am_style.contracts import SpeechFrame
        rows = generate_projected_seeds(StylePolicy(realization="free"))
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(record=row["id"]):
                f = SpeechFrame.freeze(row["frame"])
                policy = StylePolicy(**row["style_policy"])
                self.assertEqual(row["prompt"], build_messages(f, policy))
                self.assertFalse(row["training_approved"])
                provider = Provider(render_canonical(f))
                p = TerminalPresenter(provider, policy=policy, mode="shadow",
                                      monotonic=lambda: 10, wall_clock=lambda: 100)
                p.prepare(f, legacy_text="旧回复", guard=lambda _: None, task_deadline_monotonic=30)
                self.assertEqual(provider.requests[0].messages, row["prompt"])


if __name__ == "__main__":
    unittest.main()
