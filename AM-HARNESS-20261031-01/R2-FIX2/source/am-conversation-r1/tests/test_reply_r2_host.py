"""Current host + durable read boundary, synthetic data, no external calls."""
import json
import sqlite3
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace

from am_conversation.legacy import LegacyConversationBridge
from am_conversation.rewrite_host import _write, _ObservedCoordinator
from am_conversation.types import ConversationError, canonical
from am_reply.compiler import build_legacy_contract
from am_reply.contracts import fallback_text
from test_legacy import FakeService, call, answer


class R2HostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = FakeService(Path(self.temp.name))
        self.service.projects[0]['人员与职责']='AR101张甲 | 测试\nAR102李乙 | 采购'
        self.bridge = LegacyConversationBridge(self.service, {'enabled':True,
            'output_rewrite':{'mode':'off','validation_enabled':True}})
        self.finalizer = self.bridge.agent.output_finalizer
        self.original_complete = self.service.g.provider.complete
        self.proposals = []
        def complete(prompt, **options):
            if 'contract_fingerprint' not in options.get('json_schema',{}).get('properties',{}):
                return self.original_complete(prompt,**options)
            schema=options['json_schema']; self.proposals.append(options)
            payload=json.loads(prompt.split('数据如下：\n',1)[1])
            candidate={'contract_fingerprint':payload['contract_fingerprint'],'lead_in':'record',
                'groups':[{'joiner':'semicolon','items':[{'claim_id':c['claim_id'],'variant':min(1,len(c['variants'])-1)} for c in payload['claims']]}]}
            return SimpleNamespace(text=json.dumps(candidate,ensure_ascii=False))
        self.service.g.provider.complete=complete

    def tearDown(self):
        self.bridge.close(); self.service.s.conn.close(); self.temp.cleanup()

    def control(self, mode='enforce', capture=True):
        _write(self.finalizer.directory/'control.json',{'mode':mode,'capture':capture,'expires_at':time.time()+300})

    def execute(self, actor='ou_owner', text='需求1谁负责？'):
        row=self.service.inbox(actor,text)
        self.service.g.provider.outputs=[call('read_project',{'project_id':'project-a'}), answer('人员分工请看台账。')]
        out=self.bridge.process(row)
        return row,out,self.service.s.rows('SELECT * FROM outbox WHERE id=?',(out,))[0]['body']

    def test_enforce_persists_final_and_replays_without_models(self):
        self.control(); row,out,body=self.execute()
        self.assertIn('AR101张甲',body);self.assertIn('AR102李乙',body)
        self.assertEqual(len(self.proposals),1)
        count=len(self.service.g.provider.calls)
        self.assertEqual(self.bridge.process(row),out)
        self.assertEqual(len(self.proposals),1); self.assertEqual(len(self.service.g.provider.calls),count)
        capture=json.loads(next((self.finalizer.directory/'captures').glob('*.json')).read_text())
        self.assertEqual(capture['final_text'],body)
        self.assertTrue(capture['candidate_adopted'])

    def test_shadow_saves_original_with_private_candidate(self):
        self.control('shadow');row,out,body=self.execute()
        self.assertEqual(body,'人员分工请看台账。');self.assertEqual(len(self.proposals),1)
        capture=json.loads(next((self.finalizer.directory/'captures').glob('*.json')).read_text())
        self.assertEqual(capture['disposition'],'shadow_accepted')
        self.assertFalse(capture['candidate_adopted']);self.assertIn('AR101',capture['candidate_after_checks'])

    def test_member_keeps_original_without_capture_or_rewrite(self):
        self.control();row,out,body=self.execute('ou_member')
        self.assertEqual(body,'人员分工请看台账。');self.assertFalse(self.proposals)
        self.assertFalse(list((self.finalizer.directory/'captures').glob('*.json')))

    def test_default_off_adds_no_call(self):
        self.execute();self.assertFalse(self.proposals)

    def test_expired_or_public_control_is_ignored(self):
        path=self.finalizer.directory/'control.json'
        _write(path,{'mode':'enforce','capture':True,'expires_at':time.time()-1})
        self.assertEqual(self.finalizer.control()['mode'],'off')
        self.control();path.chmod(0o644)
        self.assertEqual(self.finalizer.control()['mode'],'off')

    def test_private_route_misses_before_read_event_claim(self):
        self.control(); row=self.service.inbox('ou_owner','需求1谁负责？')
        class Trap:
            def prepare(*args):raise AssertionError('must go to durable queue')
            def consume(*args):raise AssertionError('must go to durable queue')
        self.bridge.agent.fastpath=Trap()
        with self.bridge.request_context(row) as ctx:
            self.assertIsNone(self.bridge.agent.handle_fastpath(ctx,row['id'],row['body']))
        with sqlite3.connect(self.bridge.store._path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM conversation_events').fetchone()[0],0)

    def test_control_and_provenance_do_not_route(self):
        self.control();row=self.service.inbox('ou_owner')
        with self.bridge.request_context(row) as ctx:
            for question in ('原文给我','需求1采集时间','发给李工','需求1来源是什么'):
                self.assertFalse(self.finalizer.route_to_model_lane(ctx,question))

    def test_cancel_checkpoint_after_rewriter_blocks_persistence(self):
        self.control()
        def checkpoint(ctx,phase,args):
            if phase=='after_output_rewrite':raise ConversationError('RUN_CANCELLED')
        self.bridge.agent.lifecycle=checkpoint
        with self.assertRaisesRegex(ConversationError,'RUN_CANCELLED'):self.execute()
        self.assertEqual(self.service.s.rows('SELECT * FROM outbox'),[])

    def test_source_revoke_during_rewrite_blocks_fallback(self):
        self.control();complete=self.service.g.provider.complete
        def revoked(prompt,**options):
            result=complete(prompt,**options)
            if 'contract_fingerprint' in options.get('json_schema',{}).get('properties',{}):self.service.revoked=True
            return result
        self.service.g.provider.complete=revoked
        with self.assertRaisesRegex(ConversationError,'QUERY_IDENTITY_REVOKED'):self.execute()
        self.assertFalse(self.service.s.rows('SELECT * FROM outbox'))

    def test_source_blocks_are_not_llm_success(self):
        self.control();row,out,body=self.execute(text='需求1项目进展是什么？')
        self.assertFalse(self.proposals)
        capture=json.loads(next((self.finalizer.directory/'captures').glob('*.json')).read_text())
        self.assertEqual(capture['disposition'],'source_projection');self.assertFalse(capture['candidate_adopted'])

    def test_incomplete_snapshot_caveat_and_all_ar_codes_retained(self):
        row=self.service.inbox('ou_owner')
        with self.bridge.request_context(row) as ctx:
            project=self.bridge.projects.read_project(ctx,'project-a');project['snapshot']['complete']=False
            contract=build_legacy_contract(ctx,'e','需求1谁负责？','',[canonical(project)])
            text=fallback_text(contract)
            self.assertIn('AR101张甲',text)
            self.assertIn('另有资料尚待更新或核对',text)

    def test_observer_forwards_exact_existing_coordinator_and_start(self):
        calls=[]
        original=SimpleNamespace(complete=lambda prompt,**kw:(calls.append(prompt),kw['on_start'](123),SimpleNamespace(text='ok',elapsed=.1,usage={}))[2])
        observed=_ObservedCoordinator(original);self.assertEqual(observed.complete('synthetic').text,'ok')
        self.assertIs(observed.original,original)
        self.assertEqual([observed.usage[k] for k in ('attempted','started','completed')],[1,1,1])

    def test_positive_review_duties_keep_parallel_ids_and_exact_relationship(self):
        row=self.service.inbox('ou_owner')
        with self.bridge.request_context(row) as ctx:
            project=self.bridge.projects.read_project(ctx,'project-a')
            project['fields']['人员与职责']='AR101/AR201张甲｜推进/研发\nAR102李乙｜审核'
            contract=build_legacy_contract(ctx,'e','需求1谁负责？','',[canonical(project)])
            self.assertEqual(contract.origin,'ledger_role_projection')
            self.assertEqual(contract.claims[0].variants,('AR101/AR201张甲负责推进/研发','推进/研发由AR101/AR201张甲负责'))
            self.assertEqual(contract.claims[1].variants,('AR102李乙负责审核','审核由AR102李乙负责'))
            project['fields']['人员与职责']+='，仅在方案批准后生效'
            contract=build_legacy_contract(ctx,'e','需求1谁负责？','',[canonical(project)])
            self.assertEqual(contract.origin,'ledger_source_block')
