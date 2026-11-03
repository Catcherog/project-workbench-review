from contextlib import contextmanager
import sqlite3
import threading
from types import SimpleNamespace
import unittest
import uuid

from am_training_window.host import ExistingCoordinatorHost, StoreMaintenanceFence
from am_training_window.window import HostBinding, HostObservation, ModelIdentity, WindowError

MODEL = ModelIdentity("qwen3.8:27b-bartowski-q8_0", "a" * 64)
BINDING = HostBinding("unique-consumer-1", "b" * 64, MODEL, "llamacpp")


class StoreFixture:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def rows(self, sql, args=()):
        cursor = self.db.execute(sql, args)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, values)) for values in cursor.fetchall()]


class HostAdapterTests(unittest.TestCase):
    def setUp(self):
        self.store = StoreFixture()
        self.addCleanup(self.store.db.close)
        self.fence = StoreMaintenanceFence(self.store)
        self.owner = str(uuid.uuid4())

    def test_owned_pause_claim_release_and_duplicate_claim(self):
        self.fence.claim(self.owner)
        self.fence.claim(self.owner)
        self.assertEqual(self.fence.inspect(), self.owner)
        self.assertIsNone(self.store.db.execute("SELECT value FROM meta WHERE key='provider_pause'").fetchone())
        self.fence.seal(self.owner)
        self.assertTrue(self.store.db.execute("SELECT value FROM meta WHERE key='provider_pause'").fetchone()[0])
        self.fence.release(self.owner)
        self.assertIsNone(self.fence.inspect())

    def test_foreign_window_cannot_clear_pause(self):
        self.fence.claim(self.owner)
        foreign = str(uuid.uuid4())
        with self.assertRaises(WindowError):
            self.fence.claim(foreign)
        with self.assertRaises(WindowError):
            self.fence.release(foreign)
        self.assertEqual(self.fence.inspect(), self.owner)

    def test_unknown_stop_error_is_preserved(self):
        self.fence.claim(self.owner)
        self.fence.seal(self.owner)
        self.store.db.execute("UPDATE meta SET value='STOP_UNKNOWN' WHERE key='provider_pause'")
        with self.assertRaises(WindowError):
            self.fence.release(self.owner)
        with self.assertRaises(WindowError):
            self.fence.inspect()
        self.assertEqual(self.store.db.execute("SELECT value FROM meta WHERE key='provider_pause'").fetchone()[0], "STOP_UNKNOWN")

    def test_preexisting_pause_never_overwritten(self):
        self.store.db.execute("INSERT INTO meta VALUES('provider_pause','LOCAL_API_UNAVAILABLE')")
        with self.assertRaises(WindowError):
            self.fence.claim(self.owner)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM meta").fetchone()[0], 1)

    def test_unsealed_draining_can_release_without_pausing_provider(self):
        self.fence.claim(self.owner)
        self.fence.release(self.owner)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM meta").fetchone()[0], 0)

    def test_existing_lock_and_store_are_used_for_drain(self):
        lock = threading.Lock()
        coordinator = SimpleNamespace(store=self.store, lock=lock, complete=lambda: None)
        observed = HostObservation(BINDING, 1, True, True, 0, 0, (MODEL,), None)
        lifecycle = SimpleNamespace(suspend=lambda binding: None, restore=lambda binding: None)
        adapter = ExistingCoordinatorHost(coordinator=coordinator, store=self.store,
            read_observation=lambda: observed, lifecycle=lifecycle, drain_timeout_seconds=0)
        adapter.close_admission(self.owner)
        lock.acquire()
        try:
            with self.assertRaises(WindowError):
                adapter.drain(self.owner)
        finally:
            lock.release()
        adapter.drain(self.owner)
        self.assertEqual(adapter.inspect().fence_owner, self.owner)
        adapter.open_admission(self.owner)
        self.assertIsNone(adapter.inspect().fence_owner)


if __name__ == "__main__":
    unittest.main()
