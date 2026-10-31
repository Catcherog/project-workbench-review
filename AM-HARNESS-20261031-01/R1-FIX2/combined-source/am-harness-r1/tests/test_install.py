"""Phase 1 installation using actual LegacyBridge and its original fixture ports.

FakeService/OriginalStore are imported from the fixed AM regression suite.
There is no live Feishu send or live Qwen call in these tests.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from am_conversation import legacy
from am_harness.am_adapter import LifecycleBinding
from am_harness.install import InstallationError, install_fastpath_only


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class InstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load_module("am_harness_install_legacy_fixture",
                                  ROOT.parent / "am-conversation-r1/tests/test_legacy.py")
        cls.engine = load_module("am_conversation.harness_install_engine",
                         ROOT.parent / "am-conversation-r1/src/am_conversation/engine.py")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = self.fixture.FakeService(Path(self.tmp.name))
        with patch.object(legacy, "ConversationAgent", self.engine.ConversationAgent):
            self.bridge = legacy.LegacyConversationBridge(self.service, {"enabled": True})

    def tearDown(self):
        self.bridge.close()
        self.service.s.conn.close()
        self.tmp.cleanup()

    def test_real_bridge_process_uses_zero_model_calls_and_original_outbox(self):
        model = self.bridge.agent.model
        provider = self.service.g.provider
        installed = install_fastpath_only(self.bridge)
        self.assertIs(self.bridge.agent.model, model)
        self.assertIs(self.service.g.provider, provider)
        self.assertIsNone(self.bridge.agent.lifecycle)
        row = self.service.inbox(text="需求1的进展", event="fast-install-event")
        outbox_id = self.bridge.process(row)
        output = self.service.s.rows("SELECT * FROM outbox WHERE id=?", (outbox_id,))[0]
        self.assertIn("测试资料待整理", output["body"])
        self.assertIn("未独立核验", output["body"])
        self.assertEqual([], provider.calls)
        self.assertEqual(1, len(self.service.s.rows("SELECT * FROM am_conversation_outputs")))
        self.assertEqual(outbox_id, self.bridge.process(row))
        self.assertEqual(1, len(self.service.s.rows("SELECT * FROM outbox")))
        self.assertTrue(installed.restore())
        self.assertIsNone(self.bridge.agent.fastpath)
        next_row = self.service.inbox(text="需求1的进展", event="ordinary-after-restore")
        self.bridge.process(next_row)
        self.assertEqual(1, len(provider.calls))
        self.assertFalse(installed.restore())

    def test_restore_preserves_preexisting_callback(self):
        previous = lambda ctx, event, text: None
        self.bridge.agent.fastpath = previous
        installed = install_fastpath_only(self.bridge, focus_path=Path(self.tmp.name) / "custom-focus.sqlite")
        self.assertIsNot(previous, self.bridge.agent.fastpath)
        self.assertTrue(installed.restore())
        self.assertIs(previous, self.bridge.agent.fastpath)

    def test_restore_does_not_clobber_parallel_callback_change(self):
        installed = install_fastpath_only(self.bridge)
        other = lambda ctx, event, text: None
        self.bridge.agent.fastpath = other
        with self.assertRaisesRegex(InstallationError, "HARNESS_INSTALL_CALLBACK_CHANGED"):
            installed.restore()
        self.assertIs(other, self.bridge.agent.fastpath)

    def test_restore_does_not_touch_replaced_agent(self):
        installed = install_fastpath_only(self.bridge)
        original = self.bridge.agent
        replacement = SimpleNamespace(fastpath="other")
        self.bridge.agent = replacement
        try:
            with self.assertRaisesRegex(InstallationError, "HARNESS_INSTALL_AGENT_CHANGED"):
                installed.restore()
            self.assertEqual("other", replacement.fastpath)
        finally:
            self.bridge.agent = original
        self.assertTrue(installed.restore())

    def test_unknown_disabled_or_unpatched_bridge_rejected(self):
        with self.assertRaisesRegex(InstallationError, "HARNESS_INSTALL_BRIDGE_INVALID"):
            install_fastpath_only(SimpleNamespace(enabled=True, agent=self.bridge.agent))
        self.bridge.enabled = False
        with self.assertRaisesRegex(InstallationError, "HARNESS_INSTALL_BRIDGE_INVALID"):
            install_fastpath_only(self.bridge)
        self.bridge.enabled = True
        original = self.bridge.agent
        self.bridge.agent = SimpleNamespace(fastpath=None, lifecycle=None)
        try:
            with self.assertRaisesRegex(InstallationError, "HARNESS_INSTALL_ENGINE_UNPATCHED"):
                install_fastpath_only(self.bridge)
        finally:
            self.bridge.agent = original

    def test_existing_lifecycle_is_never_relaxed_for_phase_one(self):
        hooks = LifecycleBinding(lambda fence: None)
        self.bridge.agent.lifecycle = hooks
        with self.assertRaisesRegex(InstallationError, "HARNESS_INSTALL_LIFECYCLE_PRESENT"):
            install_fastpath_only(self.bridge)
        self.assertIs(hooks, self.bridge.agent.lifecycle)
        self.assertTrue(hooks.strict_bound)
        self.assertIsNone(self.bridge.agent.fastpath)


if __name__ == "__main__":
    unittest.main()
