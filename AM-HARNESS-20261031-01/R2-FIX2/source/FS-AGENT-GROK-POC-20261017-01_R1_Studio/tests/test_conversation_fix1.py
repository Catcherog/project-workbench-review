"""R1-FIX1 correct-behavior regressions. All model/cloud/identity calls are synthetic."""
import copy, json, time
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from am_info_sync.models import Source, Observation, Principal, Page, PermissionDenied, RetryableError, LeaseLost
from am_info_sync.store import Store as InfoStore
from am_info_sync.runtime import InformationService
from am_info_sync.sync import SyncEngine
from am_info_sync.facts import FactEngine
from info_sources import Discovery, record_observation
from am_conversation.store import ConversationStore
from am_conversation.types import AccessContext, ModelTurn, ConversationError
from am_conversation.engine import ConversationAgent, RuntimeConfig
from am_conversation.tools import ToolRegistry
from am_conversation.legacy import LegacyConversationBridge
from am_conversation.documents import DocumentTools
from fs_agent.store import Store
from fs_agent.document_native import NativePublisher
from fs_agent.document_standards import DocumentStandards
from am_doc_engine.models import fingerprint
from test_document_standards import fixture_native, profile_and_slots
from test_conversation_integration import convo, speak, answer, project, ux, service, am_rig, base_rig

@pytest.mark.parametrize('error',[RetryableError('timeout'),RetryableError('rate limit',retry_after=60),ValueError('parse')])
def test_f01_denial_survives_read_errors_until_authoritative_success(tmp_path,error):
    s=InfoStore(tmp_path/'info');source=Source('s','workitem_snapshot','r','t','u',enabled=True,settings={'subject_id':'P','fact_mappings':{'system_record':{'value_path':['record'],'quote_path':['quote']}}})
    s.register_source(source);obs=record_observation(source,'r',{'status':'private'},s.clock())
    adapter=Mock();adapter.fetch_page.return_value=Page((obs,));sync=SyncEngine(s,{'workitem_snapshot':adapter});facts=FactEngine(s)
    sync.run_source('s');facts.process(obs,[]);principal=Principal('u','t')
    assert len(facts.query('P',principal)['facts'])==1
    initial=s.access_version();adapter.fetch_page.side_effect=PermissionDenied()
    with pytest.raises(PermissionDenied):sync.run_source('s')
    denied=s.access_version();assert denied!=initial
    adapter.fetch_page.side_effect=error
    with pytest.raises(type(error)):sync.run_source('s')
    assert s.source_status('s')['availability']=='denied' and facts.query('P',principal)['facts']==[]
    assert s.access_version()==denied
    s.close();s=InfoStore(tmp_path/'info');assert s.access_version()==denied
    sync=SyncEngine(s,{'workitem_snapshot':adapter});adapter.fetch_page.side_effect=None
    sync.run_source('s');assert s.access_version()!=denied
    assert len(FactEngine(s).query('P',principal)['facts'])==1
    s.close()

def test_f01_revocation_fences_inflight_success():
    s=InfoStore(':memory:');s.register_source(Source('s','docx','r','t','u',enabled=True))
    run=s.begin_sync('s');s.mark_source_error('s','denied',True)
    with pytest.raises(LeaseLost):s.save_page(run['run_id'],run['lease_token'],None,Page(()))
    assert s.source_status('s')['availability']=='denied';s.close()

def info_fixture(tmp_path):
    s=InfoStore(tmp_path/'info');service=InformationService(s);s.register_source(Source('s','docx','r','tenant','owner',enabled=True,settings={'subject_id':'P'}))
    obs=Observation('s','o','v1',s.clock(),text='SOURCE_PRIVATE_VALUE')
    s.record(obs);service.facts.process(obs,[{'source_id':'s','object_id':'o','version':'v1','subject_id':'P','field':'status','value':obs.text,'quote':obs.text,'assertion_type':'reported'}])
    ctx=AccessContext('tenant','app','owner','dm',allowed_project_ids=frozenset({'P'}),is_owner=True,source_access_version=s.access_version())
    return s,service,ctx

@pytest.mark.parametrize('change',['denied','disabled','readers'])
def test_f02_history_replay_actions_and_generation_invalidate(tmp_path,change):
    s,service,ctx=info_fixture(tmp_path);c=ConversationStore(tmp_path/'conversation');reg=ToolRegistry();prompts=[]
    reg.prefetch=lambda *a:[service.query('P',Principal('owner','tenant'))]
    def complete(messages,tools,**kw):
        prompts.append(copy.deepcopy(messages))
        return ModelTurn(text='SOURCE_PRIVATE_VALUE' if 'SOURCE_PRIVATE_VALUE' in json.dumps(messages) else '当前无可用来源')
    agent=ConversationAgent(NS(complete=complete),c,reg,config=RuntimeConfig(prefetch_projects=True),source_access_version=s.access_version)
    first=agent.handle(ctx,'1','用户自己的资料');assert 'SOURCE_PRIVATE_VALUE' in first.text
    pending=c.create_action(ctx,tool_name='send',arguments={'body':first.text},preview=first.text)
    task=c.create_task(ctx,project_id='P',title=first.text)
    if change=='denied':s.mark_source_error('s','access_revoked',True)
    elif change=='disabled':s.register_source(replace(s.get_source('s'),enabled=False))
    else:s.register_source(replace(s.get_source('s'),readers=('user:other',)))
    ctx2=replace(ctx,source_access_version=s.access_version())
    with pytest.raises(ConversationError):agent.handle(ctx2,'1','用户自己的资料')
    assert c.list_actions(ctx2)==[] and c.list_tasks(ctx2)==[]
    with pytest.raises(ConversationError,match='SOURCE_ACCESS_CHANGED'):c.get_action(ctx2,pending['id'])
    hist=c.history(ctx2);assert hist==[{'role':'user','content':'用户自己的资料'}]
    if change in ('denied','disabled'):
        assert service.query('P',Principal('owner','tenant'))['facts']==[]
        agent.handle(ctx2,'2','刚才内容再说一次')
        assert all('SOURCE_PRIVATE_VALUE' not in x['content'] for x in prompts[-1])
    s.close();c.close()

def test_f02_source_change_during_model_discards_result(tmp_path):
    s,service,ctx=info_fixture(tmp_path);c=ConversationStore(':memory:')
    def complete(*args,**kw):s.mark_source_error('s','revoked',True);return ModelTurn(text='SOURCE_PRIVATE_VALUE')
    agent=ConversationAgent(NS(complete=complete),c,ToolRegistry(),source_access_version=s.access_version)
    with pytest.raises(ConversationError,match='SOURCE_ACCESS_CHANGED'):agent.handle(ctx,'1','查询')
    assert not any(x['role']=='assistant' for x in c.history(replace(ctx,source_access_version=s.access_version())))
    s.close();c.close()

@pytest.mark.parametrize('change',['denied','disabled'])
def test_f02_original_gateway_refuses_pending_reply(convo,tmp_path,change):
    am,g,s,api,clock,port=convo[0];inf,svc,_=info_fixture(tmp_path)
    am.information=NS(store=inf,query=lambda row,p:{'version':'v','facts':[],'coverage':{}})
    p=convo[1];p.outputs.append(answer('SOURCE_PRIVATE_VALUE'))
    from test_gateway import event,drain
    payload=event('需求75现在怎样',number=99,user='ou_a',chat='oc_dm');payload['event']['message']['create_time']=str(int(clock()*1000))
    assert am.ingest(payload)==(True,True);assert am.step()
    outputs=s.rows('SELECT * FROM am_conversation_outputs');assert len(outputs)==1
    if change=='denied':inf.mark_source_error('s','revoked',True)
    else:inf.register_source(replace(inf.get_source('s'),enabled=False))
    before=len(api.sent);drain(g)
    assert len(api.sent)==before
    assert s.rows('SELECT state FROM outbox WHERE id=?',(outputs[0]['outbox_id'],))[0]['state']=='rejected'
    inf.close();am.information=None

@pytest.mark.parametrize('failure',['permission','timeout','mapping'])
def test_f03_bad_child_backoff_persists_and_healthy_child_proceeds(tmp_path,failure):
    s=InfoStore(tmp_path/'info');parent=Source('parent','workitem_snapshot','100','t','u',enabled=True,settings={'space':'test','subject_id':'P'});s.register_source(parent)
    s.conn.execute('CREATE TABLE host_discovery_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    d=Discovery.__new__(Discovery);calls=[];broken=[True]
    def backend(args):
        identity=args[args.index('--work-item-id')+1];calls.append(identity)
        if identity=='101' and broken[0]:
            if failure=='permission':raise PermissionDenied()
            if failure=='timeout':raise TimeoutError()
            return {'work_item_attribute':{'work_item_id':identity}}
        return {'work_item_attribute':{'work_item_id':identity,'work_item_type':{'key':'deliverable','name':'deliverable'}}}
    d.h=NS(store=s,business=NS(_run=backend),service=NS(pulse=Mock()),_register=s.register_source,start_ms=0,am=NS(owner='u',g=NS(config=NS(tenant_key='t'))))
    d.state('metadata:deliverable',{'list':[{'field_key':'progress','field_name':'Progress','field_type':'text'}],'pagination':{'has_more':False}})
    d.last_approvals=d.last_projects=d.last_documents=d.last_search=time.time()
    d.child(parent,'101','node');d.child(parent,'102','node');d.step();d.step()
    assert calls==['101','102'];assert s.get_source('workitem:102')
    bad=d.state('child_pending:101');assert bad['attempts']==1 and bad['next_retry_at']>time.time() and bad['last_error']
    assert any(g['kind']=='discovery_child' and g['object_id']=='101' for g in s.health()['gaps'])
    s.close();s=InfoStore(tmp_path/'info');d.h.store=s;d.h._register=s.register_source
    assert d.state('child_pending:101')==bad
    broken[0]=False;d.state('child_pending:101',dict(bad,next_retry_at=0));d.step();d.child(parent,'102','node');d.step()
    assert calls==['101','102','101'] and d.state('child_pending:101') is None
    assert s.get_source('workitem:101') and not any(g['kind']=='discovery_child' for g in s.health()['gaps']);s.close()

class Cloud:
    def __init__(self,native):
        self.docs={native['token']:copy.deepcopy(native)}
        self.copies=0
        self.fail_readback=False
    def check(self): return True
    def restrict_copy(self,token): pass
    def read(self,token): return copy.deepcopy(self.docs[token])
    def call(self,method,path,*,body=None,query=None):
        if method=='POST':
            self.copies+=1
            token='copy'+str(self.copies)
            old_token=path.split('/')[-2]
            source=copy.deepcopy(self.docs[old_token])
            mapping={b['block_id']:token+'-'+str(i) for i,b in enumerate(source['blocks'])}
            def remap(v):
                if isinstance(v,dict):return {k:remap(x) for k,x in v.items()}
                if isinstance(v,list):return [remap(x) for x in v]
                return mapping.get(v,v) if isinstance(v,str) else v
            source['blocks']=remap(source['blocks'])
            source['paths']={mapping[k]:v for k,v in source['paths'].items()}
            source.update(token=token,title=body['name'])
            source['blocks'][0]['page']['elements'][0]['text_run']['content']=body['name']
            source['hash']=fingerprint(source['blocks'])
            self.docs[token]=source
            return {'file':{'token':token}}
        if method=='PATCH':
            token=path.split('/')[-3]
            native=self.docs[token]
            by={b['block_id']:b for b in native['blocks']}
            for r in body['requests']:
                by[r['block_id']]['text']['elements']=r['update_text_elements']['elements']
            if self.fail_readback:
                by[body['requests'][0]['block_id']]['text']['elements'].append({'text_run':{'content':' readback mismatch'}})
            native['revision']+=1
            native['hash']=fingerprint(native['blocks'])
            return {}
        raise AssertionError((method,path))


def test_f04_current_unknown_never_uses_previous_receipt_and_reconciles_exact(tmp_path,monkeypatch):
    s=Store(tmp_path/'docs');native=fixture_native();cloud=Cloud(native);pub=NativePublisher(s,cloud,folder='folder',host='example.com')
    _,slots=profile_and_slots();document={'fields':[{'field_id':x['field_id'],'text':'value '+str(i)} for i,x in enumerate(slots)],'issues':[],'template_hash':'template'}
    draft={'id':'draft','revision':1,'content_hash':'hash1','accepted_hash':'hash1','state':'ready','expires':time.time()+120}
    first=pub.save(draft,document,native,slots);cloud.fail_readback=True
    standards=DocumentStandards.__new__(DocumentStandards);standards.s=s;standards.cfg={'output_folder':'folder','hosts':['example.com'],'catalog':{}}
    standards.g=NS(config=NS(owner='owner'));standards.authorize=lambda row:None;standards.guard=lambda *a,**kw:True
    s.execute('CREATE TABLE amdoc_results(draft_id TEXT,revision INTEGER,payload TEXT,expires REAL)')
    payload={'document':document,'native':native,'slots':slots,'project_title':'Synthetic',
             'profile':{'sections':[],'fields':[]}}
    s.execute('INSERT INTO amdoc_results VALUES(?,?,?,?)',('draft',1,json.dumps(payload),draft['expires']))
    class SyntheticReviewPublisher(NativePublisher):
        def save(self,*a,**kw):
            kw['revalidate']=lambda b,h,c,sel:c
            return super().save(*a,**kw)
    monkeypatch.setattr('fs_agent.document_standards.NativePublisher',SyntheticReviewPublisher)
    monkeypatch.setattr('fs_agent.document_standards.OwnerNativeDocs',lambda *a,**kw:cloud)
    tools=DocumentTools.__new__(DocumentTools);tools.s=s;tools.logic=NS(standards=standards)
    tools.b=NS(store=NS(get_action=lambda ctx,key:{'preview':'exact'}));tools.publish_preview=lambda *a:'exact';tools.get=lambda *a:({},draft)
    args={'draft_id':'draft','operation':'update_cloud','sections':[slots[0]['field_id']]}
    result=tools.publish(None,args,'action2')
    assert result['status']=='unknown' and result['verified'] is False and not result.get('receipt_id')
    assert result['idempotency_key']!=first['idempotency_key'] and cloud.copies==2
    assert tools.publish(None,args,'action2')['status']=='unknown' and cloud.copies==2
    # Independent exact-key readback, no write. Old success must not mask mismatch.
    unknown=standards.native_action_result({},draft,'云文档对账',idempotency_key=result['idempotency_key'])
    assert unknown['state']=='unknown' and unknown['receipt'] is None
    row=s.rows('SELECT * FROM amdoc_native_writes WHERE idem=?',(result['idempotency_key'],))[0]
    cloud.docs[row['token']]=json.loads(row['payload'])['expected'];cloud.docs[row['token']]['hash']=fingerprint(cloud.docs[row['token']]['blocks'])
    good=standards.native_action_result({},draft,'云文档对账',idempotency_key=result['idempotency_key'])
    assert good['state']=='verified' and good['receipt']['url'].endswith('copy2')
    historical=standards.native_action_result({},dict(draft,revision=2,content_hash='newer'),'云文档对账',idempotency_key=result['idempotency_key'])
    assert historical['receipt']==good['receipt']
    assert tools.publish(None,args,'action2')['receipt_id'].endswith('copy2') and cloud.copies==2
    s.close()

@pytest.mark.parametrize('kind',['docx','file_snapshot'])
def test_f05_new_subject_reextracts_same_version_without_copying_facts(tmp_path,kind):
    from am_info_sync.catalog import EntityCatalog
    s=InfoStore(tmp_path/'info');catalog=EntityCatalog(s);catalog.register('A','A');catalog.register('B','B')
    calls=[]
    def extractor(obs):
        subjects=catalog.context_for(obs)['allowed_subject_ids'];calls.append(subjects)
        return [{'source_id':obs.source_id,'object_id':obs.object_id,'version':obs.version,'subject_id':p,'field':'progress','value':p+' ready','quote':p+' ready','assertion_type':'reported'} for p in subjects if p+' ready' in obs.text]
    adapter=Mock();service=InformationService(s,{kind:adapter},extractor)
    d=Discovery.__new__(Discovery);d.h=NS(store=s,catalog=catalog,_register=s.register_source,start_ms=0,am=NS(owner='owner',g=NS(config=NS(tenant_key='t'))));d.user=Mock()
    s.conn.execute('CREATE TABLE host_discovery_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    d.user.call.return_value={'token':'samefile','type':'docx' if kind=='docx' else 'file','title':'Shared'}
    url='https://example.feishu.cn/docx/samefile' if kind=='docx' else 'https://example.feishu.cn/file/samefile'
    d.register_document(url,['A']);sid=('docx:' if kind=='docx' else 'file:')+'samefile'
    obs=Observation(sid,'body','v1',s.clock(),text='A ready; B ready');adapter.fetch_page.return_value=Page((obs,))
    service.sync_engine.run_source(sid);assert service.analyze_once()['status']=='done'
    d.register_document(url,['B'])
    before=service.query('B',Principal('owner','t'));assert before['facts']==[] and before['coverage']['processing_pending']
    service.sync_engine.run_source(sid);assert service.analyze_once()['status']=='done'
    result=service.query('B',Principal('owner','t'));assert [f['value'] for f in result['facts']]==['B ready']
    assert calls==[['A'],['A','B']]
    assert result['coverage']['processing_pending'] is False
    d.register_document(url,['B']);service.sync_engine.run_source(sid);assert service.analyze_once() is None
    assert len(service.query('A',Principal('owner','t'))['facts'])==1
    s.close()

def test_f05_mapping_change_fences_old_extractor_and_expiry_stays_visible(tmp_path):
    now=[10000];s=InfoStore(tmp_path/'info',clock=lambda:now[0]);svc=InformationService(s,extractor=lambda o:[])
    source=Source('s','docx','r','t','u',enabled=True,raw_retention_seconds=1,settings={'subject_id':'A'})
    s.register_source(source);obs=Observation('s','body','v1',now[0],text='A and B');s.record(obs)
    job=s.claim_job('extract');s.register_source(replace(source,settings={'subject_ids':['A','B']}))
    with pytest.raises(LeaseLost):svc.facts.process(obs,[],job_id=job['job_id'],lease_token=job['lease_token'])
    assert svc.analyze_once()['status']=='done'
    now[0]+=1001;s.purge_expired_raw()
    s.register_source(replace(s.get_source('s'),settings={'subject_ids':['A','B'],'mapping_version':2}))
    result=svc.query('B',Principal('u','t'))
    assert result['coverage']['processing_pending'] and result['coverage']['needs_refresh_or_review']
    assert s.get_observation('s','body','v1') is None
    raw=s.conn.execute('SELECT raw_expires_at_ms,purged FROM observations').fetchone();assert tuple(raw)==(11000,1)
    # A later ordinary reread does not extend retention without explicit policy.
    svc.sync_engine.adapters['docx']=NS(fetch_page=lambda *a:Page((obs,)))
    svc.sync_engine.run_source('s');assert svc.analyze_once() is None and s.get_observation('s','body','v1') is None
    s.close()

def test_f05_denied_source_does_not_extract_until_access_revalidated(tmp_path):
    s=InfoStore(tmp_path/'info');source=Source('s','docx','r','t','u',enabled=True,settings={'subject_id':'A'})
    s.register_source(source);obs=Observation('s','o','v1',s.clock(),text='A B');s.record(obs)
    calls=[];svc=InformationService(s,{'docx':NS(fetch_page=lambda *a:Page((obs,)))},lambda o:calls.append(o) or [])
    assert svc.analyze_once()['status']=='done';s.mark_source_error('s','revoked',True)
    s.register_source(replace(source,settings={'subject_ids':['A','B']}));assert svc.analyze_once() is None and len(calls)==1
    svc.sync_engine.run_source('s');assert svc.analyze_once()['status']=='done' and len(calls)==2
    s.close()

def precheck_fixture(tmp_path):
    from fs_agent.logic_service import LogicService
    from fs_agent.store import scope_of
    s=Store(tmp_path/'docs');logic=LogicService(NS(store=s,config=NS(root=tmp_path,owner='owner'),authorized=lambda r:True),business=NS())
    row={'app':'app','tenant':'t','user':'owner','chat':'dm','chat_type':'p2p','message_id':'event','expires':time.time()+120}
    for name in ('A','B'):
        s.execute("INSERT INTO logic_drafts(id,scope,revision,state,document_type,sources,answers,expires,mode,target,accepted_hash) VALUES(?,?,1,'collecting','test','[]','{}',?,'precheck',?,'adopted')",(name,scope_of(row),row['expires'],json.dumps({'id':'target-'+name})))
    tools=DocumentTools.__new__(DocumentTools);tools.logic=logic;tools.s=s;tools.principal=lambda ctx:row;tools.get=lambda ctx,ident:(row,logic.get(row,ident))
    return s,logic,row,tools

def test_f06_explicit_draft_updated_and_other_draft_unchanged(tmp_path):
    from fs_agent.config import BoundaryError
    s,logic,row,tools=precheck_fixture(tmp_path);before=s.rows("SELECT * FROM logic_drafts WHERE id='B'")[0]
    reply=tools.edit(None,{'operation':'requirements','draft_id':'A','version':1,'requirements':'型号=A型号'},'event')
    assert reply['draft_id']=='A' and reply['version']==2
    assert 'A型号' in logic.get(row,'A')['target_requirements']
    assert s.rows("SELECT * FROM logic_drafts WHERE id='B'")[0]==before
    with pytest.raises(BoundaryError,match='VERSION_CHANGED'):logic.set_precheck_requirements(row,'旧要求',draft_id='A',expected_revision=1)
    assert logic.get(row,'A')['revision']==2
    # Legacy command still chooses the current draft, with a revision guard.
    assert logic.set_precheck_requirements(row,'型号=B型号')['id']=='B';s.close()

def test_f06_concurrent_change_is_rejected_before_write(tmp_path,monkeypatch):
    from fs_agent.config import BoundaryError
    s,logic,row,tools=precheck_fixture(tmp_path);get=logic.get
    def racing_get(r,i):
        old=get(r,i);s.execute('UPDATE logic_drafts SET revision=revision+1 WHERE id=?',(i,));return old
    monkeypatch.setattr(logic,'get',racing_get)
    with pytest.raises(BoundaryError,match='VERSION_CHANGED'):logic.set_precheck_requirements(row,'迟到要求',draft_id='A',expected_revision=1)
    assert s.rows("SELECT target_requirements FROM logic_drafts WHERE id='A'")[0]['target_requirements'] is None
    assert s.rows("SELECT revision FROM logic_drafts WHERE id='B'")[0]['revision']==1;s.close()

def test_f02_revoked_draft_can_cancel_and_unknown_can_reconcile_without_reusing_payload(tmp_path):
    s,info,ctx=info_fixture(tmp_path);c=ConversationStore(':memory:')
    draft=c.create_action(ctx,tool_name='send',arguments={'body':'PRIVATE'},preview='PRIVATE')
    other=c.create_action(ctx,tool_name='send',arguments={'body':'PRIVATE2'},preview='PRIVATE2')
    c.claim_event(ctx,'presented','准备动作')
    c.mark_presented(ctx,other['id'],expected_version=1,event_id='presented')
    c.approve_action(ctx,other['id'],expected_version=1,digest=other['digest']);c.begin_execution(ctx,other['id'],expected_version=1)
    c.finish_execution(ctx,other['id'],status='unknown',result={'status':'unknown'})
    s.mark_source_error('s','revoked',True);fresh=replace(ctx,source_access_version=s.access_version())
    agent=ConversationAgent(NS(),c,ToolRegistry(),source_access_version=s.access_version)
    assert agent.handle(fresh,'cancel','取消 '+draft['id']).status=='cancelled'
    assert 'PRIVATE' not in json.dumps(c.action_metadata(fresh,other['id']))
    c.finish_execution(fresh,other['id'],status='succeeded',result={'status':'succeeded','verified':True,'receipt_id':'original-receipt'})
    assert c.action_metadata(fresh,other['id'])['status']=='succeeded'
    with pytest.raises(ConversationError,match='SOURCE_ACCESS_CHANGED'):c.begin_execution(fresh,other['id'],expected_version=1)
    s.close();c.close()

def test_f02_restored_source_requires_current_read_and_never_revives_old_history(tmp_path):
    s,info,ctx=info_fixture(tmp_path);c=ConversationStore(':memory:');c.claim_event(ctx,'old','user raw');c.finish_event(ctx,'old',{'text':'SOURCE_PRIVATE_VALUE'})
    source=s.get_source('s');s.register_source(replace(source,enabled=False));s.register_source(source)
    assert info.query('P',Principal('owner','tenant'))['facts']==[]
    obs=s.get_observation('s','o','v1');info.sync_engine.adapters['docx']=NS(fetch_page=lambda *a:Page((obs,)));info.sync_engine.run_source('s')
    fresh=replace(ctx,source_access_version=s.access_version())
    assert len(info.query('P',Principal('owner','tenant'))['facts'])==1
    assert c.history(fresh)==[{'role':'user','content':'user raw'}]
    s.close();c.close()
