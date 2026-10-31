"""Independent threads/processes compete on actual SQLite transactions."""
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from am_harness.store import DurableStore, Scope, StoreError


def process_claim(path, worker, barrier, output):
    try:
        store = DurableStore(path, clock=lambda: 1000)
        barrier.wait(10)
        lease = store.claim(worker)
        output.put((worker, None if lease is None else (lease.run.id, lease.generation)))
    except BaseException as exc:
        output.put((worker, {"error": type(exc).__name__ + ":" + str(exc)}))


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "am.sqlite"
        self.store = DurableStore(self.path, clock=lambda: 1000)
        self.scope = Scope("t", "a", "u", "c")

    def tearDown(self):
        self.temp.cleanup()

    def test_concurrent_duplicate_submission_has_one_durable_run(self):
        def submit(_):
            store = DurableStore(self.path, clock=lambda: 1000)
            return store.submit(self.scope, "same-event", "same input", deadline=1120, expires_at=1600).id
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(submit, range(16)))
        self.assertEqual(1, len(set(ids)))
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM am_harness_runs").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM am_harness_events").fetchone()[0])

    def test_spawned_processes_cannot_claim_two_turns(self):
        for i in range(3):
            self.store.submit(self.scope, f"event-{i}", "input", deadline=1120, expires_at=1600)
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Event()
        output = ctx.Queue()
        processes = [ctx.Process(target=process_claim, args=(str(self.path), f"worker-{i}", barrier, output))
                     for i in range(3)]
        try:
            for process in processes:
                process.start()
            barrier.set()
            results = [output.get(timeout=15) for _ in processes]
            for process in processes:
                process.join(timeout=15)
                self.assertEqual(0, process.exitcode)
            self.assertFalse([r for _, r in results if isinstance(r, dict)], results)
            self.assertEqual(1, len([r for _, r in results if r is not None]), results)
            self.assertEqual("active", self.store.lane_status()["state"])
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=3)
            output.close()

    def test_enqueue_commit_and_cancel_are_serialized_in_same_database(self):
        run = self.store.submit(self.scope, "e", "input", deadline=1120, expires_at=1600)
        lease = self.store.claim("worker")
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE original_outbox(id TEXT PRIMARY KEY,state TEXT)")
        attempted, cancelled = threading.Event(), threading.Event()
        errors = []
        # Initialize the second connection before holding the guarded transaction:
        # the test exercises cancellation vs enqueue, not WAL initialization.
        other = DurableStore(self.path, clock=lambda: 1000)
        def already_initialized_control():
            try:
                attempted.set()
                other.cancel(self.scope, "cancel", run.id, on_change=lambda conn, fence:
                             conn.execute("UPDATE original_outbox SET state='cancelled' WHERE id=?", (fence.run_id,)))
                cancelled.set()
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=already_initialized_control)
        with self.store.transaction_guard(lease.fence) as conn:
            conn.execute("INSERT INTO original_outbox VALUES(?, 'pending')", (run.id,))
            thread.start()
            self.assertTrue(attempted.wait(2))
            self.assertFalse(cancelled.is_set())
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)
        self.assertTrue(cancelled.is_set())
        with sqlite3.connect(self.path) as conn:
            self.assertEqual("cancelled", conn.execute("SELECT state FROM original_outbox").fetchone()[0])
        with self.assertRaises(StoreError):
            with self.store.transaction_guard(lease.fence):
                self.fail("stale reservation must be blocked")


if __name__ == "__main__":
    unittest.main()
