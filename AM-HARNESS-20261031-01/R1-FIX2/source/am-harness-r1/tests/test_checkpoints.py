from pathlib import Path
import sqlite3
import tempfile
import unittest

from am_harness.checkpoints import CheckpointError, CheckpointStore


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.sqlite3"
        self.store = CheckpointStore(self.path, clock=lambda: 100)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, **kw):
        return self.store.put(**(dict(scope_key="scope", permission_fingerprint="pv1", run_id="r1", phase="facts",
                                      input_value={"query": "q"}, value={"status": "reported"},
                                      dependencies={"source": "v1"}, dependency_expiries={"source": 130},
                                      project_ids=["P1"], expires_at=200) | kw))

    def get(self, **kw):
        return self.store.get(**(dict(scope_key="scope", permission_fingerprint="pv1", run_id="r1", phase="facts",
                                      input_value={"query": "q"}, current_versions={"source": "v1"},
                                      authorize_project=lambda p: p == "P1") | kw))

    def test_restart_hash_and_ttl_cap(self):
        self.assertEqual(self.put().expires_at, 130)
        self.store = CheckpointStore(self.path, clock=lambda: 110)
        self.assertEqual(self.get().value, {"status": "reported"})
        self.assertIsNone(self.get(input_value={"query": "changed"}))
        self.assertIsNone(self.get(now=130))

    def test_revocation_scope_permissions_versions(self):
        self.put()
        for kw in [dict(scope_key="other"), dict(permission_fingerprint="pv2"),
                   dict(current_versions={"source": "v2"}), dict(current_versions={}),
                   dict(authorize_project=lambda _: False), dict(revoked_sources=frozenset({"source"})),
                   dict(current_expiries={"source": 99})]:
            with self.subTest(kw=kw):
                self.assertIsNone(self.get(**kw))
        self.assertEqual(self.get(current_expiries={"source": 120}).expires_at, 120)

    def test_external_and_approval_not_cacheable(self):
        for effect in ["external", "approval", "local"]:
            with self.assertRaisesRegex(CheckpointError, "NOT_CACHEABLE"):
                self.put(effect=effect)
        self.put(effect="pure_local")
        self.assertEqual(self.get().effect, "pure_local")

    def test_dependency_lifetime_required_and_json_size_bound(self):
        with self.assertRaisesRegex(CheckpointError, "EXPIRY_REQUIRED"):
            self.put(dependency_expiries={})
        with self.assertRaisesRegex(CheckpointError, "EXPIRED_DEPENDENCY"):
            self.put(dependency_expiries={"source": 90})
        with self.assertRaisesRegex(CheckpointError, "CHECKPOINT_TOO_LARGE"):
            self.put(value="x" * 300000)

    def test_versioned_overwrite_invalidation_and_purge(self):
        self.assertEqual(self.put().version, 1)
        self.assertEqual(self.put(value={"different": True}).version, 2)
        self.assertEqual(self.store.invalidate_sources(["source"]), 1)
        self.assertIsNone(self.get())
        self.put()
        self.assertEqual(self.store.purge_expired(now=130), 1)

    def test_future_schema_rejected_without_modifying(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE am_harness_checkpoint_meta SET value=999")
        with self.assertRaisesRegex(CheckpointError, "UNSUPPORTED"):
            CheckpointStore(self.path)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT value FROM am_harness_checkpoint_meta").fetchone()[0], 999)


if __name__ == "__main__":
    unittest.main()
