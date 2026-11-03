"""Synthetic shared-store/document contracts; no Qwen or Feishu calls are made."""
from __future__ import annotations

import copy
import json
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from am_doc_engine.models import (AccessContext, DraftDocument, DraftField, DraftRequest, Evidence,
    FactSnapshot, FieldRule, SectionSpec, SourceAsset, TemplateProfile, fingerprint, now_iso)
from am_doc_engine.host_bridge import BridgeResult
from am_outcome.evidence import EvidenceBundle
from fs_agent.config import BoundaryError
from fs_agent.doc_logic import digest
from fs_agent.document_delivery import discover_targets, render_targets
from fs_agent.document_evidence import coverage_issues, require_current
from fs_agent.document_mapping import map_facts
from fs_agent.document_standards import DocumentStandards
from fs_agent.logic_service import SCHEMA
from fs_agent.store import Store, scope_of


ROW = {'id': 'task', 'run_id': '0123456789abcdef0123456789abcdef', 'tenant': 'tenant', 'app': 'app', 'user': 'owner',
       'chat': 'chat', 'chat_type': 'p2p', 'expires': 900.0}
PROJECT = {'key': 'project', 'title': 'IRAD-2099-001 示例', 'source_revision': 'ledger-r1'}


def binding(**changes):
    return dict({'schema': 'am-document-evidence-binding/1', 'project_id': 'project',
        'project_code': 'IRAD-2099-001', 'scope': ['tenant', 'app', 'owner', 'chat', ''],
        'expires': 500.0, 'state_hash': 'state-one', 'access_version': 1, 'dependencies': [],
        'ledger_evidence': {'source_id':'th2-ledger','object_id':'project','version':'ledger:1:body-hash',
            'raw_expires_at_ms':500_000,'raw_available':True}}, **changes)


def fact(**changes):
    return dict({'fact_id': 'f-one', 'subject_id': 'project', 'field': 'progress',
        'value': '可安排测试', 'assertion_type': 'forecast', 'authority': 'source_confirmed',
        'business_state': 'unconfirmed', 'polarity': 'conditional',
        'condition': '样机到货', 'attribution': '工程师反馈', 'time_scope': 'next_week',
        'evidence': {'source_id': 'chat-source', 'object_id': 'message-one', 'version': 'message-v3',
            'quote': '工程师反馈：若样机到货。预计下周可安排测试，尚未完成验收。',
            'raw_available': True, 'url': 'https://example.com/message/one',
            'received_at_ms': 90_000}}, **changes)


def bundle(*, facts=None, bound=True, gaps=None, conflicts=None):
    return EvidenceBundle.build(PROJECT, scope=('tenant', 'app', 'owner', 'chat', ''),
        expires=500, information={'facts': [fact()] if facts is None else facts,
            'coverage': {'processing_pending': False, 'needs_refresh_or_review': False},
            'gaps': gaps or [], 'conflicts': conflicts or []},
        document_binding=binding() if bound else None)


def profile(*, decision=False):
    return TemplateProfile('tenant', 'template', 'v1', 'rules-1', 'change', '合成测试模板',
        ('IRAD:L1',), ('change',), (SectionSpec('section', '进展'),),
        (FieldRule('field', 'section', '审批结论' if decision else '进展', ('slot.field',),
            '仅使用已读取依据', ('template-source',), required=True,
            accepted_states=('confirmed',) if decision else ('confirmed', 'reported', 'proposed'),
            semantics=('actual', 'decision') if decision else ('actual', 'baseline', 'forecast', 'proposal', 'decision')),
        ), (SourceAsset('template-source', 'template', 'https://example.com/template', 'v1', '进展：'),),
        status='effective', effective_at='2026-01-01T00:00:00Z', activation_ref='catalog:1',
        allowed_actor_ids=('owner',))


def map_source(source, *, decision=False, quotes=None):
    selected = quotes or [source['segments'][0]['original']]
    session = SimpleNamespace(complete_json=lambda *a: {'matches': [
        {'field_id': 'field', 'source_id': source['id'], 'locator': source['segments'][0]['id'], 'quote': q}
        for q in selected]})
    return map_facts(profile(decision=decision), project={'id': 'project', 'title': PROJECT['title'], 'code': 'IRAD-2099-001'},
        sources=[source], access=AccessContext('tenant', 'owner', ('project',)), session=session,
        source_uri='https://example.com/ledger', source_revision='ledger-r1', supplied_type='IRAD')


def test_mapping_keeps_true_origin_quote_and_qualifiers_without_authority_promotion():
    source=bundle().document_source(uri='https://example.com/ledger')
    mapped=map_source(source, quotes=['可安排测试'])
    evidence=next(e for e in mapped.evidence if e.key == 'slot.field')
    assert evidence.source_id == 'chat-source' and evidence.source_revision == 'message-v3'
    assert evidence.source_uri == 'https://example.com/message/one'
    assert evidence.locator == 'message-one#claim=f-one'
    assert evidence.value == fact()['evidence']['quote']
    assert evidence.state == 'reported' and evidence.semantic == 'forecast'
    assert evidence.qualifiers['condition'] == '样机到货'
    assert evidence.qualifiers['attribution'] == '工程师反馈'
    assert evidence.qualifiers['business_state'] == 'unconfirmed'


def test_multiple_substrings_of_same_quote_do_not_duplicate_evidence():
    source=bundle().document_source(uri='https://example.com/ledger')
    mapped=map_source(source, quotes=['可安排测试', '尚未完成验收'])
    assert len([e for e in mapped.evidence if e.key == 'slot.field']) == 1


def test_source_confirmation_alone_cannot_fill_an_approval_only_field():
    source=bundle(facts=[fact(assertion_type='reported')]).document_source(uri='https://example.com/ledger')
    assert not [e for e in map_source(source, decision=True).evidence if e.key == 'slot.field']


def test_explicit_business_confirmation_preserves_its_distinct_semantics():
    approved=fact(assertion_type='decision', business_state='approved')
    approved['evidence']=dict(approved['evidence'],quote='审批系统记录：已批准按本方案实施。')
    source=bundle(facts=[approved]).document_source(uri='https://example.com/ledger')
    mapped=map_source(source, decision=True)
    e=next(e for e in mapped.evidence if e.key == 'slot.field')
    assert e.state == 'confirmed' and e.semantic == 'decision'
    assert e.qualifiers['source_authority'] == 'source_confirmed'


def test_an_upload_cannot_supply_its_own_trusted_business_state():
    source=bundle(facts=[fact(assertion_type='decision', business_state='approved')]).document_source(uri='https://example.com/ledger')
    source['provenance']='user_input'
    assert not [e for e in map_source(source, decision=True).evidence if e.key == 'slot.field']


def test_expired_raw_text_is_not_reconstructed_from_retained_value():
    stale=fact(); stale['evidence']=dict(stale['evidence'], raw_available=False, quote=None)
    source=bundle(facts=[stale]).document_source(uri='https://example.com/ledger')
    assert source['segments'] == [] and source['read_status'] == 'partial'
    assert source['gaps'][0]['kind'] == 'document_raw_evidence_unavailable'
    assert '可安排测试' not in json.dumps(source, ensure_ascii=False)
    assert coverage_issues(source)[0].severity == 'warning'


def test_foreign_subject_is_a_gap_not_a_project_fact():
    source=bundle(facts=[fact(subject_id='foreign')]).document_source(uri='https://example.com/ledger')
    assert source['segments'] == []
    assert source['gaps'][0]['kind'] == 'document_subject_mismatch'


@pytest.mark.parametrize('ledger_evidence',[
    None,
    {'source_id':'th2-ledger','object_id':'project','version':'old','raw_expires_at_ms':99_000,'raw_available':False},
    {'source_id':'th2-ledger','object_id':'project','version':'old','raw_expires_at_ms':99_000,'raw_available':True},
    {'source_id':'th2-ledger','object_id':'other','version':'v1','raw_expires_at_ms':500_000,'raw_available':True},
])
def test_cached_ledger_fields_cannot_reintroduce_unavailable_raw_evidence(ledger_evidence):
    project=dict(PROJECT, fields={'项目进展':'不应重新暴露的过期台账正文'},项目进展='同样不能回退的顶层正文')
    bound=binding(ledger_evidence=ledger_evidence)
    built=EvidenceBundle.build(project,scope=bound['scope'],expires=bound['expires'],information={'facts':[]},document_binding=bound)
    source=built.document_source(uri='https://example.com/ledger')
    assert built.data['claims']==[] and source['segments']==[]
    assert source['gaps']==[{'kind':'document_ledger_evidence_unavailable','source_id':'th2-ledger'}]
    assert '过期台账正文' not in json.dumps(built.data,ensure_ascii=False)
    assert '顶层正文' not in json.dumps(built.data,ensure_ascii=False)


def test_bound_ledger_quotes_use_the_verified_object_version_and_retention():
    project=dict(PROJECT,项目进展='本周继续测试')
    bound=binding()
    built=EvidenceBundle.build(project,scope=bound['scope'],expires=bound['expires'],information={'facts':[]},document_binding=bound)
    claim=built.data['claims'][0]
    assert claim['source']['version']=='ledger:1:body-hash'
    assert claim['source']['raw_expires_at_ms']==500_000
    assert claim['source']['raw_available'] is True
    assert claim['source']['quote']=='项目进展：本周继续测试'


def test_unbound_legacy_query_contract_keeps_its_recorded_fields():
    built=EvidenceBundle.build(dict(PROJECT,项目进展='原查询字段'),scope=['tenant','app','owner','chat',''],expires=900)
    assert built.data['claims'][0]['value']=='原查询字段'
    assert 'document_binding' not in built.data
    assert 'raw_available' not in built.data['claims'][0]['source']
    assert 'quote' not in built.data['claims'][0]['source']


def test_conflicts_remain_visible_even_when_one_candidate_was_selected():
    source=bundle(conflicts=[{'field': 'progress', 'fact_ids': ['f-one', 'f-two']}]).document_source(uri='https://example.com/ledger')
    assert source['read_status'] == 'partial'
    assert any(g['kind']=='document_fact_conflict' for g in source['gaps'])
    assert coverage_issues(source)[0].code == 'shared_evidence_incomplete'


@pytest.mark.parametrize('change,code', [
    ({'scope': ['tenant','app','other','chat','']}, 'SCOPE_CHANGED'),
    ({'project_id': 'other'}, 'PROJECT_CHANGED'),
    ({'expires': 99}, 'EXPIRED'),
    ({'expires': float('inf')}, 'EXPIRED'),
    ({'schema': 'unbound'}, 'REGENERATE_REQUIRED'),
])
def test_binding_rejects_wrong_identity_or_expiry_before_host_callback(change, code):
    calls=[]
    with pytest.raises(BoundaryError, match=code):
        require_current(ROW, binding(**change), lambda *a:calls.append(a) or True,
            now=100, project_code='IRAD-2099-001', project_id='project')
    assert not calls


def test_stale_binding_requires_literal_true_from_host():
    with pytest.raises(BoundaryError, match='EVIDENCE_CHANGED'):
        require_current(ROW, binding(), lambda *a:{'current': False}, now=100)


def document_host(tmp_path, *, bound=True, current=True, state='ready'):
    store=Store(tmp_path/'document.sqlite3', clock=lambda:100)
    with store.lock:store.conn.executescript(SCHEMA)
    gateway=SimpleNamespace(config=SimpleNamespace(owner='owner',app_id='app',tenant_key='tenant'),
        authorized=lambda row:True)
    logic=SimpleNamespace(g=gateway,s=store,business=SimpleNamespace(),shared_evidence=lambda *a:(PROJECT,bundle()),
        shared_evidence_current=lambda *a:current)
    standards=DocumentStandards(logic, {'ledger':{'url':'https://example.com/ledger'},'output_folder':'folder'})
    content='已有草稿';rules={'engine':'am-doc-standards-r9','project_id':'project'}
    payload={'request':{'project_id':'project'}}
    if bound:rules['document_binding']=binding();payload['document_binding']=binding()
    store.execute('INSERT INTO logic_drafts(id,scope,revision,state,document_type,sources,answers,rules,content,content_hash,expires) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
        ('draft',scope_of(ROW),1,state,'change','[]','{}',json.dumps(rules),content,digest(content),900))
    store.execute('INSERT INTO amdoc_context VALUES(?,?,?)',('draft',json.dumps({'doc_type':'change','project_code':'IRAD-2099-001','project_type':'IRAD','level':'L1','stage':'change'}),900))
    store.execute('INSERT INTO amdoc_results VALUES(?,?,?,?)',('draft',1,json.dumps(payload),900))
    return standards, store, store.rows('SELECT * FROM logic_drafts')[0]


def test_ready_cache_without_binding_requires_regeneration_and_preserves_draft(tmp_path):
    standards,store,draft=document_host(tmp_path,bound=False)
    try:
        with pytest.raises(BoundaryError,match='REGENERATE_REQUIRED'):
            standards.prepare(ROW,draft,{'revision':1},time.monotonic()+10,None,[])
        assert store.rows('SELECT content,revision,accepted_hash FROM logic_drafts') == [
            {'content':'已有草稿','revision':1,'accepted_hash':None}]
    finally:store.close()


def test_ready_cache_rechecks_current_evidence_and_returns_shortest_expiry(tmp_path):
    standards,store,draft=document_host(tmp_path)
    try:
        content,_,expires=standards.prepare(ROW,draft,{'revision':1},time.monotonic()+10,None,[])
        assert content=='已有草稿' and expires==500
        standards.logic.shared_evidence_current=lambda *a:False
        with pytest.raises(BoundaryError,match='EVIDENCE_CHANGED'):
            standards.prepare(ROW,draft,{'revision':1},time.monotonic()+10,None,[])
    finally:store.close()


def test_stale_publication_stops_before_cloud_construction(tmp_path,monkeypatch):
    standards,store,draft=document_host(tmp_path,current=False)
    calls=[]
    monkeypatch.setattr('fs_agent.document_standards.OwnerNativeDocs',lambda *a,**k:calls.append('cloud'))
    try:
        with pytest.raises(BoundaryError,match='EVIDENCE_CHANGED'):
            standards.native_action_result(ROW,draft,'保存云文档')
        assert calls==[] and store.rows('SELECT accepted_hash FROM logic_drafts')[0]['accepted_hash'] is None
    finally:store.close()


def test_regeneration_can_validate_its_target_without_reusing_old_fact_binding(tmp_path):
    standards,store,draft=document_host(tmp_path,current=False,state='collecting')
    standards.logic.business=SimpleNamespace(document_identity=lambda *a:{'project_code':'IRAD-2099-001','doc_type':'change'})
    try:
        standards.validate_target(ROW,draft,{'id':'formal'})
        with pytest.raises(BoundaryError,match='EVIDENCE_CHANGED'):
            standards.validate_target(ROW,dict(draft,state='ready'),{'id':'formal'})
    finally:store.close()


def prepare_fixture(tmp_path,monkeypatch,*,invalidate_at_composition=False):
    standards,store,draft=document_host(tmp_path,state='collecting')
    state={'current':True}
    standards.logic.shared_evidence_current=lambda *a:state['current']
    standards.g.provider=SimpleNamespace(complete=lambda *a,**k:pytest.fail('synthetic test must not call a model'))
    standards.cfg.update(catalog={'url':'https://example.com/catalog'},hosts=['example.com'],
        template_codes={'change':'T1'},required_sources=[{'id':'instructions','url':'https://example.com/instructions','role':'instruction'}])
    native={'revision':'v1','text':'合成模板','read_state':'complete','title':'合成模板','hash':'native','pages':1}
    class Docs:
        def __init__(self,*a,**k):pass
        def resolve(self,url,hosts):return url
        def read(self,url):return dict(native)
    class Catalog:
        def __init__(self,*a,**k):pass
        def read(self):
            return {'revision':'catalog-v1','rows':[{'文件编号':'T1','模板状态':['现行'],'record_id':'record',
                '来源链接':'https://example.com/template','模板名称':'合成模板','更新时间':'2026-01-01T00:00:00Z'}]}
    p=profile()
    stamp=now_iso()
    evidence=Evidence('e-one','tenant','project','slot.field','工程师反馈：尚未完成验收。','actual','reported',
        'chat-source','https://example.com/message/one','message-v3','message-one',stamp,allowed_actor_ids=('owner',))
    snapshot=FactSnapshot('snapshot',stamp,(evidence,))
    document=DraftDocument('document','tenant','project','change','合成草稿','template','v1',p.content_hash,
        'rules-1','snapshot',snapshot.content_hash,stamp,1,p.sections,
        (DraftField('field','待核实反馈：尚未完成验收。',('e-one',)),),(),(),'draft_complete',stamp)
    def compose(**kwargs):
        assert kwargs['store'].conn is store.conn
        kwargs['ensure_current']()
        kwargs['store'].claim('synthetic-run',snapshot.content_hash)
        if invalidate_at_composition:state['current']=False
        return BridgeResult(document,'合成草稿内容','已形成草稿','synthetic',0,{'issues':[]})
    monkeypatch.setattr('fs_agent.document_standards.OwnerNativeDocs',Docs)
    monkeypatch.setattr('fs_agent.document_standards.OwnerCatalog',Catalog)
    monkeypatch.setattr('fs_agent.document_standards.policy_asset',lambda read:SourceAsset('policy','instruction','am://policy','1','保留事实限定'))
    monkeypatch.setattr('fs_agent.document_standards.blueprint',lambda *a,**k:(p,[]))
    monkeypatch.setattr('fs_agent.document_standards.map_facts',lambda *a,**k:snapshot)
    monkeypatch.setattr('fs_agent.document_standards.prepare_am_document',compose)
    return standards,store,draft


def test_new_generation_persists_the_shortest_evidence_expiry_in_existing_store(tmp_path,monkeypatch):
    standards,store,draft=prepare_fixture(tmp_path,monkeypatch)
    try:
        content,_,expires=standards.prepare(ROW,draft,{'revision':1},time.monotonic()+10,None,[])
        assert content=='合成草稿内容' and expires==500
        for table in ('logic_drafts','amdoc_context','amdoc_results','amdoc_run_bindings'):
            assert store.rows('SELECT expires FROM '+table)[0]['expires']==500
        payload=json.loads(store.rows('SELECT payload FROM amdoc_results')[0]['payload'])
        assert payload['document_binding']==binding()
    finally:store.close()


def test_evidence_change_during_generation_cannot_replace_current_draft(tmp_path,monkeypatch):
    standards,store,draft=prepare_fixture(tmp_path,monkeypatch,invalidate_at_composition=True)
    try:
        with pytest.raises(BoundaryError,match='EVIDENCE_CHANGED'):
            standards.prepare(ROW,draft,{'revision':1},time.monotonic()+10,None,[])
        stored=store.rows('SELECT content,state,revision FROM logic_drafts')[0]
        assert stored=={'content':'已有草稿','state':'collecting','revision':1}
    finally:store.close()


def test_incomplete_shared_coverage_is_saved_as_a_draft_with_visible_gaps(tmp_path,monkeypatch):
    standards,store,draft=prepare_fixture(tmp_path,monkeypatch)
    standards.logic.shared_evidence=lambda *a:(PROJECT,bundle(gaps=[{'kind':'analysis_pending'}]))
    try:
        standards.prepare(ROW,draft,{'revision':1},time.monotonic()+10,None,[])
        payload=json.loads(store.rows('SELECT payload FROM amdoc_results')[0]['payload'])
        assert payload['document']['state']=='draft_with_gaps'
        assert any(i['code']=='shared_evidence_incomplete' for i in payload['document']['issues'])
        assert payload['information_gaps']==[{'kind':'analysis_pending'}]
    finally:store.close()


def targets(*entries):
    config={alias:{'kind':kind,'code':code} for alias,kind,code in entries}
    resolutions=[];writes=[]
    def resolve(row,alias):
        resolutions.append(alias)
        return {'id':alias,'project_id':'platform-project','node_id':'node','deliverable_id':alias,'revision':'v1'}
    def identity(row,target):
        value=config[target['id']]
        if value['kind']=='unavailable':raise BoundaryError('BUSINESS_CALL_FAILED')
        return {'project_code':value['code'],'doc_type':value['kind']}
    return SimpleNamespace(settings={'targets':config},resolve=resolve,document_identity=identity,
        commit=lambda *a:writes.append(a)), resolutions, writes


def test_official_target_discovery_never_reuses_a_test_or_other_project_target():
    business,read,writes=targets(('test','test','IRAD-2099-001'),('other','charter','IRAD-2099-002'))
    result=discover_targets(business,ROW,project_code='IRAD-2099-001',doc_type='charter',guard=lambda:True,deadline=time.monotonic()+10)
    assert result['state']=='not_configured' and result['targets']==[]
    assert len(read)==2 and writes==[]


def test_multiple_exact_targets_are_returned_for_selection_without_a_write():
    business,_,writes=targets(('one','closure','IRAD-2099-001'),('two','closure','IRAD-2099-001'))
    result=discover_targets(business,ROW,project_code='IRAD-2099-001',doc_type='closure',guard=lambda:True,deadline=time.monotonic()+10)
    assert result['state']=='ambiguous' and len(result['targets'])==2 and writes==[]


def test_target_read_failure_is_unresolved_not_missing():
    business,_,writes=targets(('one','unavailable','IRAD-2099-001'))
    result=discover_targets(business,ROW,project_code='IRAD-2099-001',doc_type='change',guard=lambda:True,deadline=time.monotonic()+10)
    assert result['state']=='unresolved' and result['unresolved']==['one'] and writes==[]


def test_target_display_does_not_require_the_user_to_remember_platform_ids():
    business,_,_=targets(('opaque-alias','closure','IRAD-2099-001'))
    result=discover_targets(business,ROW,project_code='IRAD-2099-001',doc_type='closure',guard=lambda:True,deadline=time.monotonic()+10)
    message=render_targets(result)
    assert '结项报告正式目标' in message
    assert all(value not in message for value in ('opaque-alias','platform-project','deliverable_id','node_id'))
    assert result['targets'][0]['id']=='opaque-alias'
