"""Behavioral checks for durable conversation state and action safety."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest

from am_conversation.store import ConversationStore, HISTORY_RETENTION
from am_conversation.types import AccessContext, ConversationError


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.sqlite3"
        self.now = 1000.0
        self.store = ConversationStore(self.path, clock=lambda: self.now)
        self.ctx = AccessContext("tenant-a", "app-a", "owner-a", "dm-a", "thread-a",
                                 frozenset({"P-17", "P-20"}), is_owner=True)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def error(self, code, fn, *args, **kwargs):
        with self.assertRaisesRegex(ConversationError, "^" + code + "$"):
            fn(*args, **kwargs)

    def action(self, ctx=None, *, ttl=1800):
        ctx = ctx or self.ctx
        return self.store.create_action(ctx, tool_name="send_reminder",
                                       arguments={"project_id": "P-17", "text": "请补报告"},
                                       project_id="P-17", preview="发给测试群：请补报告", ttl_seconds=ttl)

    def presented(self, ctx=None, *, ttl=1800):
        ctx = ctx or self.ctx
        action = self.action(ctx, ttl=ttl)
        event_id = "preview-" + action["id"]
        self.store.claim_event(ctx, event_id, "准备提醒")
        return self.store.mark_presented(ctx, action["id"], expected_version=1, event_id=event_id)

    def approved(self):
        action = self.presented()
        return self.store.approve_action(self.ctx, action["id"], expected_version=1, digest=action["digest"])

    def test_event_replay_is_persistent_and_does_not_duplicate_history(self):
        self.assertEqual("claimed", self.store.claim_event(self.ctx, "e1", "17进度？")["state"])
        self.assertEqual("in_progress", self.store.claim_event(self.ctx, "e1", "17进度？")["state"])
        reply = {"event_id": "e1", "text": "报告待提交", "status": "answered"}
        self.store.finish_event(self.ctx, "e1", reply)
        self.store.finish_event(self.ctx, "e1", reply)
        second = ConversationStore(self.path, clock=lambda: self.now)
        try:
            self.assertEqual({"state": "completed", "reply": reply}, second.claim_event(self.ctx, "e1", "17进度？"))
            self.assertEqual(2, len(second.history(self.ctx)))
        finally:
            second.close()

    def test_same_event_cannot_change_body_or_scope(self):
        self.store.claim_event(self.ctx, "e1", "第一条")
        self.error("EVENT_CONTENT_MISMATCH", self.store.claim_event, self.ctx, "e1", "另一条")
        for field, value in (("actor_id", "other"), ("chat_id", "other"), ("thread_id", "other")):
            self.error("EVENT_SCOPE_MISMATCH", self.store.claim_event, replace(self.ctx, **{field: value}), "e1", "第一条")
        other_tenant = replace(self.ctx, tenant_id="tenant-b")
        self.assertEqual("claimed", self.store.claim_event(other_tenant, "e1", "另一租户")["state"])
        self.assertEqual("另一租户", self.store.history(other_tenant)[0]["content"])

    def test_authorization_change_hides_history_and_blocks_cached_reply(self):
        self.store.claim_event(self.ctx, "e1", "查20")
        self.store.finish_event(self.ctx, "e1", {"text": "20项目敏感进度"})
        revoked = replace(self.ctx, allowed_project_ids=frozenset({"P-17"}))
        self.assertEqual([], self.store.history(revoked))
        self.error("EVENT_AUTHORIZATION_CHANGED", self.store.claim_event, revoked, "e1", "查20")
        self.store.claim_event(revoked, "e2", "查17")
        self.assertEqual([{"role": "user", "content": "查17"}], self.store.history(revoked))

    def test_each_scope_dimension_isolates_history_tasks_and_actions(self):
        self.store.append_message(self.ctx, "assistant", "本会话内容")
        task = self.store.create_task(self.ctx, project_id="P-17", title="报告")
        action = self.action()
        for field in ("tenant_id", "app_id", "actor_id", "chat_id", "thread_id"):
            other = replace(self.ctx, **{field: "different"})
            self.assertEqual([], self.store.history(other), field)
            self.assertEqual([], self.store.list_tasks(other), field)
            self.assertEqual([], self.store.list_actions(other), field)
            self.error("TASK_NOT_FOUND", self.store.get_task, other, task["id"])
            self.error("ACTION_NOT_FOUND", self.store.get_action, other, action["id"])

    def test_failed_event_is_not_implicitly_retried(self):
        self.store.claim_event(self.ctx, "e1", "发送")
        self.store.fail_event(self.ctx, "e1", "TIMEOUT")
        self.assertEqual({"state": "unknown", "reply": None}, self.store.claim_event(self.ctx, "e1", "发送"))
        self.error("EVENT_NOT_PROCESSING", self.store.finish_event, self.ctx, "e1", {"text": "后来结果"})

    def test_completed_event_cannot_be_replaced(self):
        self.store.claim_event(self.ctx, "e1", "查看")
        self.store.finish_event(self.ctx, "e1", {"text": "原结果"})
        self.error("EVENT_ALREADY_COMPLETED", self.store.finish_event, self.ctx, "e1", {"text": "其他结果"})
        self.store.fail_event(self.ctx, "e1", "AFTER_COMPLETION")
        self.assertEqual("原结果", self.store.claim_event(self.ctx, "e1", "查看")["reply"]["text"])

    def test_history_is_bounded_but_tasks_survive_restarts_and_days(self):
        task = self.store.create_task(self.ctx, project_id="P-17", title="等待报告", status="waiting")
        for i in range(HISTORY_RETENTION + 8):
            self.store.append_message(self.ctx, "user", str(i))
        self.assertEqual(HISTORY_RETENTION, len(self.store.history(self.ctx, HISTORY_RETENTION)))
        self.assertEqual("8", self.store.history(self.ctx, HISTORY_RETENTION)[0]["content"])
        self.now += 8 * 86400
        self.store.close()
        self.store = ConversationStore(self.path, clock=lambda: self.now)
        self.assertEqual("waiting", self.store.get_task(self.ctx, task["id"])["status"])

    def test_parallel_projects_do_not_overwrite_each_other(self):
        a = self.store.create_task(self.ctx, project_id="P-17", title="17报告", due_at="2026-11-03T10:00:00+08:00")
        b = self.store.create_task(self.ctx, project_id="P-20", title="20报告", due_at="2026-11-02T15:00:00+08:00")
        self.store.update_task(self.ctx, a["id"], expected_version=1, changes={"due_at": "2026-11-04T10:00:00+08:00"})
        self.assertEqual(b["due_at"], self.store.get_task(self.ctx, b["id"])["due_at"])
        self.assertEqual(1, len(self.store.list_tasks(self.ctx, project_id="P-20")))

    def test_task_change_requires_current_version_and_valid_fields(self):
        task = self.store.create_task(self.ctx, project_id="P-17", title="报告")
        self.store.update_task(self.ctx, task["id"], expected_version=1, changes={"details": "工程师报告完成，尚未验收"})
        self.error("VERSION_CONFLICT", self.store.update_task, self.ctx, task["id"], expected_version=1, changes={"status": "closed"})
        self.error("INVALID_TASK_CHANGES", self.store.update_task, self.ctx, task["id"], expected_version=2, changes={"project_id": "P-20"})
        self.assertEqual("open", self.store.get_task(self.ctx, task["id"])["status"])

    def test_task_creation_from_same_event_is_idempotent_but_allows_multiple_tasks(self):
        self.store.claim_event(self.ctx, "e1", "17和20都要跟进")
        a = self.store.create_task(self.ctx, project_id="P-17", title="跟进", event_id="e1")
        repeated = self.store.create_task(self.ctx, project_id="P-17", title="跟进", event_id="e1")
        b = self.store.create_task(self.ctx, project_id="P-20", title="跟进", event_id="e1")
        self.assertEqual(a["id"], repeated["id"])
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(2, len(self.store.list_tasks(self.ctx)))

    def test_raw_messages_expire_but_explicit_work_notes_survive(self):
        ctx=replace(self.ctx,content_expires_at=self.now+60)
        self.store.claim_event(ctx,'expiring-event','仅临时对话')
        self.store.finish_event(ctx,'expiring-event',{'text':'临时回答'})
        note=self.store.create_task(ctx,project_id='P-17',title='明确要求保留的工作事项')
        action=self.action(ctx,ttl=1800)
        self.now+=61
        self.assertEqual([],self.store.history(ctx))
        self.store.cleanup_messages()
        self.assertEqual(note['title'],self.store.get_task(ctx,note['id'])['title'])
        self.assertEqual('',self.store.get_action(ctx,action['id'])['preview'])
        self.error('EVENT_CONTENT_EXPIRED',self.store.claim_event,ctx,'expiring-event','仅临时对话')

    def test_closed_tasks_are_excluded_until_requested(self):
        task = self.store.create_task(self.ctx, project_id="P-17", title="报告")
        self.store.update_task(self.ctx, task["id"], expected_version=1, changes={"status": "closed"})
        self.assertEqual([], self.store.list_tasks(self.ctx))
        self.assertEqual(1, len(self.store.list_tasks(self.ctx, include_closed=True)))

    def test_project_revocation_applies_to_existing_tasks_and_actions(self):
        task = self.store.create_task(self.ctx, project_id="P-17", title="报告")
        action = self.action()
        revoked = replace(self.ctx, allowed_project_ids=frozenset({"P-20"}))
        self.assertEqual([], self.store.list_tasks(revoked))
        self.assertEqual([], self.store.list_actions(revoked))
        self.error("PROJECT_FORBIDDEN", self.store.get_task, revoked, task["id"])
        self.error("PROJECT_FORBIDDEN", self.store.get_action, revoked, action["id"])
        self.error("PROJECT_FORBIDDEN", self.store.create_task, revoked, project_id="P-17", title="越权")

    def test_due_date_must_be_absolute_with_timezone(self):
        for due in ("明天上午", "2026-11-03", "2026-11-03T10:00:00"):
            with self.assertRaises(ConversationError):
                self.store.create_task(self.ctx, project_id="P-17", title="报告", due_at=due)
        self.assertEqual([], self.store.list_tasks(self.ctx))
        task = self.store.create_task(self.ctx, project_id="P-17", title="报告", due_at="2026-11-03T02:00:00Z")
        self.assertEqual("2026-11-03T02:00:00+00:00", task["due_at"])

    def test_approval_requires_owner_and_current_shown_content(self):
        action = self.action()
        self.error("ACTION_NOT_PRESENTED", self.store.approve_action, self.ctx, action["id"], expected_version=1, digest=action["digest"])
        member = replace(self.ctx, is_owner=False)
        self.error("OWNER_REQUIRED", self.store.approve_action, member, action["id"], expected_version=1, digest=action["digest"])
        self.store.claim_event(self.ctx, "p1", "请预览")
        self.store.mark_presented(self.ctx, action["id"], expected_version=1, event_id="p1")
        self.error("ACTION_DIGEST_MISMATCH", self.store.approve_action, self.ctx, action["id"], expected_version=1, digest="wrong")
        self.assertEqual("draft", self.store.get_action(self.ctx, action["id"])["status"])

    def test_preview_event_must_belong_to_same_scope(self):
        action = self.action()
        other = replace(self.ctx, chat_id="another-dm")
        self.store.claim_event(other, "foreign-event", "预览")
        self.error("EVENT_SCOPE_MISMATCH", self.store.mark_presented, self.ctx, action["id"], expected_version=1, event_id="foreign-event")

    def test_edit_invalidates_approval_and_old_digest(self):
        action = self.approved()
        changed = self.store.revise_action(self.ctx, action["id"], expected_version=1,
                                          arguments={"project_id": "P-17", "text": "请明天补报告"},
                                          preview="发给测试群：请明天补报告")
        self.assertEqual((2, "draft", None), (changed["version"], changed["status"], changed["presented_version"]))
        self.assertNotEqual(action["digest"], changed["digest"])
        self.assertFalse(self.store.begin_execution(self.ctx, action["id"], expected_version=2)["claimed"])
        self.error("VERSION_CONFLICT", self.store.approve_action, self.ctx, action["id"], expected_version=1, digest=action["digest"])
        self.error("ACTION_NOT_PRESENTED", self.store.approve_action, self.ctx, action["id"], expected_version=2, digest=changed["digest"])

    def test_expired_approval_cannot_execute(self):
        action = self.presented(ttl=10)
        self.store.approve_action(self.ctx, action["id"], expected_version=1, digest=action["digest"])
        self.now += 11
        result = self.store.begin_execution(self.ctx, action["id"], expected_version=1)
        self.assertFalse(result["claimed"])
        self.assertEqual("expired", result["action"]["status"])

    def test_concurrent_execution_has_one_winner(self):
        action = self.approved()
        barrier = threading.Barrier(4)
        def attempt(_):
            barrier.wait()
            return self.store.begin_execution(self.ctx, action["id"], expected_version=1)["claimed"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(attempt, range(4)))
        self.assertEqual(1, sum(outcomes))
        self.assertEqual("executing", self.store.get_action(self.ctx, action["id"])["status"])

    def test_concurrent_task_update_has_one_winner(self):
        task = self.store.create_task(self.ctx, project_id="P-17", title="报告")
        barrier = threading.Barrier(2)
        def attempt(value):
            barrier.wait()
            try:
                self.store.update_task(self.ctx, task["id"], expected_version=1, changes={"details": value})
                return "won"
            except ConversationError as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, ["A", "B"]))
        self.assertEqual(["VERSION_CONFLICT", "won"], sorted(outcomes))

    def test_constructor_does_not_recover_another_workers_action(self):
        action = self.approved()
        self.store.begin_execution(self.ctx, action["id"], expected_version=1)
        other = ConversationStore(self.path, clock=lambda: self.now)
        try:
            self.assertEqual("executing", other.get_action(self.ctx, action["id"])["status"])
            counts = other.recover_inflight()
            self.assertEqual(1, counts["actions"])
            self.assertFalse(other.begin_execution(self.ctx, action["id"], expected_version=1)["claimed"])
        finally:
            other.close()

    def test_unknown_action_never_reexecutes_but_verified_result_can_resolve_it(self):
        action = self.approved()
        self.store.begin_execution(self.ctx, action["id"], expected_version=1)
        self.store.finish_execution(self.ctx, action["id"], status="unknown", result={"code": "TIMEOUT"})
        self.assertFalse(self.store.begin_execution(self.ctx, action["id"], expected_version=1)["claimed"])
        self.error("ACTION_ALREADY_STARTED_OR_CLOSED", self.store.cancel_action, self.ctx, action["id"], expected_version=1)
        final = self.store.finish_execution(self.ctx, action["id"], status="succeeded", result={"message_id": "synthetic-message"})
        self.assertEqual("succeeded", final["status"])
        self.assertFalse(self.store.begin_execution(self.ctx, action["id"], expected_version=1)["claimed"])

    def test_cancellation_only_stops_unstarted_action(self):
        action = self.approved()
        cancelled = self.store.cancel_action(self.ctx, action["id"], expected_version=1)
        self.assertEqual("cancelled", cancelled["status"])
        self.assertFalse(self.store.begin_execution(self.ctx, action["id"], expected_version=1)["claimed"])
        self.assertEqual(cancelled, self.store.cancel_action(self.ctx, action["id"], expected_version=1))

    def test_execution_result_is_idempotent_and_cannot_be_rewritten(self):
        action = self.approved()
        self.error("EXECUTION_NOT_STARTED", self.store.finish_execution, self.ctx, action["id"], status="succeeded", result={"id": "x"})
        self.store.begin_execution(self.ctx, action["id"], expected_version=1)
        self.store.finish_execution(self.ctx, action["id"], status="succeeded", result={"id": "x"})
        self.store.finish_execution(self.ctx, action["id"], status="succeeded", result={"id": "x"})
        self.error("EXECUTION_ALREADY_FINISHED", self.store.finish_execution, self.ctx, action["id"], status="succeeded", result={"id": "y"})

    def test_memory_store_keeps_state_across_internal_connections(self):
        with_memory = ConversationStore(":memory:")
        try:
            with_memory.claim_event(self.ctx, "e1", "你好")
            self.assertEqual("你好", with_memory.history(self.ctx)[0]["content"])
        finally:
            with_memory.close()

    def test_invalid_structured_inputs_fail_without_mutation(self):
        self.error("INVALID_TASK_STATUS", self.store.create_task, self.ctx,
                   project_id="P-17", title="报告", status=["closed"])
        self.assertEqual([], self.store.list_tasks(self.ctx))
        action = self.presented()
        self.error("ACTION_DIGEST_MISMATCH", self.store.approve_action, self.ctx,
                   action["id"], expected_version=1, digest="确认")
        self.error("INVALID_ACTION_ID", self.store.get_action, self.ctx, [action["id"]])
        self.error("INVALID_EXECUTION_STATUS", self.store.finish_execution, self.ctx,
                   action["id"], status=["succeeded"], result={})
        self.assertEqual("draft", self.store.get_action(self.ctx, action["id"])["status"])

    def test_focus_survives_days_and_restart_but_stays_scoped(self):
        self.store.claim_event(self.ctx, "focus-1", "查17")
        self.store.set_focus(self.ctx, "P-17", event_id="focus-1")
        self.now += 86400 * 3
        self.store.close()
        self.store = ConversationStore(self.path, clock=lambda: self.now)
        self.assertEqual("P-17", self.store.get_focus(self.ctx))
        for field in ("tenant_id", "app_id", "actor_id", "chat_id", "thread_id"):
            self.assertIsNone(self.store.get_focus(replace(self.ctx, **{field: "another"})))

    def test_focus_is_filtered_after_revocation_and_does_not_mutate_on_bad_event(self):
        self.store.set_focus(self.ctx, "P-17")
        revoked = replace(self.ctx, allowed_project_ids=frozenset({"P-20"}))
        self.assertIsNone(self.store.get_focus(revoked))
        self.error("PROJECT_FORBIDDEN", self.store.set_focus, revoked, "P-17")
        other = replace(self.ctx, chat_id="another-dm")
        self.store.claim_event(other, "other-focus", "查20")
        self.error("EVENT_SCOPE_MISMATCH", self.store.set_focus, self.ctx, "P-20", event_id="other-focus")
        self.assertEqual("P-17", self.store.get_focus(self.ctx))


if __name__ == "__main__":
    unittest.main()
