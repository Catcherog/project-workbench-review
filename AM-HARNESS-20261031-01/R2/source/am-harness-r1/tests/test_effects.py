from pathlib import Path
import sqlite3
import tempfile
import unittest

from am_harness.effects import FencedOutbox
from am_harness.store import DurableStore, Scope


class EffectTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.now=1000
        self.store=DurableStore(Path(self.tmp.name)/"am.sqlite",clock=lambda:self.now)
        self.scope=Scope("tenant","app","actor","chat","thread")
        with sqlite3.connect(self.store.path) as c:
            c.execute("""CREATE TABLE outbox(id TEXT PRIMARY KEY,app TEXT,tenant TEXT,user TEXT,chat TEXT,
                         expires REAL,state TEXT,error TEXT,message_id TEXT,body TEXT)""")
        self.out=FencedOutbox(self.store,binding_verifier=lambda c,r,o:None)
        self.run=self.store.submit(self.scope,"event","question",deadline=1120,expires_at=1600)
        self.lease=self.store.claim("worker")

    def tearDown(self): self.tmp.cleanup()

    def enqueue(self,conn,run):
        conn.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,'pending',NULL,NULL,?)",
                     ("out-1","app","tenant","actor","chat",run.expires_at,"synthetic result"))
        return "out-1"

    def commit(self):
        self.assertTrue(self.store.finish(self.lease,result={"ok":True},
                        on_commit=lambda c,r:self.out.enqueue(c,r,self.enqueue)))

    def state(self):
        with sqlite3.connect(self.store.path) as c:
            return c.execute("SELECT state FROM outbox WHERE id='out-1'").fetchone()[0]

    def test_cancel_before_finish_atomically_blocks_publication(self):
        self.store.cancel(self.scope,"cancel",self.run.id,on_change=self.out.suppress_pending)
        self.assertFalse(self.store.finish(self.lease,on_commit=lambda c,r:self.out.enqueue(c,r,self.enqueue)))
        with sqlite3.connect(self.store.path) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],0)

    def test_cancel_after_enqueue_rejects_unsent_original_outbox(self):
        self.commit()
        self.store.cancel(self.scope,"cancel",self.run.id,on_change=self.out.suppress_pending)
        self.assertEqual(self.state(),"rejected")
        with sqlite3.connect(self.store.path,isolation_level=None) as c:
            c.execute("BEGIN IMMEDIATE")
            self.assertFalse(self.out.before_dispatch(c,"out-1")); c.commit()

    def test_dispatch_wins_then_cancel_records_uncertainty_and_preserves_receipt(self):
        self.commit()
        with sqlite3.connect(self.store.path,isolation_level=None) as c:
            c.execute("BEGIN IMMEDIATE")
            self.assertTrue(self.out.before_dispatch(c,"out-1"))
            c.execute("UPDATE outbox SET state='sending' WHERE id='out-1'")
            c.commit()
        self.store.cancel(self.scope,"cancel",self.run.id,on_change=self.out.suppress_pending)
        self.assertEqual(self.state(),"sending")
        with sqlite3.connect(self.store.path,isolation_level=None) as c:
            self.assertEqual(c.execute("SELECT state FROM am_harness_outbox").fetchone()[0],"needs_reconciliation")
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE outbox SET state='sent',message_id='receipt-1' WHERE id='out-1'")
            self.out.observe_receipt(c,"out-1","receipt-1",verified=True)
            c.commit()
            self.assertEqual(c.execute("SELECT state,verified FROM am_harness_outbox").fetchone(),("sent",1))

    def test_expired_delivery_rejected_without_touching_other_am_rows(self):
        self.commit(); self.now=1601
        with sqlite3.connect(self.store.path,isolation_level=None) as c:
            c.execute("BEGIN IMMEDIATE")
            self.assertFalse(self.out.before_dispatch(c,"out-1"))
            self.assertTrue(self.out.before_dispatch(c,"not-a-harness-row"))
            c.commit()
        self.assertEqual(self.state(),"rejected")

    def test_finished_result_can_deliver_after_execution_budget_within_ttl(self):
        self.commit(); self.now=1121
        with sqlite3.connect(self.store.path,isolation_level=None) as c:
            c.execute("BEGIN IMMEDIATE")
            self.assertTrue(self.out.before_dispatch(c,"out-1"))
            c.execute("UPDATE outbox SET state='sending' WHERE id='out-1'")
            c.commit()

    def test_bound_payload_change_prevents_dispatch(self):
        self.commit()
        with sqlite3.connect(self.store.path,isolation_level=None) as c:
            c.execute("UPDATE outbox SET body='altered reply' WHERE id='out-1'")
            c.execute("BEGIN IMMEDIATE")
            self.assertFalse(self.out.before_dispatch(c,"out-1"));c.commit()
        self.assertEqual(self.state(),"rejected")

    def test_scope_and_same_database_guards(self):
        with self.store.transaction_guard(self.lease.fence) as c:
            self.enqueue(c,self.lease.run)
            c.execute("UPDATE outbox SET chat='someone-else' WHERE id='out-1'")
            with self.assertRaisesRegex(RuntimeError,"OUTBOX_SCOPE_MISMATCH"):
                self.out.bind(c,self.lease.run,"out-1")
        with sqlite3.connect(Path(self.tmp.name)/"other.sqlite",isolation_level=None) as c:
            c.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(RuntimeError,"OUTBOX_MUST_SHARE_RUN_DATABASE"):
                self.out.before_dispatch(c,"out-1")
            c.rollback()

    def test_missing_transaction_is_rejected(self):
        with sqlite3.connect(self.store.path,isolation_level=None) as c:
            with self.assertRaisesRegex(RuntimeError,"OUTBOX_TRANSACTION_REQUIRED"):
                self.out.before_dispatch(c,"out-1")
