"""Independent behavioral review of the engine/store execution boundary.

Fixtures are synthetic. These checks do not claim that a real model or Feishu
transport has been exercised.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from am_conversation.engine import ConversationAgent, RuntimeConfig
from am_conversation.store import ConversationStore
from am_conversation.tools import Tool, ToolRegistry, obj, string
from am_conversation.types import AccessContext, AgentReply, ModelTurn, ToolCall


class ScriptModel:
    def __init__(self, *turns):
        self.turns = list(turns)

    def complete(self, messages, tools, *, request_id=""):
        if not self.turns:
            raise AssertionError("Unexpected extra model call")
        return self.turns.pop(0)


class EngineIndependentReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1000.0
        self.store = ConversationStore(Path(self.tmp.name) / "state.sqlite3", clock=lambda: self.now)
        self.ctx = AccessContext("tenant", "app", "owner", "dm", allowed_project_ids=frozenset({"P-17"}), is_owner=True)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def agent(self, model, registry, **config):
        return ConversationAgent(model, self.store, registry, config=RuntimeConfig(**config), clock=lambda: self.now)

    def registry(self, handler=None, preview=None):
        registry = ToolRegistry()
        registry.register(Tool("send_note", "发送一条测试提醒",
            obj({"project_id": string(256), "body": string(3000)}, ("project_id", "body")),
            handler or (lambda ctx, args, event: {"status": "succeeded", "verified": True, "receipt_id": "synthetic-receipt"}),
            effect="external", owner_only=True,
            preview=preview or (lambda ctx, args: "拟发送：" + args["body"])))
        return registry

    def test_unverified_completion_paraphrase_is_not_published(self):
        claim = "我已经把提醒发到项目群，台账也改好了。"
        agent = self.agent(ScriptModel(ModelTurn(text=claim)), ToolRegistry())
        reply = agent.handle(self.ctx, "e1", "帮我提醒一下工程师")
        self.assertNotEqual(claim, reply.text, "No external tool ran; paraphrased execution claims must not be treated as completed work")

    def test_verified_historical_status_is_not_confused_with_new_execution(self):
        registry = ToolRegistry()
        registry.register(Tool("read_report", "读取台账报告记录", obj({}),
            lambda ctx, args, event: {"project_id": "P-17", "summary": "台账记录：负责人已发送报告，当前待评审。", "observed_at": "2026-10-30T10:00:00+08:00"}))
        model = ScriptModel(ModelTurn(tool_calls=(ToolCall("read-1", "read_report", {}),)),
                            ModelTurn(text="台账记录：负责人已发送报告，当前待评审。"))
        reply = self.agent(model, registry).handle(self.ctx, "e2", "报告到哪一步了？")
        self.assertIn("负责人", reply.text)
        self.assertIn("待评审", reply.text)

    def test_recombined_status_sentence_is_conservatively_blocked(self):
        """Document the current UX limit; this is not semantic verification."""
        registry = ToolRegistry()
        registry.register(Tool("read_report", "读取台账分列记录", obj({}),
            lambda ctx, args, event: {"project_id": "P-17", "report_status": "负责人已发送报告", "next": "待评审"}))
        sentence = "台账记录：负责人已发送报告，当前待评审。"
        model = ScriptModel(ModelTurn(tool_calls=(ToolCall("read-1", "read_report", {}),)),
                            ModelTurn(text=sentence))
        reply = self.agent(model, registry).handle(self.ctx, "status-recombined", "报告到哪一步了？")
        self.assertNotEqual(sentence, reply.text)
        self.assertIn("没有本轮外部执行完成的凭据", reply.text)

    def test_first_person_quote_cannot_become_agents_completion_claim(self):
        registry = ToolRegistry()
        statement = "我已经把提醒发到项目群"
        registry.register(Tool("read_report", "读取工程师消息", obj({}),
            lambda ctx, args, event: {"project_id": "P-17", "engineer_quote": statement}))
        model = ScriptModel(ModelTurn(tool_calls=(ToolCall("read-1", "read_report", {}),)),
                            ModelTurn(text=statement + "。"))
        reply = self.agent(model, registry).handle(self.ctx, "first-person-quote", "帮我发提醒")
        self.assertNotEqual(statement + "。", reply.text)

    def test_boolean_or_blank_receipt_is_not_verified_completion(self):
        for receipt in (True, "   "):
            with self.subTest(receipt=receipt):
                registry = self.registry(handler=lambda ctx, args, event, value=receipt:
                    {"status": "succeeded", "verified": True, "receipt_id": value})
                agent = self.agent(ScriptModel(), registry, allow_external_actions=True)
                action = self.store.create_action(self.ctx, tool_name="send_note", arguments={"project_id": "P-17", "body": "请补报告"}, project_id="P-17", preview="拟发送：请补报告")
                event_id = "preview-" + action["id"]
                self.store.claim_event(self.ctx, event_id, "预览提醒")
                self.store.mark_presented(self.ctx, action["id"], expected_version=1, event_id=event_id)
                reply = agent.handle(self.ctx, "confirm-" + action["id"], "确认执行 " + action["id"] + " v1")
                self.assertEqual("execution_unknown", reply.status)
                self.assertEqual("unknown", self.store.get_action(self.ctx, action["id"])["status"])

    def test_complete_preview_respects_output_budget_without_silent_truncation(self):
        registry = self.registry(preview=lambda ctx, args: "拟发送完整内容：" + "合成正文" * 300)
        model = ScriptModel(ModelTurn(tool_calls=(ToolCall("send-1", "send_note", {"project_id": "P-17", "body": "请补报告"}),)),
                            ModelTurn(text="这份提醒较长，请先缩短正文或提供文档。"))
        agent = self.agent(model, registry, max_reply_chars=300)
        reply = agent.handle(self.ctx, "long-preview", "准备提醒")
        self.assertLessEqual(len(reply.text), 300)
        for action in self.store.list_actions(self.ctx):
            self.assertIsNone(action["presented_version"], "An incomplete preview must not be approvable")

    def test_delayed_delivery_ack_skips_expired_action_without_throwing(self):
        agent = self.agent(ScriptModel(), self.registry())
        self.store.claim_event(self.ctx, "preview-late", "准备提醒")
        action = self.store.create_action(self.ctx, tool_name="send_note", arguments={"project_id": "P-17", "body": "请补报告"}, project_id="P-17", preview="拟发送：请补报告", ttl_seconds=1)
        reply = AgentReply("preview-late", action["preview"] + "\n动作编号：" + action["id"] + " v1",
                           "needs_confirmation", pending_actions=(action["id"],))
        self.now += 2
        agent.acknowledge_presentation(self.ctx, reply)
        expired = self.store.get_action(self.ctx, action["id"])
        self.assertEqual("expired", expired["status"])
        self.assertIsNone(expired["presented_version"])


if __name__ == "__main__":
    unittest.main()
