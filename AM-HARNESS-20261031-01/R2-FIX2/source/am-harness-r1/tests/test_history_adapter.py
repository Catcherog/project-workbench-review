from pathlib import Path
import sqlite3
import tempfile
import unittest
from am_conversation.store import ConversationStore
from am_conversation.types import AccessContext
from am_harness.am_adapter import engine_event_id
from am_harness.effects import FencedOutbox
from am_harness.history_adapter import FencedHistoryStore
from am_harness.store import DurableStore, Scope


class HistoryAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.original=ConversationStore(root/"conversation.sqlite",clock=lambda:1000)
        self.tasks=DurableStore(root/"tasks.sqlite",clock=lambda:1000)
        self.ctx=AccessContext("t","a","u","c",content_expires_at=1600)
        self.scope=Scope.from_context(self.ctx)
        self.filtered=FencedHistoryStore(self.original,self.tasks)

    def tearDown(self):self.original.close();self.tmp.cleanup()

    def run_and_record(self):
        self.tasks.submit(self.scope,"event","question",deadline=1120,expires_at=1600)
        lease=self.tasks.claim("worker");event=engine_event_id(lease.run)
        self.original.claim_event(self.ctx,event,"question")
        self.original.finish_event(self.ctx,event,{"event_id":event,"text":"old answer"})
        return lease

    def test_cancel_after_original_history_commit_does_not_feed_old_answer(self):
        lease=self.run_and_record()
        self.tasks.cancel(self.scope,"cancel",lease.run.id)
        self.assertEqual(len(self.original.history(self.ctx)),2)
        self.assertEqual(self.filtered.history(self.ctx),[])
        self.assertFalse(self.tasks.finish(lease))

    def test_generated_but_unverified_answer_is_not_a_delivered_statement(self):
        lease=self.run_and_record();self.tasks.finish(lease,result={"text":"old answer"})
        self.assertEqual(self.filtered.history(self.ctx),[{"role":"user","content":"question"}])
        FencedOutbox(self.tasks,binding_verifier=lambda *a:None)
        with sqlite3.connect(self.tasks.path) as conn:
            conn.execute("""INSERT INTO am_harness_outbox
                (outbox_id,run_id,scope_key,revision,cancel_epoch,lease_generation,payload_hash,state,receipt_id,verified)
                VALUES('out',?,?,?,?,?,'fixture','sent','receipt',1)""",
                (lease.run.id,self.scope.key,lease.run.revision,lease.run.cancel_epoch,lease.generation))
        self.assertEqual(len(self.filtered.history(self.ctx)),2)

    def test_non_harness_history_and_write_methods_keep_original_contract(self):
        self.filtered.claim_event(self.ctx,"ordinary-feishu-event","normal question")
        self.filtered.finish_event(self.ctx,"ordinary-feishu-event",{"text":"normal answer"})
        self.assertEqual(self.filtered.history(self.ctx),self.original.history(self.ctx))
        other=AccessContext("t","a","u","different-chat")
        self.assertEqual(self.filtered.history(other),[])
