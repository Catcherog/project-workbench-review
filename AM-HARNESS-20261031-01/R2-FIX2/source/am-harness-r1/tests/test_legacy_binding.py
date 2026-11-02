from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from am_harness.am_adapter import engine_event_id
from am_harness.legacy_binding import deterministic_publication_key, verify_legacy_binding
from am_harness.store import DurableStore, Scope, canonical


def hashed(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


# These are the baseline AM table/column names used by the verifier. Fixtures
# create local records only; they do not represent live ingress/authentication.
AM_SCHEMA = """
CREATE TABLE am_inbox(id TEXT PRIMARY KEY,app TEXT,tenant TEXT,user TEXT,chat TEXT,
    chat_type TEXT,created REAL,expires REAL,body TEXT,kind TEXT,state TEXT,error TEXT);
CREATE TABLE am_source_meta(id TEXT PRIMARY KEY,metadata TEXT NOT NULL);
CREATE TABLE outbox(id TEXT PRIMARY KEY,app TEXT,tenant TEXT,user TEXT,chat TEXT,
    chat_type TEXT,origin_chat_type TEXT,kind TEXT,body TEXT,created REAL,expires REAL,
    state TEXT DEFAULT 'pending',message_id TEXT,error TEXT);
CREATE TABLE am_conversation_outputs(outbox_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,
    tenant TEXT NOT NULL,app TEXT NOT NULL,scope TEXT NOT NULL,input_hash TEXT NOT NULL,
    context TEXT NOT NULL,grant_json TEXT NOT NULL,reply TEXT NOT NULL,expires REAL NOT NULL,
    state TEXT DEFAULT 'pending',message_id TEXT,error TEXT,rendered_text TEXT,
    UNIQUE(tenant,app,event_id));
CREATE TABLE am_outbox_events(outbox_id TEXT PRIMARY KEY,event_id TEXT NOT NULL);
CREATE TABLE am_query_deliveries(outbox_id TEXT PRIMARY KEY,scope_hash TEXT NOT NULL,denial INTEGER NOT NULL);
CREATE TABLE am_group_delivery(outbox_id TEXT PRIMARY KEY,source_chat TEXT,reply_to TEXT,thread TEXT,mode TEXT);
CREATE TABLE am_group_refs(message_id TEXT PRIMARY KEY,app TEXT,tenant TEXT,chat TEXT,projects TEXT,expires REAL);
"""


class LegacyBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "am.sqlite3"
        self.now = [100.0]
        self.store = DurableStore(self.path, clock=lambda: self.now[0])
        with sqlite3.connect(self.path) as conn:
            conn.executescript(AM_SCHEMA)

    def tearDown(self):
        self.tmp.cleanup()

    @contextmanager
    def tx(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    def source(self, event, body, *, scope=None, chat_type=None, metadata=None, expires=250):
        scope = scope or self.scope
        chat_type = chat_type or self.chat_type
        with self.tx() as conn:
            conn.execute("INSERT INTO am_inbox VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL)",
                         (event, scope.app_id, scope.tenant_id, scope.actor_id, scope.chat_id, chat_type,
                          80, expires, body, "conversation", "received"))
            if metadata is not None:
                conn.execute("INSERT INTO am_source_meta VALUES(?,?)", (event, canonical(metadata)))

    def case(self, *, thread="", chat_type="p2p", metadata=None):
        self.scope = Scope("tenant", "app", "actor", "chat", thread)
        self.chat_type = chat_type
        if metadata is None and thread:
            metadata = {"thread": thread}
        self.source("origin", "查询 P1 当前进展", metadata=metadata)
        self.run = self.store.submit(self.scope, "origin", "查询 P1 当前进展", deadline=120, expires_at=200)
        self.lease = self.store.claim("worker", lease_seconds=30)
        self.run = self.lease.run
        return self.run

    def enqueue(self, *, outbox_id="out", source_event="origin", expires=200, references=(), context_changes=None):
        run = self.run
        with self.tx() as conn:
            body = conn.execute("SELECT body FROM am_inbox WHERE id=?", (source_event,)).fetchone()[0]
            context = dict(tenant_id=run.scope.tenant_id, app_id=run.scope.app_id,
                           actor_id=run.scope.actor_id, chat_id=run.scope.chat_id, thread_id=run.scope.thread_id,
                           allowed_project_ids=["P1", "P2"], all_projects=False,
                           is_owner=self.chat_type == "p2p", content_expires_at=expires,
                           reference_project_ids=list(references), source_access_version=None)
            context.update(context_changes or {})
            conn.execute("""INSERT INTO outbox(id,app,tenant,user,chat,chat_type,origin_chat_type,kind,body,created,expires)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (outbox_id, run.scope.app_id, run.scope.tenant_id,
                     run.scope.actor_id, run.scope.chat_id, self.chat_type, self.chat_type, "text", "current reply", 100, expires))
            conn.execute("""INSERT INTO am_conversation_outputs
                (outbox_id,event_id,tenant,app,scope,input_hash,context,grant_json,reply,expires,rendered_text)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (outbox_id, source_event, run.scope.tenant_id, run.scope.app_id,
                     run.scope.key, hashed(body), canonical(context), canonical(["P1", "P2"]),
                     canonical({"event_id": engine_event_id(run), "text": "current reply", "pending_actions": []}), expires, "current reply"))
            conn.execute("INSERT INTO am_outbox_events VALUES(?,?)", (outbox_id, source_event))
            conn.execute("INSERT INTO am_query_deliveries VALUES(?,?,0)", (outbox_id, hashed(["P1", "P2"])))
            if self.chat_type == "group":
                conn.execute("INSERT INTO am_group_delivery VALUES(?,?,?,?,?)",
                             (outbox_id, run.scope.chat_id, source_event, run.scope.thread_id or None, "public"))

    def verify(self, outbox_id="out", run=None):
        with self.tx() as conn:
            verify_legacy_binding(conn, run or self.run, outbox_id)

    def test_real_event_context_chain_and_empty_thread(self):
        self.case()  # No am_source_meta record: empty thread is a valid scope.
        self.enqueue()
        self.assertIsNone(self.verify())
        with sqlite3.connect(self.path) as conn:
            with self.assertRaisesRegex(RuntimeError, "TRANSACTION_REQUIRED"):
                verify_legacy_binding(conn, self.run, "out")

    def test_default_fenced_outbox_composes_with_real_origin_verifier(self):
        from am_harness.effects import FencedOutbox
        self.case();self.enqueue()
        effects=FencedOutbox(self.store)
        self.assertTrue(self.store.finish(self.lease,result={"ok":True},
                        on_commit=lambda conn,run:effects.bind(conn,run,"out")))
        self.now[0]=121  # Execution deadline ended; committed result TTL is 200.
        with self.tx() as conn:
            self.assertTrue(effects.before_dispatch(conn,"out"))
            conn.execute("UPDATE outbox SET state='sending' WHERE id='out'")

    def test_same_chat_other_thread_context_rejected(self):
        self.case(thread="thread-A", chat_type="group")
        self.enqueue(context_changes={"thread_id": "thread-B"})
        with self.assertRaisesRegex(RuntimeError, "CONTEXT_SCOPE_MISMATCH"):
            self.verify()

    def test_original_ingress_thread_replaced_rejected(self):
        self.case(thread="thread-A", chat_type="group")
        self.enqueue()
        with self.tx() as conn:
            conn.execute("UPDATE am_source_meta SET metadata=? WHERE id='origin'", (canonical({"thread": "thread-B"}),))
        with self.assertRaisesRegex(RuntimeError, "SOURCE_SCOPE_MISMATCH"):
            self.verify()

    def test_original_message_and_matching_saved_hash_cannot_be_replaced(self):
        self.case()
        self.enqueue()
        changed = "伪造的另一个请求"
        with self.tx() as conn:
            conn.execute("UPDATE am_inbox SET body=? WHERE id='origin'", (changed,))
            conn.execute("UPDATE am_conversation_outputs SET input_hash=? WHERE outbox_id='out'", (hashed(changed),))
        with self.assertRaisesRegex(RuntimeError, "ORIGINAL_INPUT_HASH_MISMATCH"):
            self.verify()

    def test_source_hash_uses_legacy_canonical_json(self):
        self.case()
        self.enqueue()
        with self.tx() as conn:
            conn.execute("UPDATE am_conversation_outputs SET input_hash=?", (hashlib.sha256(self.run.input_text.encode()).hexdigest(),))
        with self.assertRaisesRegex(RuntimeError, "SOURCE_INPUT_HASH_MISMATCH"):
            self.verify()

    def test_corrected_revision_uses_real_control_event(self):
        self.case(thread="thread-A", chat_type="group")
        first_key = deterministic_publication_key(self.run)
        self.source("correction", "更正当前任务：只查询 P1 负责人", metadata={"thread": "thread-A"})
        self.store.revise(self.scope, "correction", self.run.id, "只查询 P1 负责人", deadline=180)
        self.assertFalse(self.store.finish(self.lease, result={"obsolete": True}))
        self.lease = self.store.claim("next-worker", lease_seconds=30)
        self.run = self.lease.run
        self.enqueue(source_event="correction")
        self.assertIsNone(self.verify())
        self.assertNotEqual(first_key, deterministic_publication_key(self.run))
        with self.tx() as conn:
            saved = conn.execute("SELECT event_id,reply FROM am_conversation_outputs").fetchone()
        self.assertEqual(saved[0], "correction")
        self.assertEqual(json.loads(saved[1])["event_id"], engine_event_id(self.run))
        self.assertNotEqual(saved[0], json.loads(saved[1])["event_id"])

    def revise(self):
        self.source("correction", "更正当前任务：新请求")
        self.store.revise(self.scope, "correction", self.run.id, "新请求", deadline=180)
        self.store.finish(self.lease)
        self.lease = self.store.claim("next-worker")
        self.run = self.lease.run

    def test_revision_cannot_reuse_original_output_event(self):
        self.case()
        self.revise()
        self.enqueue(source_event="origin")
        with self.assertRaisesRegex(RuntimeError, "OUTPUT_EVENT_MISMATCH"):
            self.verify()

    def test_revision_cannot_use_fabricated_normal_message(self):
        self.case()
        self.revise()
        self.enqueue(source_event="correction")
        with self.tx() as conn:
            conn.execute("UPDATE am_inbox SET body='新请求' WHERE id='correction'")
            conn.execute("UPDATE am_conversation_outputs SET input_hash=?", (hashed("新请求"),))
        with self.assertRaisesRegex(RuntimeError, "REVISION_INPUT_MISMATCH"):
            self.verify()

    def test_link_engine_id_and_ttl_are_checked_independently(self):
        self.case()
        self.enqueue()
        mutations = [
            ("UPDATE am_outbox_events SET event_id='fake'", (), "OUTBOX_EVENT_MISMATCH"),
            ("UPDATE am_conversation_outputs SET reply=?", (canonical({"event_id": "origin"}),), "ENGINE_EVENT_MISMATCH"),
            ("UPDATE outbox SET expires=201", (), "OUTPUT_TTL_MISMATCH"),
            ("DELETE FROM am_conversation_outputs", (), "OUTPUT_RECORD_REQUIRED"),
        ]
        for sql, params, code in mutations:
            with self.subTest(code=code), self.tx() as conn:
                conn.execute("SAVEPOINT mutation")
                conn.execute(sql, params)
                with self.assertRaisesRegex(RuntimeError, code):
                    verify_legacy_binding(conn, self.run, "out")
                conn.execute("ROLLBACK TO mutation")

    def test_late_delivery_does_not_reapply_execution_deadline(self):
        self.case()
        self.enqueue()
        self.assertTrue(self.store.finish(self.lease, result={"finished": True}))
        self.now[0] = 121  # execution deadline 120; content TTL remains 200.
        self.run = self.store.get(self.scope, self.run.id)
        self.assertEqual(self.run.state, "succeeded")
        self.assertIsNone(self.verify())

    def test_group_quote_and_transport_thread_have_real_bindings(self):
        self.case(thread="thread-A", chat_type="group", metadata={"thread": "thread-A", "parent": "quoted-message"})
        with self.tx() as conn:
            conn.execute("INSERT INTO am_group_refs VALUES(?,?,?,?,?,?)",
                         ("quoted-message", "app", "tenant", "chat", canonical(["P1", "P3"]), 180))
        self.enqueue(expires=180, references=("P1",))
        self.assertIsNone(self.verify())
        with self.tx() as conn:
            conn.execute("UPDATE am_group_delivery SET thread='thread-B'")
        with self.assertRaisesRegex(RuntimeError, "GROUP_THREAD_BINDING_MISMATCH"):
            self.verify()
        with self.tx() as conn:
            conn.execute("UPDATE am_group_delivery SET thread='thread-A'")
            conn.execute("UPDATE am_group_refs SET expires=170")
        with self.assertRaisesRegex(RuntimeError, "QUOTED_SOURCE_UNAVAILABLE"):
            self.verify()

    def test_query_grant_binding_cannot_be_reused_for_other_scope(self):
        self.case()
        self.enqueue()
        with self.tx() as conn:
            conn.execute("UPDATE am_query_deliveries SET scope_hash=?", (hashed(["other-project"]),))
        with self.assertRaisesRegex(RuntimeError, "GRANT_BINDING_INVALID"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
