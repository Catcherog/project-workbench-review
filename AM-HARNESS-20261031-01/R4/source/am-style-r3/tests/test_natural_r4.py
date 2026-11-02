"""Independent boundary cases for the optional R4 natural-surface grammar."""
import copy
import unittest

from am_style.contracts import ContractError, SpeechFrame, StylePolicy
from am_style.natural import NaturalSurfaceVerifier
from am_style.render import make_frame, gap_unit
from am_style.verify import CompositeVerifier


def frame(**kwargs):
    return make_frame(binding={"turn_id": "r4-fixture", "scope_id": "synthetic",
        "outcome_hash": "a" * 64, "source_revision": "fixture-v1", "revision": 0, "cancel_epoch": 0},
        expires_at=2000000000, question="检查本轮结果", family="fixture", **kwargs)


def sent(obj="给顾工的通知", state="succeeded"):
    return {"id": "send", "kind": "send_message", "state": state, "object": obj,
            "receipt": {"id": "receipt-fixture", "operation_id": "op-fixture", "object_id": "message-fixture", "verified": True}}


class NaturalSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.v = CompositeVerifier(NaturalSurfaceVerifier())
        self.policy = StylePolicy(realization="free")

    def passes(self, f, text):
        return self.v.verify(f, text, self.policy).decision == "pass"

    def test_receipted_send_can_use_idiomatic_equivalent(self):
        f = frame(effects=[sent()])
        self.assertTrue(self.passes(f, "给顾工的通知已经发出去了。"))
        self.assertFalse(self.passes(f, "给赵工的通知已经发出去了。"))

    def test_failed_or_unknown_action_cannot_become_sent(self):
        for state in ["failed", "unknown", "pending"]:
            with self.subTest(state=state):
                self.assertFalse(self.passes(frame(effects=[sent(state=state)]), "给顾工的通知已经发出去了。"))

    def test_estimate_must_survive_owner_or_date_rephrase(self):
        f = frame(facts=[{"id": "date", "kind": "date", "subject": "验收", "value": "2026-12-17", "modality": "estimated"}])
        self.assertTrue(self.passes(f, "预计验收的时间为2026-12-17。"))
        self.assertFalse(self.passes(f, "验收的时间为2026-12-17。"))
        self.assertFalse(self.passes(f, "预计验收的时间为2026-12-18。"))

    def test_unverified_owner_does_not_lose_uncertainty(self):
        f = frame(facts=[{"id": "owner", "kind": "owner", "subject": "装配验证", "value": "顾工", "modality": "unverified"}])
        self.assertTrue(self.passes(f, "负责装配验证的是顾工，这点还没有确认。"))
        self.assertFalse(self.passes(f, "负责装配验证的是顾工。"))

    def test_global_negation_and_scope_removal_is_never_used(self):
        text = "仅样机阶段未完成，批量阶段的状态未知。"
        f = frame(facts=[{"id": "status", "value": text}])
        for altered in ["仅样机阶段完成，批量阶段的状态未知。", "未完成，批量阶段的状态未知。", "仅样机阶段未完成，批量阶段已经完成。"]:
            self.assertFalse(self.passes(f, altered))

    def test_additive_join_preserves_both_obligations(self):
        f = frame(facts=[{"id": "one", "value": "样机已经到了"}, {"id": "two", "value": "测试还没开始"}])
        self.assertTrue(self.passes(f, "样机已经到了，另外，测试还没开始。"))
        self.assertFalse(self.passes(f, "样机已经到了，因此测试还没开始。"))
        self.assertFalse(self.passes(f, "样机已经到了。"))

    def test_repetition_cannot_satisfy_a_second_obligation(self):
        f = frame(facts=[{"id": "one", "value": "项目甲未完成"}, {"id": "two", "value": "项目乙未完成"}])
        self.assertFalse(self.passes(f, "项目甲未完成。项目甲未完成。"))

    def test_current_time_is_not_inferred_from_a_bare_owner(self):
        f = frame(facts=[{"id": "owner", "kind": "owner", "subject": "演示工位", "value": "顾工"}])
        self.assertFalse(self.passes(f, "演示工位现在由顾工负责。"))

    def test_exact_preview_is_checked_before_free_surface(self):
        f = frame(effects=[sent()], previews=[{"id": "approval", "text": "批准正文：A\nB"}])
        self.assertTrue(self.passes(f, "给顾工的通知已经发出去了。批准正文：A\nB"))
        self.assertFalse(self.passes(f, "给顾工的通知已经发出去了。批准正文：AB"))

    def test_mismatched_provenance_cannot_authorize_a_new_surface(self):
        f = frame(effects=[sent()]); data = f.data
        data["provenance"]["effects"][0]["object"] = "给赵工的通知"
        altered = SpeechFrame.freeze(data)
        self.assertFalse(self.passes(altered, "给赵工的通知已经发出去了。"))

    def test_cancel_does_not_claim_history_was_deleted(self):
        f = frame(effects=[{"id": "cancel", "kind": "cancel", "state": "cancelled", "object": "演示项目的提醒", "cancel_verified": True}],
                  facts=[{"id": "history", "value": "之前发出的消息会保留"}])
        self.assertTrue(self.passes(f, "演示项目的提醒后续处理已停止。之前发出的消息会保留。"))
        self.assertFalse(self.passes(f, "演示项目的提醒后续处理已停止。之前发出的消息已删除。"))

    def test_schedule_question_is_distinct_from_reminder_question(self):
        self.assertEqual(gap_unit({"id": "schedule", "slot": "start_and_duration", "object": "试验"})["variants"],
                         ["试验准备什么时候开始，预计需要多久？"])
        self.assertIn("提醒", gap_unit({"id": "remind", "slot": "reminder_time", "object": "试验"})["variants"][0])
        with self.assertRaises(ContractError):
            gap_unit({"id": "other", "slot": "invented", "object": "试验"})


if __name__ == "__main__":
    unittest.main()
