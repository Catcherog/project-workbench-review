"""Real SQLite tests: no provider, Feishu, or timing-performance claims."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from am_harness.store import DurableStore, Scope, StoreError


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "am.sqlite"
        self.clock = Clock()
        self.store = DurableStore(self.path, clock=self.clock)
        self.scope = Scope("tenant", "app", "owner", "chat", "thread")

    def tearDown(self):
        self.temp.cleanup()

    def submit(self, event="e1", text="查询项目状态", **kwargs):
        return self.store.submit(self.scope, event, text,
                                 deadline=kwargs.pop("deadline", self.clock() + 120),
                                 expires_at=kwargs.pop("expires_at", self.clock() + 600), **kwargs)

    def error(self, code, call):
        with self.assertRaises(StoreError) as exc:
            call()
        self.assertEqual(code, exc.exception.code)

    def test_scope_key_is_existing_am_canonical_identity(self):
        wire = json.dumps(self.scope.values, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
        self.assertEqual(self.scope.key, hashlib.sha256(wire.encode()).hexdigest())
        self.assertNotEqual(self.scope.key, replace(self.scope, thread_id="other").key)

    def test_restart_preserves_idempotency_and_original_timing(self):
        original = self.submit()
        self.clock.now += 5
        reopened = DurableStore(self.path, clock=self.clock)
        replay = reopened.submit(self.scope, "e1", "查询项目状态", deadline=1200, expires_at=1700)
        self.assertEqual(original, replay)
        self.error("EVENT_CONFLICT", lambda: reopened.submit(self.scope, "e1", "不同内容",
                                                            deadline=1200, expires_at=1700))
        self.assertEqual(1, len(reopened.active(self.scope)))

    def test_scope_isolation_and_same_external_event_in_another_scope(self):
        run = self.submit()
        other = replace(self.scope, actor_id="coworker")
        self.error("RUN_NOT_FOUND", lambda: self.store.get(other, run.id))
        self.error("RUN_NOT_FOUND", lambda: self.store.cancel(other, "cancel", run.id))
        self.error("RUN_NOT_FOUND", lambda: self.store.revise(other, "change", run.id, "新要求"))
        new = self.store.submit(other, "e1", "查询项目状态", deadline=1120, expires_at=1600)
        self.assertNotEqual(new.id, run.id)
        self.assertEqual([run.id], [r.id for r in self.store.active(self.scope)])

    def test_capacity_does_not_reject_identical_redelivery(self):
        one = DurableStore(self.path, clock=self.clock, max_queued=1)
        first = one.submit(self.scope, "e", "问题", deadline=1120, expires_at=1600)
        self.assertEqual(first, one.submit(self.scope, "e", "问题", deadline=1120, expires_at=1600))
        self.error("QUEUE_FULL", lambda: one.submit(self.scope, "other", "问题", deadline=1120, expires_at=1600))

    def test_cancel_running_retains_lane_and_drops_returned_result(self):
        run = self.submit()
        lease = self.store.claim("worker")
        cancelled = self.store.cancel(self.scope, "cancel", run.id)
        self.assertEqual("cancelled", cancelled.state)
        self.assertEqual(1, cancelled.cancel_epoch)
        self.error("STALE_FENCE", lambda: self.store.guard(lease.fence))
        self.assertIsNone(self.store.claim("second-worker"))
        called = []
        self.assertFalse(self.store.finish(lease, result={"text": "旧答案"},
                                           on_commit=lambda *_: called.append(True)))
        self.assertEqual([], called)
        self.assertEqual("idle", self.store.lane_status()["state"])
        self.assertEqual("cancelled", self.store.get(self.scope, run.id).state)

    def test_control_replay_cannot_target_a_newer_task(self):
        first = self.submit()
        self.store.cancel(self.scope, "cancel-event", first.id)
        second = self.submit("e2")
        replay = self.store.replay_control(self.scope, "cancel-event", "cancel")
        self.assertEqual(first.id, replay.id)
        self.assertEqual("queued", self.store.get(self.scope, second.id).state)
        self.error("EVENT_CONFLICT", lambda: self.store.replay_control(
            self.scope, "cancel-event", "cancel", target_run_id=second.id))
        again = self.store.cancel(self.scope, "cancel-event", first.id)
        self.assertEqual(1, again.cancel_epoch)

    def test_noop_control_is_durable_and_cross_operation_conflicts(self):
        self.assertIsNone(self.store.replay_control_noop(self.scope, "stop", "cancel"))
        self.store.record_control_noop(self.scope, "stop", "cancel", reason="no_active_run")
        run = self.submit()
        reopened = DurableStore(self.path, clock=self.clock)
        self.assertEqual("no_active_run", reopened.replay_control_noop(self.scope, "stop", "cancel"))
        self.error("EVENT_CONFLICT", lambda: reopened.cancel(self.scope, "stop", run.id))
        self.error("EVENT_CONFLICT", lambda: reopened.submit(self.scope, "stop", "问题", deadline=1120, expires_at=1600))
        self.error("EVENT_CONFLICT", lambda: reopened.replay_control_noop(self.scope, "stop", "revise", "新问题"))
        self.assertEqual("queued", reopened.get(self.scope, run.id).state)
        reopened.cancel(self.scope, "real-stop", run.id)
        self.error("EVENT_CONFLICT", lambda: reopened.record_control_noop(self.scope, "real-stop", "cancel"))

    def test_running_revision_waits_for_old_worker_and_keeps_retention(self):
        run = self.submit()
        lease = self.store.claim("old")
        self.clock.now += 2
        changed = self.store.revise(self.scope, "change", run.id, "改查里程碑", deadline=1130)
        self.assertEqual(2, changed.revision)
        self.assertEqual(run.expires_at, changed.expires_at)
        self.assertIsNone(self.store.claim("new"))
        self.assertFalse(self.store.finish(lease, result={"text": "旧答案"}))
        new = self.store.claim("new")
        self.assertEqual("改查里程碑", new.run.input_text)
        self.assertGreater(new.generation, lease.generation)
        self.assertTrue(self.store.finish(new, result={"text": "新答案"}))
        self.assertEqual({"text": "新答案"}, self.store.get(self.scope, run.id).result)
        replay = self.store.replay_control(self.scope, "change", "revise", "改查里程碑")
        self.assertEqual(2, replay.revision)
        self.error("EVENT_CONFLICT", lambda: self.store.replay_control(self.scope, "change", "revise", "另一个问题"))

    def test_expired_lease_is_quarantined_across_restart(self):
        run = self.submit()
        lease = self.store.claim("lost-worker", lease_seconds=3)
        self.clock.now += 4
        reopened = DurableStore(self.path, clock=self.clock)
        self.assertIsNone(reopened.claim("replacement"))
        self.assertEqual("quarantined", reopened.lane_status()["state"])
        self.assertEqual("unknown", reopened.get(self.scope, run.id).state)
        self.error("LEASE_QUARANTINED", lambda: reopened.heartbeat(lease))
        self.error("LEASE_QUARANTINED", lambda: reopened.finish(lease, result="late"))
        self.assertEqual("quarantined", reopened.lane_status()["state"])

    def test_guard_checks_expired_execution_lease_before_any_new_claim(self):
        self.submit()
        lease = self.store.claim("worker", lease_seconds=2)
        self.clock.now += 3
        with sqlite3.connect(self.path, isolation_level=None) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self.error("STALE_LEASE", lambda: self.store.check_in_transaction(conn, lease.fence))
            conn.execute("ROLLBACK")
        self.error("RUN_NOT_ACTIVE", lambda: self.store.guard(lease.fence))
        self.assertEqual("quarantined", self.store.lane_status()["state"])

    def test_quarantine_requires_positive_stopped_proof_and_does_not_requeue(self):
        self.submit()
        lease = self.store.claim("worker")
        self.store.quarantine(lease, reason="STOP_UNKNOWN")
        self.error("PROOF_REQUIRED", lambda: self.store.resolve_quarantine(
            lease, proof={"execution_state": "timed_out"}, verifier=lambda *_: True))
        self.error("PROOF_REJECTED", lambda: self.store.resolve_quarantine(
            lease, proof={"execution_state": "stopped"}, verifier=lambda *_: False))
        self.store.resolve_quarantine(lease, proof={"execution_state": "stopped", "source": "host-observation"},
                                      verifier=lambda candidate, _: candidate.token == lease.token)
        self.assertEqual("idle", self.store.lane_status()["state"])
        self.assertIsNone(self.store.claim("new"))
        self.assertEqual("unknown", self.store.get(self.scope, lease.run.id).state)
        self.error("STALE_LEASE", lambda: self.store.resolve_quarantine(
            lease, proof={"execution_state": "stopped"}, verifier=lambda *_: True))

    def test_unknown_cannot_be_finished_as_if_provider_stopped(self):
        self.submit()
        lease = self.store.claim("worker")
        self.error("INVALID_FINISH_STATE", lambda: self.store.finish(lease, state="unknown"))
        self.assertEqual("active", self.store.lane_status()["state"])

    def test_safe_not_dispatched_retry_changes_generation_and_honors_backoff(self):
        self.submit()
        lease = self.store.claim("first")
        self.assertTrue(self.store.release_not_dispatched(lease, proof={"dispatch_state": "not_started"},
                                                       verifier=lambda *_: True, delay_seconds=2))
        self.assertIsNone(self.store.claim("second"))
        self.clock.now += 2
        newer = self.store.claim("second")
        self.assertEqual(lease.run.revision, newer.run.revision)
        self.assertGreater(newer.generation, lease.generation)
        self.error("STALE_LEASE", lambda: self.store.guard(lease.fence))
        self.error("STALE_LEASE", lambda: self.store.heartbeat(lease))
        self.error("STALE_LEASE", lambda: self.store.finish(lease))
        self.assertTrue(self.store.finish(newer))

    def test_terminal_publication_rejects_previous_attempt_generation(self):
        for state in ("succeeded", "waiting_review"):
            with self.subTest(state=state):
                self.submit(event=state)
                old = self.store.claim("first")
                self.store.release_not_dispatched(old, proof={"dispatch_state": "not_started"},
                                                  verifier=lambda *_: True, delay_seconds=0)
                current = self.store.claim("second")
                self.assertEqual(old.fence.revision, current.fence.revision)
                self.assertGreater(current.fence.generation, old.fence.generation)
                self.assertTrue(self.store.finish(current, state=state))
                self.error("STALE_LEASE", lambda: self._dispatch_check(old.fence))
                self.assertEqual(state, self._dispatch_check(current.fence).state)

    def test_deadline_does_not_free_running_lane(self):
        run = self.submit(deadline=1002)
        lease = self.store.claim("worker", lease_seconds=30)
        self.clock.now += 3
        self.error("DEADLINE_EXCEEDED", lambda: self.store.guard(lease.fence))
        self.assertEqual("expired", self.store.get(self.scope, run.id).state)
        self.assertIsNone(self.store.claim("another"))
        self.assertFalse(self.store.finish(lease, result="too late"))
        self.assertEqual("idle", self.store.lane_status()["state"])

    def test_ttl_purges_input_result_and_raw_scope_without_reopening_event(self):
        run = self.submit(text="PRIVATE SENTINEL", deadline=1005, expires_at=1010)
        lease = self.store.claim("worker")
        self.store.finish(lease, result={"answer": "PRIVATE RESULT"})
        self.clock.now = 1011
        self.assertEqual(1, self.store.purge_expired())
        expired = self.store.get(self.scope, run.id)
        self.assertIsNone(expired.input_text)
        self.assertIsNone(expired.result)
        self.assertTrue(expired.purged)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual((None, None, None), conn.execute(
                "SELECT input_text,result_json,scope_json FROM am_harness_runs WHERE id=?", (run.id,)).fetchone())
        replay = self.submit(text="PRIVATE SENTINEL", deadline=1130, expires_at=1700)
        self.assertTrue(replay.purged)
        self.assertEqual(run.id, replay.id)
        self.assertEqual(run.expires_at, replay.expires_at)
        self.assertNotIn("PRIVATE", json.dumps(self.store.audit()))

    def test_priority_aging_prevents_continuous_new_high_priority_starvation(self):
        low = self.submit("low", priority=-10, deadline=2200, expires_at=2300)
        self.clock.now += 660
        self.submit("high", priority=10, deadline=2200, expires_at=2300)
        self.assertEqual(low.id, self.store.claim("worker").run.id)

    def test_original_database_schema_version_and_tables_are_preserved(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA user_version=73")
            conn.execute("CREATE TABLE original_outbox (id TEXT PRIMARY KEY, state TEXT)")
            conn.execute("INSERT INTO original_outbox VALUES('old','sent')")
        DurableStore(self.path, clock=self.clock)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(73, conn.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(("old", "sent"), conn.execute("SELECT * FROM original_outbox").fetchone())
            conn.execute("UPDATE am_harness_meta SET value='999' WHERE key='schema_version'")
        self.error("UNSUPPORTED_SCHEMA_VERSION", lambda: DurableStore(self.path, clock=self.clock))

    def test_finish_and_outbox_insert_share_atomic_commit_and_rollback(self):
        self.submit()
        lease = self.store.claim("worker")
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE original_outbox (id TEXT PRIMARY KEY,state TEXT)")
        def failing(conn, run):
            conn.execute("INSERT INTO original_outbox VALUES(?, 'pending')", (run.id,))
            raise RuntimeError("host SQL failed")
        with self.assertRaises(RuntimeError):
            self.store.finish(lease, result={"text": "answer"}, on_commit=failing)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM original_outbox").fetchone()[0])
        self.assertEqual("running", self.store.get(self.scope, lease.run.id).state)
        self.assertEqual("active", self.store.lane_status()["state"])
        def commit(conn, run):
            self.store.check_in_transaction(conn, run.fence)
            conn.execute("INSERT INTO original_outbox VALUES(?, 'pending')", (run.id,))
        self.assertTrue(self.store.finish(lease, result={"text": "answer"}, on_commit=commit))
        self.error("RUN_NOT_ACTIVE", lambda: self.store.cancel(self.scope, "cancel", lease.run.id))
        def withdraw(conn, old):
            conn.execute("UPDATE original_outbox SET state='cancelled' WHERE id=? AND state='pending'", (old.run_id,))
        self.store.cancel(self.scope, "cancel", lease.run.id, on_change=withdraw)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual("cancelled", conn.execute("SELECT state FROM original_outbox").fetchone()[0])
        self.error("STALE_FENCE", lambda: self._dispatch_check(lease.fence))

    def _dispatch_check(self, fence, *, enforce_execution_deadline=True):
        with sqlite3.connect(self.path, isolation_level=None) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                return self.store.check_in_transaction(conn, fence,
                                                       enforce_execution_deadline=enforce_execution_deadline)
            finally:
                conn.execute("ROLLBACK")

    def test_transaction_guard_works_with_plain_tuple_rows_and_rejects_wrong_db(self):
        self.submit()
        lease = self.store.claim("worker")
        self.assertEqual(lease.run.id, self._dispatch_check(lease.fence).id)
        with sqlite3.connect(self.path) as conn:
            self.error("TRANSACTION_REQUIRED", lambda: self.store.check_in_transaction(conn, lease.fence))
        other_path = Path(self.temp.name) / "other.sqlite"
        with sqlite3.connect(other_path, isolation_level=None) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self.error("DATABASE_MISMATCH", lambda: self.store.check_in_transaction(conn, lease.fence))
            conn.execute("ROLLBACK")

    def test_deadline_passed_during_commit_callback_rolls_back_publication(self):
        self.submit(deadline=1002)
        lease = self.store.claim("worker")
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE original_outbox(id TEXT PRIMARY KEY)")
        def too_late(conn, run):
            conn.execute("INSERT INTO original_outbox VALUES(?)", (run.id,))
            self.clock.now = 1003
        self.error("DEADLINE_EXCEEDED", lambda: self.store.finish(lease, on_commit=too_late))
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM original_outbox").fetchone()[0])
        self.assertEqual("active", self.store.lane_status()["state"])
        self.assertFalse(self.store.finish(lease))

    def test_transaction_guard_rechecks_expiry_before_committing(self):
        self.submit(deadline=1002)
        lease = self.store.claim("worker")
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE original_outbox(id TEXT PRIMARY KEY)")
        with self.assertRaises(StoreError):
            with self.store.transaction_guard(lease.fence) as conn:
                conn.execute("INSERT INTO original_outbox VALUES(?)", (lease.run.id,))
                self.clock.now = 1003
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM original_outbox").fetchone()[0])

    def test_completed_delivery_can_outlive_execution_deadline_but_never_content_ttl(self):
        for index, state in enumerate(("succeeded", "waiting_review")):
            with self.subTest(state=state):
                self.clock.now = 1000 + index * 1000
                deadline, expiry = self.clock() + 2, self.clock() + 600
                run = self.submit(event=state, deadline=deadline, expires_at=expiry)
                lease = self.store.claim("worker")
                self.clock.now += 1
                self.assertTrue(self.store.finish(lease, state=state))
                self.clock.now = deadline + 1
                self.assertEqual(state, self.store.get(self.scope, run.id).state)
                self.error("DEADLINE_EXCEEDED", lambda: self._dispatch_check(lease.fence))
                delivered = self._dispatch_check(lease.fence, enforce_execution_deadline=False)
                self.assertEqual(state, delivered.state)
                self.clock.now = expiry + 1
                self.error("CONTENT_EXPIRED", lambda: self._dispatch_check(
                    lease.fence, enforce_execution_deadline=False))

    def test_delivery_deadline_policy_cannot_bypass_running_execution_budget(self):
        self.submit(deadline=1002)
        lease = self.store.claim("worker")
        self.error("RUN_NOT_ACTIVE", lambda: self._dispatch_check(
            lease.fence, enforce_execution_deadline=False))
        self.clock.now = 1003
        self.error("RUN_NOT_ACTIVE", lambda: self._dispatch_check(
            lease.fence, enforce_execution_deadline=False))
        self.error("DEADLINE_EXCEEDED", lambda: self._dispatch_check(lease.fence))
        published = []
        self.assertFalse(self.store.finish(lease, on_commit=lambda *_: published.append(True)))
        self.assertEqual([], published)

    def test_cancellation_callback_failure_rolls_back_epoch_and_local_sql(self):
        run = self.submit()
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE original_outbox (id TEXT,state TEXT)")
            conn.execute("INSERT INTO original_outbox VALUES(?, 'pending')", (run.id,))
        def failing(conn, old):
            conn.execute("UPDATE original_outbox SET state='cancelled'")
            raise RuntimeError("cannot withdraw safely")
        with self.assertRaises(RuntimeError):
            self.store.cancel(self.scope, "cancel", run.id, on_change=failing)
        self.assertEqual(0, self.store.get(self.scope, run.id).cancel_epoch)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual("pending", conn.execute("SELECT state FROM original_outbox").fetchone()[0])

    def test_invalid_inputs_fail_without_saving_their_contents(self):
        self.error("INVALID_PRIORITY", lambda: self.submit(priority=True))
        self.error("INVALID_DEADLINE", lambda: self.submit(deadline=1000))
        self.error("INVALID_DEADLINE", lambda: self.submit(deadline=2000, expires_at=1600))
        self.error("INVALID_TIME", lambda: self.submit(deadline=float("inf")))
        self.error("INVALID_INPUT", lambda: self.submit(text=""))
        self.error("INVALID_INPUT", lambda: self.submit(text="x" * 6001))
        self.assertEqual([], self.store.active(self.scope))


if __name__ == "__main__":
    unittest.main()
