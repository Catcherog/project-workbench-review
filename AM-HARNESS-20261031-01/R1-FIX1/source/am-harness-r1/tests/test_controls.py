import tempfile
import unittest
from pathlib import Path

from am_harness.controls import IngressController, parse_control
from am_harness.store import DurableStore, Scope, StoreError


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1000.0
        self.scope = Scope("tenant", "app", "owner", "chat", "thread")
        self.store = DurableStore(Path(self.tmp.name) / "runs.sqlite", clock=lambda: self.now)
        self.ops = []
        self.control = IngressController(self.store, authorize=lambda s, op: self.ops.append((s.key, op)))

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self, event="event", text="查项目进展"):
        return self.store.submit(self.scope, event, text, deadline=1100, expires_at=1300)

    def test_bare_cancel_and_compound_text_remain_original_semantics(self):
        for text in ("取消", "先别发", "取消这个", "告诉我如何停止当前任务", "停止当前任务并发送消息", "/cancel", "修改当前任务："):
            self.assertIsNone(parse_control(text))
        self.assertEqual(parse_control("更正当前任务：查看交期").replacement, "查看交期")

    def test_authenticated_cancel_without_worker_lock_and_duplicate(self):
        run = self.submit()
        lease = self.store.claim("worker")
        reply = self.control.handle(self.scope, "control", "停止当前任务")
        self.assertEqual(reply.status, "cancelled")
        self.assertEqual(self.store.lane_status()["state"], "active")
        again = self.control.handle(self.scope, "control", "停止当前任务")
        self.assertEqual(again.status, "already_handled")
        self.assertEqual(again.cancel_epoch, reply.cancel_epoch)
        self.assertFalse(self.store.finish(lease, result={"stale": True}))
        self.assertIsNone(self.store.get(self.scope, run.id).result)

    def test_noop_redelivery_cannot_cancel_a_later_task(self):
        reply = self.control.handle(self.scope, "before-task", "停止当前任务")
        self.assertEqual(reply.status, "no_active_run")
        run = self.submit()
        replay = self.control.handle(self.scope, "before-task", "停止当前任务")
        self.assertEqual(replay.status, "no_active_run")
        self.assertEqual(self.store.get(self.scope, run.id).state, "queued")

    def test_ambiguous_noop_stays_ambiguous_after_other_task_finishes(self):
        one, two = self.submit("1"), self.submit("2")
        reply = self.control.handle(self.scope, "control", "停止当前任务")
        self.assertEqual(reply.status, "clarification")
        self.store.cancel(self.scope, "other-cancel", two.id)
        replay = self.control.handle(self.scope, "control", "停止当前任务")
        self.assertEqual(replay.status, "clarification")
        self.assertEqual(self.store.get(self.scope, one.id).state, "queued")

    def test_revise_preserves_expiry_and_does_not_repeat(self):
        run = self.submit()
        self.now += 10
        reply = self.control.handle(self.scope, "steer", "更正当前任务：查询关键日期")
        updated = self.store.get(self.scope, run.id)
        self.assertEqual(updated.input_text, "查询关键日期")
        self.assertEqual(updated.expires_at, 1300)
        self.assertEqual(updated.deadline, 1130)
        self.assertEqual(reply.revision, 2)
        again = self.control.handle(self.scope, "steer", "更正当前任务：查询关键日期")
        self.assertEqual(again.revision, 2)
        with self.assertRaises(StoreError):
            self.control.handle(self.scope, "steer", "更正当前任务：发送消息")

    def test_scope_and_auth_are_checked_for_controls(self):
        run = self.submit()
        other = Scope("tenant", "app", "coworker", "chat", "thread")
        with self.assertRaises(StoreError):
            self.control.handle(other, "control", "取消任务 " + run.id)
        def deny(scope, operation):
            raise RuntimeError("AUTHORIZATION_DENIED")
        controller = IngressController(self.store, authorize=deny)
        with self.assertRaisesRegex(RuntimeError, "AUTHORIZATION_DENIED"):
            controller.handle(self.scope, "deny", "停止当前任务")
        self.assertEqual(self.store.get(self.scope, run.id).state, "queued")

    def test_multiple_tasks_can_revise_one_explicit_target(self):
        one,two=self.submit("one"),self.submit("two")
        clarification=self.control.handle(self.scope,"ambiguous","更正当前任务：新要求")
        self.assertIn("更正任务",clarification.text)
        reply=self.control.handle(self.scope,"specified","更正任务 "+two.id+"：新要求")
        self.assertEqual(reply.run_id,two.id)
        self.assertEqual(self.store.get(self.scope,one.id).revision,1)
        self.assertEqual(self.store.get(self.scope,two.id).input_text,"新要求")
