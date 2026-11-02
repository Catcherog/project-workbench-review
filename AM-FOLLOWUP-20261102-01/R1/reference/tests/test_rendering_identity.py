import json
from pathlib import Path
import tempfile
import unittest

from am_followup.identity import BusinessIdentity, IdentityRegistry
from am_followup.rendering import (DisclosedFact, DraftSelection, RenderError,
                                  compose, describe_receipt, feishu_post, parse_selection)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "am.db")
        self.r = IdentityRegistry(self.path, "tenant_demo", "ou_owner")

    def tearDown(self):
        self.r.close()
        self.tmp.cleanup()

    def test_two_producers_link_to_one_business_task(self):
        task = self.r.register(BusinessIdentity("tenant_demo", "project_A", "test_01", "confirm_start", "round_1"))
        for producer, local in [("personal_assistant", "todo_4"), ("am", "item_9")]:
            self.r.bind_alias(producer, local, task, actor_id="ou_owner", decision_id="review_1")
        self.assertEqual(self.r.resolve("personal_assistant", "todo_4"), self.r.resolve("am", "item_9"))
        # Alias changes cannot silently move already-approved work.
        task2 = self.r.register(BusinessIdentity("tenant_demo", "project_A", "test_02", "confirm_start", "round_1"))
        with self.assertRaisesRegex(ValueError, "ALIAS_ALREADY_BOUND"):
            self.r.bind_alias("am", "item_9", task2, actor_id="ou_owner", decision_id="review_2")

    def test_incomplete_identity_and_untrusted_actor_cannot_promote(self):
        with self.assertRaises(ValueError):
            BusinessIdentity("tenant_demo", "", "unknown", "confirm_start", "round_1")
        task = self.r.register(BusinessIdentity("tenant_demo", "project_A", "test_01", "confirm_start", "round_1"))
        with self.assertRaisesRegex(ValueError, "OWNER_ONLY"):
            self.r.bind_alias("am", "item_9", task, actor_id="ou_imposter", decision_id="review_1")
        self.assertIsNone(self.r.resolve("am", "item_9"))

    def test_tenant_and_cycle_are_independent(self):
        a = BusinessIdentity("tenant_demo", "project_A", "test_01", "confirm_start", "round_1")
        b = BusinessIdentity("tenant_demo", "project_A", "test_01", "confirm_start", "round_2")
        self.assertNotEqual(self.r.register(a), self.r.register(b))
        other = IdentityRegistry(self.path, "tenant_other", "ou_owner")
        try:
            with self.assertRaisesRegex(ValueError, "TENANT_MISMATCH"):
                other.register(a)
            with self.assertRaisesRegex(ValueError, "UNKNOWN_CANONICAL_TASK"):
                other.bind_alias("am", "id", a.canonical_id, actor_id="ou_owner", decision_id="d")
        finally:
            other.close()


class GroundedDraftTests(unittest.TestCase):
    def fact(self, **kw):
        data = dict(fact_id="f1", text="样机已到仓", evidence_ref="msg/one",
                    evidence_version="v1", policy_version="p1",
                    allowed_audiences=("chat:oc_project",), authority="reported")
        data.update(kw)
        return DisclosedFact(**data)

    def test_question_does_not_infer_execution_from_arrival(self):
        draft = compose("示例项目", "测试准备", "chat:oc_project", "confirm_start",
                        [self.fact()], DraftSelection("confirm_start", ("f1",)))
        self.assertIn("目前收到的反馈是：样机已到仓", draft.body)
        self.assertIn("是否已经开始", draft.body)
        self.assertNotIn("测试已完成", draft.body)
        self.assertEqual(draft.dependencies, (("msg/one", "v1", "p1"),))

    def test_private_fact_not_transferred_to_group(self):
        private = self.fact(allowed_audiences=("user:ou_owner",))
        with self.assertRaisesRegex(RenderError, "FACT_NOT_DISCLOSABLE"):
            compose("示例项目", "发布", "chat:oc_project", "confirm_release",
                    [private], DraftSelection("confirm_release", ("f1",)))
        # A question without the private fact is possible once the project/action
        # titles themselves are approved for disclosure by the policy gate.
        draft = compose("示例项目", "发布", "chat:oc_project", "confirm_release")
        self.assertEqual(draft.fact_ids, ())
        self.assertNotIn(private.text, draft.body)

    def test_llm_cannot_change_purpose_or_smuggle_actions(self):
        with self.assertRaisesRegex(RenderError, "MODEL_CHANGED_PURPOSE"):
            compose("示例项目", "测试", "chat:oc_project", "confirm_start",
                    selection=DraftSelection("confirm_release"))
        for raw in [
            '{"purpose":"request_progress","fact_ids":[],"tone":"neutral","send":true}',
            '{"purpose":"request_progress","fact_ids":[],"tone":"neutral","tone":"warm"}',
            '{"purpose":"request_progress","fact_ids":["f","f"],"tone":"neutral"}',
        ]:
            with self.assertRaises(RenderError):
                parse_selection(raw)

    def test_mentions_are_structured_and_body_cannot_inject_all(self):
        result = feishu_post("请确认当前进展。", ("ou_engineer",))
        self.assertEqual(result["zh_cn"]["content"][0], [{"tag":"at","user_id":"ou_engineer"}])
        with self.assertRaises(RenderError):
            feishu_post('<at user_id="all">所有人</at>')
        with self.assertRaises(RenderError):
            feishu_post("请确认", ("all",))
        self.assertEqual(feishu_post("请确认")["zh_cn"]["content"][0][0]["tag"], "text")

    def test_uncertain_receipt_never_promises_sent_or_read(self):
        self.assertIn("尚未核实", describe_receipt("unknown"))
        self.assertNotIn("已发出", describe_receipt("unknown"))
        self.assertNotIn("已读", describe_receipt("confirmed", "om_demo"))
        self.assertNotIn("已发出", describe_receipt("confirmed"))

    def test_unconfirmed_fact_does_not_become_assertion(self):
        with self.assertRaises(RenderError):
            self.fact(authority="model_guess")


if __name__ == "__main__":
    unittest.main()

