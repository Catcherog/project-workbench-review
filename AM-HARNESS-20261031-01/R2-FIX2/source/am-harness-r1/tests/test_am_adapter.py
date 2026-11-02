"""Cooperative cancellation against the actual patched AM engine."""
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from am_conversation.model import ScriptedModel
from am_conversation.store import ConversationStore
from am_conversation.tools import Tool, ToolRegistry, obj
from am_conversation.types import AccessContext, ModelTurn, ToolCall, canonical
from am_harness.am_adapter import AmAgentRunner, BindingError, LifecycleBinding, engine_event_id


def patched_module():
    path = Path(__file__).resolve().parents[2] / "am-conversation-r1/src/am_conversation/engine.py"
    name = "am_conversation.harness_binding_engine"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class ScopeFixture:
    key: str


@dataclass(frozen=True)
class FenceFixture:
    run_id: str
    scope_key: str
    revision: int = 1
    cancel_epoch: int = 0


@dataclass(frozen=True)
class RunFixture:
    id: str
    scope: ScopeFixture
    input_text: str
    event_id: str
    fence: FenceFixture
    revision: int = 1
    cancel_epoch: int = 0
    deadline: float = 1100
    expires_at: float = 1200


class AmAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self.tmp.name) / "am.sqlite", clock=lambda: 1000)
        self.ctx = AccessContext("t", "a", "owner", "chat", allowed_project_ids=frozenset({"p1"}), is_owner=True)
        self.registry = ToolRegistry()
        self.run = RunFixture("run-1", ScopeFixture(self.ctx.session_id), "查询合成资料", "incoming-1",
                              FenceFixture("run-1", self.ctx.session_id))
        self.module = patched_module()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_unbound_or_wrong_scope_fail_closed(self):
        hooks = LifecycleBinding(lambda fence: None)
        with self.assertRaisesRegex(BindingError, "HARNESS_UNBOUND_RUN"):
            hooks(self.ctx, "before_model", {})
        with hooks.bind(FenceFixture("r", "other")):
            with self.assertRaisesRegex(BindingError, "HARNESS_SCOPE_MISMATCH"):
                hooks(self.ctx, "before_model", {})
        self.assertIsNone(hooks.fence)

    def test_readonly_binding_cannot_enter_model_control_or_effect_phases(self):
        now = [1000.0]
        hooks = LifecycleBinding(lambda fence: self.fail("readonly must not forge durable fence"), clock=lambda: now[0])
        with hooks.bind_readonly(self.ctx, expires_at=2000):
            hooks(self.ctx, "before_fastpath_prepare", {})
            for phase in ("before_model", "before_control", "before_tool", "before_external"):
                with self.subTest(phase=phase), self.assertRaisesRegex(BindingError, "HARNESS_READONLY_PHASE_DENIED"):
                    hooks(self.ctx, phase, {})
            with self.assertRaisesRegex(BindingError, "HARNESS_SCOPE_MISMATCH"):
                hooks(replace(self.ctx, all_projects=True), "before_finish", {})
            now[0] = 1006
            with self.assertRaisesRegex(BindingError, "HARNESS_READONLY_EXPIRED"):
                hooks(self.ctx, "before_finish", {})
        self.assertIsNone(hooks.fence)

    def test_run_uses_revision_event_id_and_fresh_context_manager(self):
        phases, calls = [], []
        hooks = LifecycleBinding(lambda fence: phases.append(fence), observer=lambda event: calls.append(event))
        model = ScriptedModel([ModelTurn(text="合成回复")])
        agent = self.module.ConversationAgent(model, self.store, self.registry, lifecycle=hooks)
        active = []

        @contextmanager
        def resolve(snapshot):
            active.append("enter")
            try:
                yield self.ctx
            finally:
                active.append("exit")
        result = AmAgentRunner(agent, resolve, hooks, clock=lambda: 1000).run(self.run)
        self.assertEqual(["enter", "exit"], active)
        self.assertEqual("incoming-1", result["origin_event_id"])
        self.assertEqual("harness:run-1:v1", result["engine_event_id"])
        self.assertEqual(result["engine_event_id"], result["reply"]["event_id"])
        self.assertIn("after_model", [r["phase"] for r in calls])
        self.assertIsNone(hooks.fence)
        self.assertNotEqual(engine_event_id(self.run), engine_event_id(replace(self.run, revision=2)))

    def test_cancel_while_model_running_stops_returned_tool_and_reply(self):
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        used = []
        self.registry.register(Tool("fixture_read", "合成读取", obj({}),
                                    lambda ctx, args, event: used.append(event) or {"value": "synthetic"}))

        class BlockingModel:
            def complete(inner, messages, tools, *, request_id=""):
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("TEST_BLOCK_TIMEOUT")
                return ModelTurn(tool_calls=(ToolCall("call-1", "fixture_read", {}),))

        def guard(fence):
            if cancelled.is_set():
                raise BindingError("HARNESS_STALE_FENCE")
        hooks = LifecycleBinding(guard)
        agent = self.module.ConversationAgent(BlockingModel(), self.store, self.registry, lifecycle=hooks)
        runner = AmAgentRunner(agent, lambda run: self.ctx, hooks, clock=lambda: 1000)
        outputs, errors = [], []

        def execute():
            try:
                outputs.append(runner.run(self.run))
            except Exception as exc:
                errors.append(str(exc))
        worker = threading.Thread(target=execute)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            # No ConversationAgent striped lock is acquired by the control.
            cancelled.set()
            self.assertTrue(worker.is_alive())  # Cooperative cancel != abort.
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(["HARNESS_STALE_FENCE"], errors)
        self.assertEqual([], used)
        self.assertEqual([], outputs)
        self.assertFalse(any(m["role"] == "assistant" for m in self.store.history(self.ctx)))

    def test_after_tool_interrupt_not_swallowed_as_normal_tool_error(self):
        cancelled = False
        def read(ctx, args, event):
            nonlocal cancelled
            cancelled = True
            return {"synthetic": "value"}
        self.registry.register(Tool("fixture_read", "合成读取", obj({}), read))
        def guard(fence):
            if cancelled:
                raise BindingError("HARNESS_STALE_FENCE")
        hooks = LifecycleBinding(guard)
        model = ScriptedModel([ModelTurn(tool_calls=(ToolCall("c1", "fixture_read", {}),)), ModelTurn(text="不应执行")])
        agent = self.module.ConversationAgent(model, self.store, self.registry, lifecycle=hooks)
        with self.assertRaisesRegex(BindingError, "HARNESS_STALE_FENCE"):
            AmAgentRunner(agent, lambda run: self.ctx, hooks, clock=lambda: 1000).run(self.run)
        self.assertEqual(1, len(model.calls))

    def test_known_external_receipt_survives_post_execution_cancel(self):
        cancelled = False
        def send(ctx, args, event):
            nonlocal cancelled
            cancelled = True
            return {"status": "succeeded", "receipt_id": "fixture-receipt", "verified": True}
        self.registry.register(Tool("fixture_send", "合成发送", obj({}), send, "external", True,
                                    preview=lambda ctx, args: "合成预览"))
        action = self.store.create_action(self.ctx, tool_name="fixture_send", arguments={},
                                          project_id=None, preview="合成预览")
        self.store.claim_event(self.ctx, "preview", "准备合成预览")
        self.store.mark_presented(self.ctx, action["id"], expected_version=action["version"], event_id="preview")
        def guard(fence):
            if cancelled:
                raise BindingError("HARNESS_STALE_FENCE")
        hooks = LifecycleBinding(guard)
        agent = self.module.ConversationAgent(ScriptedModel([]), self.store, self.registry, lifecycle=hooks,
                    config=self.module.RuntimeConfig(allow_external_actions=True))
        confirmation = replace(self.run, input_text="确认执行")
        with self.assertRaisesRegex(BindingError, "HARNESS_STALE_FENCE"):
            AmAgentRunner(agent, lambda run: self.ctx, hooks, clock=lambda: 1000).run(confirmation)
        saved = self.store.get_action(self.ctx, action["id"])
        self.assertEqual("succeeded", saved["status"])
        self.assertEqual("fixture-receipt", saved["result"]["receipt_id"])

    def test_no_hooks_preserves_original_behavior(self):
        model = ScriptedModel([ModelTurn(text="普通路径")])
        agent = self.module.ConversationAgent(model, self.store, self.registry)
        reply = agent.handle(self.ctx, "plain-event", "普通请求")
        self.assertEqual("普通路径", reply.text)
        self.assertEqual(1, len(model.calls))

    def test_runner_rejects_unpatched_agent_and_expired_deadline(self):
        hooks = LifecycleBinding(lambda fence: None)
        agent = self.module.ConversationAgent(ScriptedModel([]), self.store, self.registry)
        with self.assertRaisesRegex(BindingError, "HARNESS_ENGINE_HOOKS_NOT_INSTALLED"):
            AmAgentRunner(agent, lambda run: self.ctx, hooks)
        agent.lifecycle = hooks
        with self.assertRaisesRegex(BindingError, "HARNESS_DEADLINE_EXPIRED"):
            AmAgentRunner(agent, lambda run: self.ctx, hooks, clock=lambda: 1200).run(self.run)


if __name__ == "__main__":
    unittest.main()
