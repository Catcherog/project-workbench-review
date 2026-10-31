import copy
import json
import time
from types import SimpleNamespace

import pytest
from am_doc_engine.models import (AccessContext, SourceAsset, fingerprint)
from fs_agent.config import BoundaryError
from fs_agent.document_mapping import blueprint, map_facts, admit_project_input
from fs_agent.document_native import NativePublisher, replacements, verify_exact
from fs_agent.document_sources import NativeDocs, OwnerCatalog, OwnerNativeDocs, token_from_url
from fs_agent.document_standards import HostRunStore, SharedProvider, ProviderControlError, DocumentStandards, deferred_question_keys
from fs_agent.store import Store


def fixture_native():
    blocks=[{'block_id':'root','block_type':1,'parent_id':'','children':['name','background','title','body'],
        'page':{'elements':[{'text_run':{'content':'Template'}}]}},
        {'block_id':'name','block_type':2,'parent_id':'root','text':{'elements':[
            {'text_run':{'content':'项目名称：','text_element_style':{'bold':True}}},{'text_run':{'content':'〈项目全称〉'}}]}},
        {'block_id':'background','block_type':2,'parent_id':'root','text':{'elements':[{'text_run':{'content':'固定文字'}}]}},
        {'block_id':'title','block_type':4,'parent_id':'root','heading2':{'elements':[{'text_run':{'content':'更改原因'}}]}},
        {'block_id':'body','block_type':2,'parent_id':'root','text':{'elements':[{'text_run':{'content':''}}]}}]
    return {'token':'root','revision':1,'title':'Template','blocks':blocks,'paths':{'root':[],**{b['block_id']:[i] for i,b in enumerate(blocks[1:])}},
        'pages':1,'hash':fingerprint(blocks),'read_state':'complete','unread_blocks':[],'text':'项目名称：〈项目全称〉\n更改原因'}


def profile_and_slots():
    native=fixture_native()
    policy=SourceAsset('writing-policy','instruction','https://example.com/policy','1','缺失资料保留待补')
    template=SourceAsset('full','template','https://example.com/template','1',native['text'])
    profile,slots=blueprint(native,record={'source_url':'https://example.com/template','record_id':'rec1','title':'模板',
        'effective_at':'2026-10-30T00:00:00+00:00','activation_ref':'catalog:current'},tenant='tenant',actor='owner',
        doc_type='change',project_type='IRAD:L1',stage='change',assets=[template,policy])
    return profile,slots


class Reader(NativeDocs):
    def __init__(self,native,*,revision_changed=False,pages=None):
        super().__init__(None,lambda:True);self.native=native;self.calls=[];self.changed=revision_changed;self.pages=pages;self.metadata_calls=0
    def call(self,method,path,*,query=None,body=None):
        self.calls.append((path,query))
        if path.endswith('/blocks'):
            return self.pages[len([p for p,q in self.calls if p.endswith('/blocks')])-1] if self.pages else {'items':self.native['blocks'],'has_more':False}
        self.metadata_calls+=1
        return {'document':{'revision_id':2 if self.changed and self.metadata_calls>1 else 1,'title':'Template'}}


def test_complete_read_is_fenced_and_uses_current_permission():
    r=Reader(fixture_native());out=r.read('root')
    assert out['read_state']=='complete'
    assert r.calls[1][1]['document_revision_id']==-1


def test_moving_document_rejected():
    with pytest.raises(BoundaryError,match='CHANGED_DURING_READ'):Reader(fixture_native(),revision_changed=True).read('root')


def test_missing_child_rejected():
    n=fixture_native();n['blocks'].pop()
    with pytest.raises(BoundaryError,match='INCOMPLETE'):Reader(n).read('root')


def test_image_is_partial_not_full_text_success():
    n=fixture_native();n['blocks'][-1]={'block_id':'body','block_type':27,'parent_id':'root','image':{'token':'image'}}
    assert Reader(n).read('root')['read_state']=='partial'


def test_embedded_sheet_is_not_mistaken_for_a_container():
    n=fixture_native();n['blocks'][-1]={'block_id':'body','block_type':30,'parent_id':'root','sheet':{'token':'sheet'}}
    assert Reader(n).read('root')['unread_blocks']==['body']


def test_pagination_cycle_fails():
    page={'items':[],'has_more':True,'page_token':'repeat'}
    with pytest.raises(BoundaryError,match='PAGINATION'):Reader(fixture_native(),pages=[page,page]).read('root')


@pytest.mark.parametrize('url',['http://example.com/docx/x','https://bad.example/docx/x','https://u:p@example.com/docx/x','https://example.com/drive/x'])
def test_source_urls_do_not_expand_scope(url):
    with pytest.raises(BoundaryError):token_from_url(url,['example.com'])


def test_owner_catalog_denies_before_reading_cli(tmp_path):
    with pytest.raises(BoundaryError,match='OWNER_ONLY'):
        OwnerCatalog({}, {'user':'another'}, 'owner',lambda:True,deadline=time.monotonic()+10)


def test_rich_header_label_and_style_preserved():
    _,slots=profile_and_slots();n=fixture_native();s=next(s for s in slots if s['block_id']=='name')
    elements,updated=replacements(n['blocks'][1],s,'Actual project')
    assert elements[0]==n['blocks'][1]['text']['elements'][0]
    assert elements[1]['text_run']['content']=='Actual project'
    assert n['blocks'][1]['text']['elements'][1]['text_run']['content']=='〈项目全称〉'


def test_unread_template_cannot_become_effective():
    n=fixture_native();n['read_state']='partial'
    with pytest.raises(BoundaryError,match='PARTIAL'):
        blueprint(n,record={},tenant='t',actor='o',doc_type='change',project_type='IRAD:L1',stage='change',assets=[])


def test_runtime_control_failure_is_not_a_model_fallback():
    p=SimpleNamespace(complete=lambda *a,**kw:(_ for _ in ()).throw(BoundaryError('STOP_UNKNOWN')))
    with pytest.raises(ProviderControlError) as err:SharedProvider(p).complete('x')
    assert str(err.value.original)=='STOP_UNKNOWN'


def test_false_identity_guard_never_calls_provider():
    called=[]
    p=SharedProvider(SimpleNamespace(complete=lambda *a,**kw:called.append(True)),guard=lambda:False)
    with pytest.raises(ProviderControlError):p.complete('x')
    assert not called


def test_unavailable_reply_changes_only_the_named_gap():
    questions=[{'key':'risk','label':'结题 / 遗留风险 / 结论安排'},{'key':'owner','label':'结题 / 维护责任 / 结论安排'}]
    assert deferred_question_keys('遗留风险暂时没有资料',questions)=={'risk'}
    assert deferred_question_keys('无法提供',questions)==set()


def test_explicit_all_unavailable_can_defer_displayed_gaps():
    assert deferred_question_keys('以上全部无法提供',[{'key':'one'},{'key':'two'}])=={'one','two'}


def test_blank_template_cell_does_not_invent_mandatory_policy():
    profile,_=profile_and_slots()
    assert next(f for f in profile.fields if f.label=='更改原因').required is False
    assert next(f for f in profile.fields if f.label=='项目名称').required is True


def test_readback_normalizes_only_false_style_defaults():
    n=fixture_native();same=copy.deepcopy(n)
    same['blocks'][-1]['text']['elements'][0]['text_run']['text_element_style']={'bold':False,'italic':False}
    assert verify_exact(n,same)
    same['blocks'][-1]['text']['elements'][0]['text_run']['text_element_style']['bold']=True
    assert not verify_exact(n,same)


def test_identity_time_is_charged_to_original_budget():
    seen={}
    def complete(*a,**kw):seen.update(kw);return SimpleNamespace(elapsed=0)
    p=SharedProvider(SimpleNamespace(complete=complete),guard=lambda:time.sleep(.01),deadline=time.monotonic()+1)
    p.complete('x',timeout=120)
    assert 0<seen['timeout']<1


def test_mapping_does_not_strip_negation_or_grant_confirmation():
    profile,_=profile_and_slots();field=next(r for r in profile.fields if r.label=='更改原因')
    session=SimpleNamespace(complete_json=lambda *args:{'matches':[{'field_id':field.field_id,'source_id':'S1','locator':'1','quote':'通过验证'}]})
    snap=map_facts(profile,project={'id':'project','title':'Project','code':'P1'},
        sources=[{'id':'S1','project_id':'project','provenance':'user_input','version':'1','read_status':'complete',
        'segments':[{'id':'1','original':'尚未通过验证，仍待复核。'}]}],access=AccessContext('tenant','owner',('project',)),
        session=session,source_uri='ledger://test',source_revision='1',supplied_type='IRAD')
    evidence=next(e for e in snap.evidence if e.key.startswith('slot.'))
    assert evidence.value=='尚未通过验证，仍待复核。' and evidence.state=='reported'


def test_mapping_rejects_fabricated_quote():
    profile,_=profile_and_slots();field=next(r for r in profile.fields if r.label=='更改原因')
    session=SimpleNamespace(complete_json=lambda *args:{'matches':[{'field_id':field.field_id,'source_id':'S1','locator':'1','quote':'编造通过'}]})
    with pytest.raises(BoundaryError,match='QUOTE_INVALID'):
        map_facts(profile,project={'id':'project','title':'Project','code':'P1'},sources=[{'id':'S1','project_id':'project',
            'provenance':'user_input','version':'1','read_status':'complete','segments':[{'id':'1','original':'待测试'}]}],
            access=AccessContext('tenant','owner',('project',)),session=session,source_uri='ledger://test',source_revision='1',supplied_type='IRAD')


def test_foreign_project_rejected_before_model():
    profile,_=profile_and_slots()
    with pytest.raises(BoundaryError,match='PROJECT_DENIED'):
        map_facts(profile,project={'id':'project','title':'Project','code':'P1'},sources=[{'project_id':'other','provenance':'current_project'}],
            access=AccessContext('tenant','owner',('project',)),session=None,source_uri='ledger://test',source_revision='1',supplied_type='IRAD')


@pytest.mark.parametrize('source,code',[
    ({'name':'参考文档.txt','segments':[]},'REFERENCE_NOT_PROJECT_FACT'),
    ({'name':'report.txt','segments':[{'original':'IRAD-2099-002 项目已通过'}]},'SOURCE_PROJECT_MISMATCH'),
    ({'name':'report.txt','segments':[{'original':'IRAD-2099-001 与 IRAD-2099-002'}]},'MULTI_PROJECT_INPUT_REQUIRES_SCOPE')])
def test_uploaded_scope_is_not_relabelled_as_current(source,code):
    with pytest.raises(BoundaryError,match=code):admit_project_input(source,'project','IRAD-2099-001')


def test_host_store_shares_transaction_and_connection(tmp_path):
    store=Store(tmp_path/'db.sqlite3');host=HostRunStore(store,{'id':'draft','expires':time.time()+100})
    assert host.conn is store.conn and host._lock is store.lock
    host.claim('key','hash');assert store.rows('SELECT * FROM amdoc_run_bindings')[0]['draft_id']=='draft'
    host.close();assert store.rows('SELECT * FROM amdoc_runs');store.close()


def test_expiry_removes_sources_even_when_feature_is_disabled(tmp_path):
    store=Store(tmp_path/'db.sqlite3',clock=lambda:100)
    host=HostRunStore(store,{'id':'draft','expires':99});host.claim('key','hash')
    store.execute('INSERT INTO amdoc_fact_snapshots VALUES(?,?,?)',('key','fact','sensitive body'))
    store.execute('INSERT INTO amdoc_context VALUES(?,?,?)',('draft','private project',99))
    NativePublisher(store,FakeCloud(fixture_native()),folder='folder',host='example.com')
    store.execute('INSERT INTO amdoc_native_writes VALUES(?,?,?,?,?,?,?,?,?)',('idem','draft',1,'hash','unknown','object','private payload',None,99))
    DocumentStandards.cleanup_store(store)
    assert not store.rows('SELECT * FROM amdoc_fact_snapshots') and not store.rows('SELECT * FROM amdoc_context')
    assert store.rows('SELECT payload,state FROM amdoc_native_writes')[0]=={'payload':'{}','state':'unknown'}
    store.close()


class FakeCloud:
    def __init__(self,native):self.docs={native['token']:copy.deepcopy(native)};self.writes=[];self.fail_copy=False;self.fail_patch=False
    def check(self):return True
    def restrict_copy(self,token):self.private_token=token
    def read(self,token):return copy.deepcopy(self.docs[token])
    def call(self,method,path,*,body=None,query=None):
        if method=='GET':return {'files':[{'name':self.docs['copy']['title'],'type':'docx','token':'copy'}]} if 'copy' in self.docs else {'files':[]}
        self.writes.append((method,path))
        if method=='POST':
            source=copy.deepcopy(self.docs['root']);mapping={b['block_id']:'copy' if b['block_id']=='root' else 'copy'+b['block_id'] for b in source['blocks']}
            def remap(x):
                if isinstance(x,dict):return {k:remap(v) for k,v in x.items()}
                if isinstance(x,list):return [remap(v) for v in x]
                return mapping.get(x,x) if isinstance(x,str) else x
            source['blocks']=remap(source['blocks']);source['paths']={mapping[k]:v for k,v in source['paths'].items()};source['token']='copy';source['title']=body['name']
            source['blocks'][0]['page']['elements'][0]['text_run']['content']=body['name'];source['hash']=fingerprint(source['blocks']);self.docs['copy']=source
            if self.fail_copy:raise TimeoutError('response lost after creation')
            return {'file':{'token':'copy'}}
        if method=='PATCH':
            source=self.docs['copy'];by={b['block_id']:b for b in source['blocks']}
            for request in body['requests']:by[request['block_id']]['text']['elements']=request['update_text_elements']['elements']
            source['revision']+=1;source['hash']=fingerprint(source['blocks'])
            if self.fail_patch:raise TimeoutError('response lost after write')
            return {}


def publication(tmp_path):
    n=fixture_native();cloud=FakeCloud(n);store=Store(tmp_path/'db.sqlite3');publisher=NativePublisher(store,cloud,folder='folder',host='example.com')
    profile,slots=profile_and_slots();doc={'fields':[{'field_id':s['field_id'],'text':'new '+str(i)} for i,s in enumerate(slots)],'issues':[],'template_hash':'templatehash'}
    draft={'id':'draft','revision':1,'content_hash':'hash1','expires':time.time()+100}
    return publisher,cloud,store,draft,doc,n,slots


def test_native_copy_write_readback_and_repeat(tmp_path):
    pub,cloud,s,d,doc,n,slots=publication(tmp_path)
    result=pub.save(d,doc,n,slots);assert result['state']=='verified' and len(cloud.writes)==2
    again=pub.save(d,doc,n,slots);assert again['receipt']==result['receipt'] and len(cloud.writes)==2
    s.close()


def test_reconciling_old_receipt_cannot_roll_back_current_document(tmp_path):
    pub,cloud,s,d,doc,n,slots=publication(tmp_path);result=pub.save(d,doc,n,slots)
    s.execute('INSERT INTO amdoc_native_writes VALUES(?,?,?,?,?,?,?,?,?)',('later','draft',2,'hash2','verified','newer','{}','{}',d['expires']))
    s.execute("UPDATE amdoc_native_documents SET token='newer' WHERE draft_id='draft'")
    assert pub.reconcile(result['idempotency_key'])
    assert s.rows('SELECT token FROM amdoc_native_documents')[0]['token']=='newer';s.close()


def test_uncertain_copy_reconciles_without_creating_again(tmp_path):
    pub,cloud,s,d,doc,n,slots=publication(tmp_path);cloud.fail_copy=True
    with pytest.raises(TimeoutError):pub.save(d,doc,n,slots)
    assert pub.save(d,doc,n,slots)['state']=='unknown' and len(cloud.writes)==1
    assert s.rows('SELECT token FROM amdoc_native_writes')[0]['token']=='copy';s.close()


def test_copy_privacy_must_be_verified_before_project_content(tmp_path):
    pub,cloud,s,d,doc,n,slots=publication(tmp_path)
    cloud.restrict_copy=lambda token:(_ for _ in ()).throw(BoundaryError('DOCUMENT_PRIVATE_ACCESS_UNVERIFIED'))
    with pytest.raises(BoundaryError,match='PRIVATE_ACCESS'):pub.save(d,doc,n,slots)
    assert len(cloud.writes)==1 and cloud.writes[0][0]=='POST'
    assert s.rows('SELECT state FROM amdoc_native_writes')[0]['state']=='copied';s.close()


def test_uncertain_write_readback_reuses_actual_result(tmp_path):
    pub,cloud,s,d,doc,n,slots=publication(tmp_path);cloud.fail_patch=True
    with pytest.raises(TimeoutError):pub.save(d,doc,n,slots)
    result=pub.save(d,doc,n,slots);assert result['state']=='verified' and len(cloud.writes)==2;s.close()


def test_human_modified_target_is_never_overwritten(tmp_path):
    pub,cloud,s,d,doc,n,slots=publication(tmp_path);pub.save(d,doc,n,slots)
    cloud.docs['copy']['blocks'][1]['text']['elements']=[{'text_run':{'content':'human edit'}}]
    with pytest.raises(BoundaryError,match='HUMAN_EDIT'):
        pub.save(dict(d,revision=2,content_hash='hash2'),doc,n,slots,selected_fields=[slots[0]['field_id']])
    assert len(cloud.writes)==2;s.close()


def test_revision_requires_explicit_fields_and_revalidation(tmp_path):
    pub,cloud,s,d,doc,n,slots=publication(tmp_path);pub.save(d,doc,n,slots)
    with pytest.raises(BoundaryError,match='EXPLICIT_UPDATE'):
        pub.save(dict(d,revision=2,content_hash='hash2'),doc,n,slots)
    with pytest.raises(BoundaryError,match='REVALIDATION'):
        pub.save(dict(d,revision=2,content_hash='hash2'),doc,n,slots,selected_fields=[slots[0]['field_id']])
    s.close()


def test_template_migration_is_not_silent(tmp_path):
    pub,cloud,s,d,doc,n,slots=publication(tmp_path);pub.save(d,doc,n,slots)
    with pytest.raises(BoundaryError,match='MIGRATION'):
        pub.save(dict(d,revision=2,content_hash='hash2'),dict(doc,template_hash='new'),n,slots,selected_fields=[slots[0]['field_id']])
    assert len(cloud.writes)==2;s.close()
