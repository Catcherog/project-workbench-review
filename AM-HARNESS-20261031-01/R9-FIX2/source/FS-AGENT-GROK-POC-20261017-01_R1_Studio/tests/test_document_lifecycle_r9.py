"""Offline lifecycle regression over the original Store, LogicService and outbox.

The API, business records and evidence-current callback are synthetic. No model
or network call is permitted or needed for these lifecycle assertions.
"""
from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from am_conversation.documents import DocumentTools
from am_conversation.types import ConversationError
from fs_agent.config import BoundaryError
from fs_agent.doc_logic import digest
from fs_agent.document_standards import DocumentStandards
from fs_agent.feishu import SendRejected
from test_gateway import rig as gateway_rig, event


class Business:
    def __init__(self):
        self.reads=[];self.writes=[];self.receipts={}
        self.target={'id':'formal','project_id':'platform-project','node_id':'platform-node',
                     'deliverable_id':'platform-deliverable','revision':'target-v1'}
        self.settings={'targets':{'formal':{'display_name':'本项目正式章程'}}}

    def resolve(self,row,alias):
        self.reads.append(alias)
        if alias!='formal':raise BoundaryError('BUSINESS_SCOPE_DENIED')
        return dict(self.target)

    def document_identity(self,row,target):
        if target!=self.target:raise BoundaryError('TARGET_REVISION_CHANGED')
        return {'project_code':'IRAD-2099-001','doc_type':'charter'}

    def commit(self,row,target,content,content_hash,idem,guard):
        if not guard():raise BoundaryError('DOCUMENT_NOT_CURRENT')
        self.writes.append(idem)
        receipt={'target_id':target['id'],'content_hash':content_hash,
                 'object_id':'synthetic-file','url':'https://synthetic.invalid/formal'}
        self.receipts[idem]=receipt
        return receipt

    def reconcile(self,row,idem):return self.receipts.get(idem)


@pytest.fixture
def document_rig(gateway_rig):
    gateway,store,api,provider,clock=gateway_rig
    # The original generic fixture asserts on rejection; the real transport
    # reports a definite pre-send refusal, which is what this lifecycle tests.
    original_send=api.send
    def guarded_send(row,guard):
        if not guard():raise SendRejected('DELIVERY_AUTH_OR_TTL')
        return original_send(row,guard)
    api.send=guarded_send
    gateway.config=replace(gateway.config,document_logic=True)
    assert gateway.ingest(event('合成文档生命周期输入'))
    ingress=store.rows('SELECT * FROM inbox')[0]
    draft=gateway.logic.create(ingress,'charter')
    task_id=store.enqueue(ingress,'doc',acknowledgement=False)
    store.execute('INSERT INTO logic_jobs VALUES(?,?,?)',(task_id,draft['id'],draft['revision']))
    store.execute("UPDATE tasks SET state='completed',run_id=? WHERE id=?",('a'*32,task_id))
    task=store.rows('SELECT * FROM tasks WHERE id=?',(task_id,))[0]
    body='SYNTHETIC_PRIVATE_STANDARD_BODY'
    content_hash=digest(body)
    store.execute("UPDATE logic_drafts SET state='ready',content=?,content_hash=?,accepted_hash=?,target=? WHERE id=?",
        (body,content_hash,content_hash,json.dumps(Business().target,sort_keys=True),draft['id']))
    artifact=gateway.config.root/'artifacts'/(task_id+'.md');artifact.write_text(body)
    business=Business();gateway.logic.business=business
    standards=DocumentStandards(gateway.logic,{'ledger':{'url':'https://synthetic.invalid/ledger'}})
    gateway.logic.standards=standards
    state={'current':True,'checks':[]}
    def current(row,binding):
        state['checks'].append(dict(row))
        return state['current']
    gateway.logic.shared_evidence=lambda *a:pytest.fail('lifecycle guard must not recollect sources')
    gateway.logic.shared_evidence_current=current
    binding={'schema':'am-document-evidence-binding/1','project_id':'project',
        'project_code':'IRAD-2099-001','scope':[task['tenant'],task['app'],task['user'],task['chat'],''],
        'expires':clock()+600,'state_hash':'evidence-current','access_version':1,'dependencies':[],
        'ledger_evidence':{'source_id':'th2-ledger','object_id':'project','version':'ledger-v1',
                           'raw_available':True,'raw_expires_at_ms':int((clock()+600)*1000)}}
    rules={'engine':'am-doc-standards-r9','document_binding':binding,'project_id':'project'}
    store.execute('UPDATE logic_drafts SET rules=? WHERE id=?',(json.dumps(rules),draft['id']))
    store.execute('INSERT INTO amdoc_context VALUES(?,?,?)',(draft['id'],json.dumps({
        'project_code':'IRAD-2099-001','doc_type':'charter','project_type':'IRAD','level':'L1','stage':'initiation'}),clock()+600))
    store.execute('INSERT INTO amdoc_results VALUES(?,?,?,?)',(draft['id'],1,json.dumps({
        'document_binding':binding,'request':{'project_id':'project'}}),clock()+600))
    ctx=SimpleNamespace(session_id='synthetic-session',can_access_project=lambda value:value=='project')
    bridge=SimpleNamespace(service=SimpleNamespace(g=gateway),s=store,
        _current=lambda _: {'row':dict(task,body='确认采用这版并保存',created=clock())},
        authorize=lambda *a:True)
    tools=DocumentTools(bridge)
    store.execute('INSERT INTO am_conversation_documents VALUES(?,?,?,?)',
        (draft['id'],ctx.session_id,'project','event'))
    return SimpleNamespace(g=gateway,s=store,api=api,p=provider,clock=clock,row=task,
        draft_id=draft['id'],task_id=task_id,body=body,hash=content_hash,state=state,
        standards=standards,tools=tools,ctx=ctx,business=business,artifact=artifact,
        draft=lambda:store.rows('SELECT * FROM logic_drafts WHERE id=?',(draft['id'],))[0])


@pytest.mark.parametrize('section',['content','review'])
def test_expired_standard_context_cannot_bypass_content_read(document_rig,section):
    r=document_rig
    r.s.execute('UPDATE amdoc_context SET expires=? WHERE draft_id=?',(r.clock()-1,r.draft_id))
    assert r.draft()['expires']>r.clock()  # Reproduce a legacy unsynchronized row.
    assert r.standards.context(r.draft()) is None
    with pytest.raises((ConversationError,BoundaryError)):
        r.tools.read(r.ctx,{'draft_id':r.draft_id,'section':section},'read-event')
    summary=r.tools.read(r.ctx,{'draft_id':r.draft_id,'section':'summary'},'read-event')
    assert summary['drafts'][0]['evidence_current'] is False
    assert summary['drafts'][0]['requires_regeneration_for_cloud'] is True
    assert r.body not in json.dumps(summary,ensure_ascii=False)


def test_historical_context_alone_still_identifies_a_standard_draft(document_rig):
    r=document_rig
    r.s.execute('UPDATE logic_drafts SET rules=NULL WHERE id=?',(r.draft_id,))
    r.s.execute('UPDATE amdoc_context SET expires=? WHERE draft_id=?',(r.clock()-1,r.draft_id))
    assert r.g.logic.is_standard_draft(r.draft()) is True
    r.g.logic.standards=None
    with pytest.raises(BoundaryError):r.g.logic.require_current_document_evidence(r.row,r.draft())


@pytest.mark.parametrize('section',['content','review','native_sections'])
@pytest.mark.parametrize('invalidation',['expired','source_changed','module_disabled'])
def test_existing_document_view_applies_same_evidence_guard(document_rig,section,invalidation):
    from am_documents import DocumentViewsMixin
    r=document_rig
    if invalidation=='expired':
        r.s.execute('UPDATE amdoc_context SET expires=? WHERE draft_id=?',(r.clock()-1,r.draft_id))
    elif invalidation=='source_changed':r.state['current']=False
    else:r.g.logic.standards=None
    view=SimpleNamespace(g=r.g,s=r.s,owner=r.g.config.owner,
        ux_page=lambda *a,**kw:pytest.fail('stale document must not reach a rendered view'))
    with pytest.raises(BoundaryError):
        DocumentViewsMixin.ux_documents(view,r.row,{'draft':r.draft_id,'section':section})
    assert r.api.sent==[] and r.business.writes==[]


@pytest.mark.parametrize('marker',['engine','document_binding'])
def test_standard_markers_survive_missing_context(document_rig,marker):
    r=document_rig
    rules=json.loads(r.draft()['rules'])
    r.s.execute('UPDATE logic_drafts SET rules=? WHERE id=?',(json.dumps({marker:rules[marker]}),r.draft_id))
    r.s.execute('DELETE FROM amdoc_context WHERE draft_id=?',(r.draft_id,))
    assert r.g.logic.is_standard_draft(r.draft()) is True
    r.g.logic.standards=None
    with pytest.raises(BoundaryError):r.g.logic.require_current_document_evidence(r.row,r.draft())


@pytest.mark.parametrize('operation',['adopt','mount','read','resend','publish_preview','valid_job'])
def test_disabling_standards_does_not_turn_an_existing_standard_draft_into_legacy(document_rig,operation):
    r=document_rig;r.g.logic.standards=None
    before_outbox=r.s.rows('SELECT * FROM outbox')
    if operation=='valid_job':
        assert r.g.logic.valid_job({'id':r.task_id}) is False
    else:
        with pytest.raises((BoundaryError,ConversationError)):
            if operation=='adopt':r.g.logic.adopt(r.row,r.draft_id)
            elif operation=='mount':r.g.logic.mount(r.row,r.draft_id)
            elif operation=='read':r.tools.read(r.ctx,{'draft_id':r.draft_id,'section':'content'},'read-event')
            elif operation=='resend':r.tools.edit(r.ctx,{'draft_id':r.draft_id,'version':1,'operation':'resend'},'resend-event')
            else:r.tools.publish_preview(r.ctx,{'draft_id':r.draft_id,'version':1,'content_hash':r.hash,'operation':'mount'})
    assert r.business.writes==[] and r.api.sent==[]
    assert r.s.rows('SELECT * FROM outbox')==before_outbox


def test_valid_job_loads_the_real_task_for_a_local_evidence_check(document_rig):
    r=document_rig
    before=r.api.checks
    assert r.g.logic.valid_job({'id':r.task_id}) is True
    assert r.state['checks'] and r.state['checks'][-1]['app']==r.row['app']
    assert r.state['checks'][-1]['user']==r.row['user']
    assert r.api.checks==before and r.p.prompts==[]


def test_a_standard_job_without_a_real_task_row_is_not_dispatchable(document_rig):
    r=document_rig
    r.s.execute('INSERT INTO logic_jobs VALUES(?,?,?)',('missing-task',r.draft_id,1))
    assert r.g.logic.valid_job({'id':'missing-task'}) is False


def test_source_change_after_queueing_blocks_real_outbox_delivery(document_rig):
    r=document_rig
    assert r.g.logic.valid_job({'id':r.task_id}) is True
    outbox_id=r.s.add_outbox(r.row,artifact=str(r.artifact),task_id=r.task_id,private=True)
    r.state['current']=False
    assert r.g.logic.valid_job({'id':r.task_id}) is False
    assert r.g.deliver_one() is True
    saved=r.s.rows('SELECT state FROM outbox WHERE id=?',(outbox_id,))[0]
    assert saved['state']=='rejected' and r.api.sent==[]


def test_a_current_standard_draft_can_be_delivered(document_rig):
    r=document_rig
    outbox_id=r.s.add_outbox(r.row,artifact=str(r.artifact),task_id=r.task_id,private=True)
    assert r.g.deliver_one() is True
    assert r.api.sent and r.api.sent[0]['id']==outbox_id
    assert r.s.rows('SELECT state FROM outbox WHERE id=?',(outbox_id,))[0]['state']=='sent'


def test_plain_legacy_document_keeps_read_adopt_and_delivery_paths(document_rig):
    r=document_rig
    r.s.execute('DELETE FROM amdoc_context WHERE draft_id=?',(r.draft_id,))
    r.s.execute('DELETE FROM amdoc_results WHERE draft_id=?',(r.draft_id,))
    r.s.execute('UPDATE logic_drafts SET rules=NULL,accepted_hash=NULL WHERE id=?',(r.draft_id,))
    r.g.logic.standards=None
    assert r.g.logic.is_standard_draft(r.draft()) is False
    assert r.g.logic.require_current_document_evidence(r.row,r.draft()) is True
    assert r.tools.read(r.ctx,{'draft_id':r.draft_id,'section':'content'},'read-event')['drafts'][0]['content']==r.body
    r.g.logic.adopt(r.row,r.draft_id)
    assert r.draft()['accepted_hash']==r.hash
    assert r.g.logic.valid_job({'id':r.task_id}) is True
    r.s.add_outbox(r.row,artifact=str(r.artifact),task_id=r.task_id,private=True)
    assert r.g.deliver_one() is True and len(r.api.sent)==1


def test_delivery_discovery_rejects_an_old_revision_without_read_or_write(document_rig):
    r=document_rig
    before=r.s.rows('SELECT * FROM logic_drafts')
    with pytest.raises(ConversationError,match='VERSION_CHANGED'):
        r.tools.delivery(r.ctx,{'draft_id':r.draft_id,'version':2},'delivery-event')
    assert r.business.reads==[] and r.business.writes==[]
    assert r.s.rows('SELECT * FROM logic_drafts')==before


def test_delivery_discovery_uses_the_exact_revision_and_is_read_only(document_rig):
    r=document_rig
    before=r.s.rows('SELECT * FROM logic_drafts')
    result=r.tools.delivery(r.ctx,{'draft_id':r.draft_id,'version':1},'delivery-event')
    assert result['read_only'] is True and result['version']==1
    assert result['state']=='available' and result['targets']==[r.business.target]
    assert result['adoption_recorded'] is True
    assert '本项目正式章程' in result['message']
    assert r.business.writes==[] and r.api.sent==[] and not r.s.rows('SELECT * FROM outbox')
    assert r.s.rows('SELECT * FROM logic_drafts')==before
