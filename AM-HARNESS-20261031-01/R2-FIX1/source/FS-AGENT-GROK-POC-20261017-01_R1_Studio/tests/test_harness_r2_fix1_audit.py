"""R2 independent audit counterexamples on real host/store adapters; synthetic I/O."""
from dataclasses import replace
from types import SimpleNamespace
import json
import pytest
from test_harness_response_v2 import response,presentations
from test_harness_host import harness,convo,ux,service,am_rig,base_rig,incoming,execute,call,answer,project
from am_outcome.completion import resolve_goals,check_goals
from am_outcome.adapters import adapt
from am_response.pipeline import ResponsePipeline
from am_response.gateway import GatewayProjection
from am_response.semantics import PROFILE
from am_conversation.types import AccessContext,AgentReply,ConversationError
from am_conversation.store import ConversationStore

CAT=[{'id':'p','title':'需求75','aliases':[]}]

def test_same_project_matters_need_distinct_receipts():
    goals,complete=resolve_goals('为需求75分别登记跟进：确认油脂交期；核对测试排期',CAT)
    assert complete and len(goals)==2 and len({g['step_id'] for g in goals})==2
    a=adapt('create_followup',{'project_id':'p','description':'确认油脂交期'},{'item':{'id':'one','version':1,'state':'open'}},'local',key='a')
    assert check_goals(goals,complete,[a])[1]=='partial'
    b=adapt('create_followup',{'project_id':'p','description':'核对测试排期'},{'item':{'id':'two','version':1,'state':'open'}},'local',key='b')
    assert check_goals(goals,complete,[a,b])[1]=='fulfilled'


def test_compound_reminder_is_not_erased():
    goals,complete=resolve_goals('为需求75登记跟进，明天提醒我',CAT)
    assert complete and [g['operation'] for g in goals]==['create_followup','schedule_reminder']
    assert goals[1]['depends_on']==[goals[0]['step_id']]
    unit=adapt('create_followup',{'project_id':'p'},{'item':{'id':'i','version':1,'state':'open'}},'local',key='u')
    assert check_goals(goals,complete,[unit])[1]=='partial'


def test_real_loop_finishes_both_matters(response):
    conv,h=response;p=project(conv)
    execute(response,'为需求75分别登记跟进：确认油脂交期；核对测试排期',[
        call('create_followup',{'project_id':p,'description':'确认油脂交期'}),
        call('create_followup',{'project_id':p,'description':'核对测试排期'})])
    assert len(h.s.rows('SELECT * FROM action_items'))==2
    assert presentations(h)[-1]['business_completion']=='fulfilled'
    assert len(conv[1].prompts)==2

@pytest.mark.parametrize('changed',['none','hash','accepted','version','id','state'])
def test_adoption_requires_actual_current_content(changed):
    args={'operation':'adopt','draft_id':'d','version':3,'content_hash':'h'}
    raw={'draft_id':'d','version':3,'content_hash':'h','accepted_hash':'h','state':'ready'}
    if changed!='none':raw[{'hash':'content_hash','accepted':'accepted_hash','version':'version','id':'draft_id','state':'state'}[changed]]='other'
    result=adapt('edit_document',args,raw,'local',key='u')
    assert (result['completion']=='fulfilled')==(changed=='none')


def test_readonly_reconciliation_preserves_verified_receipt():
    u=adapt('reconcile_send',{'action_id':'a'},{'status':'succeeded','verified':True,'receipt_id':'m'},'read',key='u')
    assert u['effect']=='read' and u['completion']=='fulfilled' and u['receipt']=='m' and not u['gaps']


def test_identity_renewal_after_one_commit_saves_reply(tmp_path):
    now=[100.];ctx=AccessContext('t','a','u','c',is_owner=True,content_expires_at=1000)
    store=ConversationStore(tmp_path/'c.db',clock=lambda:now[0]);store.claim_event(ctx,'e','保存记录')
    pipe=ResponsePipeline({'mode':'canonical'},clock=lambda:now[0],binding=lambda c,e:{'kind':'event','scope':list(c.scope),'engine_event_id':e,'origin_event_id':e,'identity_expires_at':101.})
    token=pipe.begin(ctx,'e','保存记录');calls=[];guards=[]
    try:
        calls.append('commit');pipe.record('save_work_note',{'project_id':'p'},{'task':{'id':'n','version':1,'status':'open'}},'local')
        now[0]=103
        host=SimpleNamespace(config=SimpleNamespace(max_reply_chars=6000),_guard=lambda *a:guards.append('renewed'),_checkpoint=lambda *a:None)
        reply,pres=pipe.finish(host,ctx,AgentReply('e','已保存','recorded'))
        store.finish_event(ctx,'e',reply.to_dict(),presentation=pres)
        assert store.presentation(ctx,'e')['expires_at']==1000 and len(calls)==1 and len(guards)==2
    finally:pipe.end(token);store.close()

@pytest.mark.parametrize('failure',['SOURCE_ACCESS_CHANGED','CONTENT_EXPIRED','TASK_CANCELLED'])
def test_renewal_never_bypasses_other_guards(tmp_path,failure):
    ctx=AccessContext('t','a','u','c',is_owner=True,content_expires_at=1000)
    pipe=ResponsePipeline({'mode':'canonical'},clock=lambda:100)
    token=pipe.begin(ctx,'e','查询')
    def deny(*a):raise ConversationError(failure)
    try:
        with pytest.raises(ConversationError,match=failure):pipe.finish(SimpleNamespace(_guard=deny,config=SimpleNamespace(max_reply_chars=6000)),ctx,AgentReply('e','old','answered'))
    finally:pipe.end(token)

@pytest.mark.parametrize('mode',['legacy','shadow'])
def test_shadow_does_not_repair_task_or_append_display(harness,mode):
    conv,h=harness
    h.bridge.agent.response_pipeline=ResponsePipeline({'mode':mode},binding=h.bridge.response_binding,targets=lambda c:h.bridge._current(c)['project_catalog'],clock=h.s.clock)
    execute(harness,'为需求75建立跟进',[answer('请补充这条跟进的具体内容。')])
    assert len(conv[1].prompts)==1
    assert conv[0][3].sent[-1]['body']=='请补充这条跟进的具体内容。'
    if mode=='shadow':assert presentations(h)[-1]['observation_kind']=='offline_replay_pending'


def test_cleanup_after_legacy_restart(response):
    conv,h=response;execute(response,'需求75谁负责')
    assert h.s.rows('SELECT * FROM am_response_outbox_v2')
    del h.s.response_projection
    h.s.execute('UPDATE am_response_outbox_v2 SET expires=0')
    h.s.cleanup()
    assert not h.s.rows('SELECT * FROM am_response_outbox_v2')

@pytest.mark.parametrize('state',['unknown','rejected','expired','sending'])
def test_outbox_terminal_is_authoritative_no_resend(response,state):
    conv,h=response;execute(response,'需求75谁负责');sent=len(conv[0][3].sent)
    h.s.execute('UPDATE outbox SET state=?',(state,))
    assert {r['state'] for r in h.s.rows('SELECT * FROM am_response_outbox_v2')}=={state}
    GatewayProjection(h.s)
    assert {r['authoritative_state'] for r in h.s.rows('SELECT * FROM am_response_delivery_v2')}=={state}
    assert len(conv[0][3].sent)==sent


def test_goal_journal_restart_does_not_repeat_success(tmp_path):
    from am_outcome.goals import GoalJournal
    ctx=AccessContext('t','a','u','c',is_owner=True,allowed_project_ids=frozenset({'p'}),content_expires_at=1000)
    store=ConversationStore(tmp_path/'c.db',clock=lambda:100)
    args={'project_id':'p','description':'确认油脂交期'};raw={'item':{'id':'one','version':1,'state':'open'}}
    j=GoalJournal(store,ctx,'e','为需求75分别登记跟进：确认油脂交期；核对测试排期',CAT)
    assert j.before('create_followup',args,'local') is None;j.record('create_followup',args,raw,'local');store.close()
    store=ConversationStore(tmp_path/'c.db',clock=lambda:101)
    j=GoalJournal(store,ctx,'next','继续剩下的事项',CAT)
    assert j.before('create_followup',args,'local')==raw
    assert not j.fulfilled()
    store.close()


def test_unknown_goal_reservation_blocks_replay(tmp_path):
    from am_outcome.goals import GoalJournal
    ctx=AccessContext('t','a','u','c',is_owner=True,allowed_project_ids=frozenset({'p'}),content_expires_at=1000);store=ConversationStore(tmp_path/'c.db',clock=lambda:100)
    args={'project_id':'p','description':'合成事项'};j=GoalJournal(store,ctx,'e','为需求75登记跟进',CAT);j.before('create_followup',args,'local')
    later=GoalJournal(store,ctx,'next','继续',CAT)
    with pytest.raises(ConversationError,match='GOAL_RESULT_RECONCILE_REQUIRED'):later.before('create_followup',args,'local')
    store.close()

@pytest.mark.parametrize('text,decision',[('预计明天完成，尚未验收。','pass'),('根据记录，预估明天完成，还没有验收。','pass'),('已完成并验收。','reject'),('任务已取消。','reject')])
def test_semantic_propositions_keep_modality(text,decision):
    from am_response.semantics import SemanticAssessor
    ctx=AccessContext('t','a','u','c',is_owner=True);p=ResponsePipeline({'mode':'enforce','families':['analysis'],'profile_version':PROFILE})
    token=p.begin(ctx,'e','进展');p.record('read_information',{}, {'facts':[{'fact_id':'f','field':'progress','value':'预计明天完成，尚未验收。'}],'complete_response':True,'has_more':False},'read')
    try:
        e=p.envelope();plan={'segments':[{'kind':'text','intent':'answer','text':text,'claim_ids':[e.data['claims'][0]['id']]}]}
        assert SemanticAssessor()(plan,e)['decision']==decision
    finally:p.end(token)


def test_short_reference_cannot_rebind_to_other_event():
    from am_response.schema import expand
    ctx=AccessContext('t','a','u','c',is_owner=True);p=ResponsePipeline({'mode':'canonical'})
    t=p.begin(ctx,'e1','查询');e1=p.envelope();p.end(t)
    t=p.begin(ctx,'e2','查询');e2=p.envelope();p.end(t)
    plan={'snapshot':e1.digest[:16],'segments':[{'kind':'text','intent':'answer','text':'无','refs':[]}],'omitted':[]}
    with pytest.raises(ConversationError,match='RESPONSE_SNAPSHOT_MISMATCH'):expand(plan,e2)


def test_real_adoption_result_has_hash_and_version(response):
    conv,h=response
    execute(response,'新建一份章程',[call('edit_document',{'operation':'create','kind':'charter'})])
    d=h.s.rows('SELECT * FROM logic_drafts')[0]
    h.s.execute("UPDATE logic_drafts SET state='ready',content='合成稿',content_hash='h1' WHERE id=?",(d['id'],))
    execute(response,'采用当前这版文字',[call('edit_document',{'operation':'adopt','draft_id':d['id'],'version':1,'content_hash':'h1'})])
    units=presentations(h)[-1]['outcome']['work_units'];u=next(u for u in units if u['operation']=='edit_document')
    assert u['completion']=='fulfilled' and u['result']['accepted_hash']==u['result']['content_hash']=='h1'
    assert h.s.rows('SELECT * FROM logic_drafts')[0]['state']=='ready'


def test_real_committed_followup_survives_identity_renewal(response):
    import time
    conv,h=response;am=conv[0][0];cache=am.query_identity;cache.seconds=600
    p=project(conv);tool=h.bridge.registry._tools['create_followup'];original=tool.handler;commits=[]
    def committed(*args):
        result=original(*args);commits.append(result['item']['id'])
        with cache.lock:cache.entries[am.owner]=time.monotonic()-1
        return result
    h.bridge.registry._tools['create_followup']=replace(tool,handler=committed)
    execute(response,'为需求75登记跟进',[call('create_followup',{'project_id':p,'description':'合成续验事项'})])
    assert cache.valid(am.owner) and len(commits)==1 and len(h.s.rows('SELECT * FROM action_items'))==1
    assert h.s.rows('SELECT state FROM am_response_outbox_v2')[-1]['state']=='verified'

@pytest.mark.parametrize('case,expected',[('same','current'),('content','content_changed'),('acl','content_changed'),('mapping','content_changed'),('parser','content_changed'),('revoked','permission_revoked'),('expired','expired'),('missing','indeterminate'),('deleted','content_changed'),('new_member','content_changed'),('partial','indeterminate')])
def test_exact_dependency_shadow_cases(case,expected):
    import copy
    from am_outcome.dependencies import compare
    d={'source_id':'s','object_id':'o','locator':'field','content_hash':'h','access_revision':'a','mapping_version':'m','parser_version':'p','expires':1000}
    before={'objects':[d],'query_set':{'predicate':'all','watermark':'w','pagination_complete':True}};after=copy.deepcopy(before)
    if case in ('content','acl','mapping','parser'):after['objects'][0][{'content':'content_hash','acl':'access_revision','mapping':'mapping_version','parser':'parser_version'}[case]]='new'
    if case=='revoked':after['objects'][0]['permission_revoked']=True
    if case=='deleted':after['objects'][0]['deleted']=True
    if case=='missing':after['objects'][0]['access_revision']=None
    if case=='new_member':after['objects'].append(dict(d,object_id='two'))
    if case=='partial':after['query_set']['pagination_complete']=False
    assert compare(before,after,now=1001 if case=='expired' else 100)['decision']==expected


def test_shared_bundle_document_projection_keeps_id_scope_and_qualifiers():
    from am_outcome.evidence import EvidenceBundle
    p={'key':'canonical','title':'需求75','source_revision':9,'项目进展':'预计完成，尚未验收。'}
    b=EvidenceBundle.build(p,scope=('t','a','u','c',''),expires=1000)
    source=b.document_source(uri='synthetic://ledger',legacy_project_id='legacy')
    assert source['project_id']=='canonical' and source['evidence_bundle_id']==b.data['bundle_id']
    assert '预计完成，尚未验收' in source['segments'][0]['original']
    assert source['legacy_project_id']=='legacy'


def test_allowed_question_has_a_valid_production_path():
    ctx=AccessContext('t','a','u','c',is_owner=True)
    p=ResponsePipeline({'mode':'enforce','families':['query'],'profile_version':PROFILE},targets=lambda c:CAT)
    t=p.begin(ctx,'e','为需求75登记跟进')
    try:
        e=p.envelope();d=e.data;step=d['allowed_next_steps'][0]
        plan={'envelope_fingerprint':e.digest,'segments':[{'kind':'locked','block_id':b['id']} for b in d['protected_blocks']]+[{'kind':'text','intent':'question','text':step['text'],'claim_ids':[],'next_step_ids':[step['id']]}],'omitted_optional_claim_ids':[]}
        candidate,reason=p.validate(plan,e,6000)
        assert candidate and reason in ('candidate','source_projection')
    finally:p.end(t)


def test_offline_shadow_replay_records_candidate_without_delivery():
    from am_response.evaluation import replay_frozen
    ctx=AccessContext('t','a','u','c',is_owner=True,content_expires_at=1000)
    p=ResponsePipeline({'mode':'shadow'},clock=lambda:100);token=p.begin(ctx,'e','进展')
    p.record('read_information',{}, {'facts':[{'fact_id':'f','field':'progress','value':'预计明天完成，尚未验收。'}],'complete_response':True,'has_more':False},'read')
    e=p.envelope();p.end(token)
    calls=[]
    class Model:
        def complete(self,prompt,**kw):
            calls.append(prompt)
            return SimpleNamespace(text=json.dumps({'type':'response_plan','plan':{'snapshot':e.digest[:16],
                'segments':[{'kind':'text','intent':'answer','text':'根据记录，预估明天完成，还没有验收。','refs':[0]}]+[{'kind':'locked','ref':i} for i,b in enumerate(e.data['protected_blocks'])], 'omitted':[]}},ensure_ascii=False))
    out=replay_frozen(Model(),{'envelope':e.data,'user_question':'进展','legacy_text':'预计明天完成，尚未验收。'},settings={'mode':'enforce','profile_version':PROFILE,'families':['analysis']},clock=lambda:101)
    assert out['observation_kind']=='offline_replay' and out['candidate'] and out['accepted']
    assert out['adopted'] is False and out['business_calls']==0 and out['actual_delivery'] is False and len(calls)==1

@pytest.mark.parametrize('change',['permission','source_version'])
def test_goal_resume_rechecks_current_scope_and_global_source(tmp_path,change):
    from am_outcome.goals import GoalJournal
    ctx=AccessContext('t','a','u','c',is_owner=True,allowed_project_ids=frozenset({'p'}),content_expires_at=1000,source_access_version='v1')
    store=ConversationStore(tmp_path/'c.db',clock=lambda:100)
    GoalJournal(store,ctx,'first','为需求75登记跟进',CAT)
    changed=replace(ctx,allowed_project_ids=frozenset()) if change=='permission' else replace(ctx,source_access_version='v2')
    with pytest.raises(ConversationError,match='SOURCE_ACCESS_CHANGED'):GoalJournal(store,changed,'next','继续',CAT)
    store.close()


def test_dependency_shadow_uses_current_record_lookup():
    from am_outcome.evidence import EvidenceBundle
    ctx=AccessContext('t','a','u','c',is_owner=True,content_expires_at=1000)
    calls=[]
    def lookup(ctx,old):
        calls.append(old)
        return {'objects':[dict(d,content_hash='different') for d in old['objects']]}
    p=ResponsePipeline({'mode':'canonical'},dependency_lookup=lookup,clock=lambda:100)
    token=p.begin(ctx,'e','查询');raw={'id':'p','fields':{'progress':'预计完成'},'snapshot':{'version':'1'}}
    raw['evidence_bundle']=EvidenceBundle.build(raw,scope=ctx.scope,expires=1000).data
    try:
        p.record('read_project',{'project_id':'p'},raw,'read');data=p.envelope().data
        assert calls and data['dependencies']['shadow_observations'][0]['verdict']['decision']=='content_changed'
        assert data['dependencies']['policy']=='global_guard_retained'
    finally:p.end(token)


def test_query_and_document_use_same_native_bundle(response):
    from types import MethodType
    from am_information import AMInformation
    from fs_agent.document_standards import DocumentStandards
    conv,h=response;am,g,s,api,clock,port=conv[0]
    info=SimpleNamespace(am=am,store=SimpleNamespace(access_version=lambda:'info-v1'),query=lambda row,subject:{'facts':[],'coverage':{},'gaps':[],'version':'v1'})
    info.evidence_bundle=MethodType(AMInformation.evidence_bundle,info)
    am.information=info;g.logic.shared_evidence=info.evidence_bundle
    row=incoming(response,'读取需求75');pid=project(conv)
    with h.bridge.request_context(row) as ctx:
        token=h.bridge.agent.response_pipeline.begin(ctx,row['id'],row['body'])
        try:result=h.bridge.projects.read_project(ctx,pid)
        finally:h.bridge.agent.response_pipeline.end(token)
    standards=DocumentStandards(g.logic,{'ledger':{'url':'https://example.invalid/synthetic'}})
    project_result,source=standards.project_evidence(row,{'project_code':'需求75'},lambda:True,999999)
    assert project_result['id']==pid
    assert source['evidence_bundle_id']==result['evidence_bundle']['bundle_id']


def test_single_explicit_matter_cannot_be_satisfied_by_another_write():
    goals,complete=resolve_goals('为需求75登记跟进：确认油脂交期',CAT)
    wrong=adapt('create_followup',{'project_id':'p','description':'核对测试排期'},{'item':{'id':'wrong','version':1,'state':'open'}},'local',key='wrong')
    assert check_goals(goals,complete,[wrong])[1]!='fulfilled'
    right=adapt('create_followup',{'project_id':'p','description':'确认油脂交期'},{'item':{'id':'right','version':1,'state':'open'}},'local',key='right')
    assert check_goals(goals,complete,[right])[1]=='fulfilled'
    # Correcting the requested goal does not erase an unintended committed write.
    assert check_goals(goals,complete,[wrong,right])[1]=='partial'


def test_read_query_does_not_invent_missing_action_parameters():
    goals,complete=resolve_goals('需求75关键日期',CAT)
    assert goals==[] and complete is False


def test_fastpath_result_is_host_owned_in_outcome(response):
    conv,h=response;execute(response,'需求75关键日期')
    data=presentations(h)[-1]['outcome']
    assert data['protected_blocks'][0]['id']=='fastpath-result'
    assert not data['allowed_next_steps']


def test_natural_required_clock_question_can_pass_without_fake_claims():
    ctx=AccessContext('t','a','u','c',is_owner=True)
    p=ResponsePipeline({'mode':'enforce','families':['query'],'profile_version':PROFILE},targets=lambda c:CAT)
    t=p.begin(ctx,'e','明天提醒我处理需求75')
    try:
        e=p.envelope();step=e.data['allowed_next_steps'][0]
        plan={'envelope_fingerprint':e.digest,'segments':[{'kind':'locked','block_id':b['id']} for b in e.data['protected_blocks']]+[{'kind':'text','intent':'question','text':'明天几点提醒你？','claim_ids':[],'next_step_ids':[step['id']]}],'omitted_optional_claim_ids':[]}
        text,reason=p.validate(plan,e,6000)
        assert text and reason=='candidate'
        assert not p.needs_repair()
    finally:p.end(t)


def test_personal_reminder_keeps_clock_obligation_without_project():
    goals,complete=resolve_goals('明天提醒我处理合成包装确认。',CAT)
    assert complete and len(goals)==1 and goals[0]['operation']=='schedule_reminder'
    assert goals[0]['project_id'] is None
    from am_response.semantics import next_steps
    progress,_=check_goals(goals,complete,[])
    steps=next_steps(progress,[])
    assert len(steps)==1 and steps[0]['missing']=='clock' and steps[0]['date_context']=='明天'


def test_personal_reminder_is_not_satisfied_by_group_plan():
    goals,complete=resolve_goals('明天09:00提醒我处理合成包装确认。',CAT)
    wrong=adapt('schedule_reminder',{'target':'group','body':'合成包装确认'},{'status':'succeeded','verified':True,'receipt_id':'synthetic-plan'},'external',key='u')
    assert check_goals(goals,complete,[wrong])[1]!='fulfilled'


def test_invalid_adoption_receipt_cannot_retain_success_prose():
    result=adapt('edit_document',{'operation':'adopt','draft_id':'d','version':1,'content_hash':'h'},
        {'draft_id':'d','version':1,'state':'ready','content_hash':'h','accepted_hash':None,'message':'已采用当前版本文字。'},'local',key='u')
    assert result['completion']=='blocked' and '已采用' not in result['status_text']


def test_overlapping_goal_terms_terminate_and_preserve_entire_clause():
    for text in ('保存提醒我跟进笔记','为需求75保存跟进笔记：核对测试排期','为需求75创建跟进并保存笔记'):
        goals,complete=resolve_goals(text,CAT)
        assert not complete and goals and any(text in ' '.join(g['request_spans']) for g in goals)


def test_small_remaining_budget_is_rejected_before_provider_dispatch():
    from am_conversation.model import CoordinatorModel
    import time
    calls=[]
    class Provider:
        def complete(self,*a,**kw):calls.append(kw);raise AssertionError('must not dispatch')
    m=CoordinatorModel(Provider(),min_dispatch_seconds=60);token=m.set_deadline(time.monotonic()+20)
    try:
        with pytest.raises(ConversationError,match='MODEL_BUDGET_EXHAUSTED'):m.complete([{'role':'user','content':'查询'}],[])
        assert not calls
    finally:m.reset_deadline(token)


def test_budget_stop_preserves_one_commit_and_remaining_goal(response):
    conv,h=response;p=project(conv);h.bridge.agent.config=replace(h.bridge.agent.config,goal_tracking=True)
    model=h.bridge.agent.model;original=model.complete;count=[]
    def limited(*args,**kwargs):
        count.append(1)
        if len(count)>1:raise ConversationError('MODEL_BUDGET_EXHAUSTED')
        return original(*args,**kwargs)
    model.complete=limited
    execute(response,'为需求75分别登记跟进：确认油脂交期；核对测试排期',[call('create_followup',{'project_id':p,'description':'确认油脂交期'})])
    assert len(h.s.rows('SELECT * FROM action_items'))==1
    assert h.tasks.lane_status()['state']=='idle' and not h.s.meta('provider_pause')
    saved=presentations(h)[-1]
    assert saved['dispatch_budget_exhausted'] and saved['business_completion']=='partial'
    assert '尚未确认完成' in conv[0][3].sent[-1]['body']


def test_reconcile_read_retains_required_receipt_and_complete_query():
    action='action_'+'a'*32
    ctx=AccessContext('t','a','u','c',is_owner=True);p=ResponsePipeline({'mode':'canonical'})
    token=p.begin(ctx,'e','核对发送 '+action)
    try:
        p.record('reconcile_send',{'action_id':action},{'status':'succeeded','verified':True,'receipt_id':'m'},'read')
        data=p.envelope().data
        assert data['completion']=='fulfilled'
        assert data['work_units'][0]['effect']=='read' and data['work_units'][0]['receipt']=='m'
        assert data['protected_blocks'][0]['required']
    finally:p.end(token)


def test_sending_status_question_does_not_create_send_obligation():
    assert resolve_goals('查询需求75的通知发送了吗？',CAT)==([],False)


def test_reported_claim_paraphrase_requires_source_attribution():
    from am_response.semantics import SemanticAssessor
    ctx=AccessContext('t','a','u','c',is_owner=True);p=ResponsePipeline({'mode':'canonical'})
    token=p.begin(ctx,'e','查询')
    try:
        p.record('read_information',{}, {'facts':[{'fact_id':'f','field':'progress','value':'预计明天完成，尚未验收。','assertion_type':'reported','business_state':'unconfirmed'}],'complete_response':True,'has_more':False},'read')
        e=p.envelope();plan={'segments':[{'kind':'text','intent':'answer','text':'预估明天完成，还没有验收。','claim_ids':[e.data['claims'][0]['id']]}]}
        assert SemanticAssessor()(plan,e)['decision']=='indeterminate'
    finally:p.end(token)


def test_quoted_fact_is_attributed_but_required_question_is_not_a_source_quote():
    ctx=AccessContext('t','a','u','c',is_owner=True);p=ResponsePipeline({'mode':'enforce','families':['analysis'],'profile_version':PROFILE})
    t=p.begin(ctx,'e','查询')
    try:
        p.record('read_information',{}, {'facts':[{'fact_id':'f','subject_id':'p','field':'progress','value':'尚未验收。','assertion_type':'reported'}],'complete_response':True,'has_more':False},'read')
        e=p.envelope();plan={'envelope_fingerprint':e.digest,'segments':[{'kind':'text','intent':'answer','text':'尚未验收。','claim_ids':[e.data['claims'][0]['id']]}]+[{'kind':'locked','block_id':b['id']} for b in e.data['protected_blocks']],'omitted_optional_claim_ids':[]}
        text,kind=p.validate(plan,e,6000)
        assert kind=='source_projection' and text.startswith('资料记录：')
    finally:p.end(t)


def test_unresolved_clause_keeps_known_reminder_duty_visible():
    ctx=AccessContext('t','a','u','c',is_owner=True)
    p=ResponsePipeline({'mode':'canonical'},targets=lambda c:CAT)
    t=p.begin(ctx,'e','为需求75整理知识规则，明天提醒我')
    try:
        data=p.envelope().data
        assert not data['intent']['goal_set_complete']
        assert any('明天提醒我' in b['text'] for b in data['protected_blocks'])
        assert any(s.get('missing')=='clock' for s in data['allowed_next_steps'])
    finally:p.end(t)


def _pending_reminder_goal(tmp_path,*,ttl_seconds=1800):
    from am_outcome.goals import GoalJournal
    ctx=AccessContext('t','a','u','c',is_owner=True,content_expires_at=1000,source_access_version='v1')
    store=ConversationStore(tmp_path/'continuation.db',clock=lambda:100)
    question='明天09:30提醒我确认油脂交期'
    args={'target':'self','body':'确认油脂交期','frequency':'once','at':'2030-03-02T09:30:00+08:00'}
    store.claim_event(ctx,'first',question)
    goal=GoalJournal(store,ctx,'first',question,CAT)
    assert goal.before('schedule_reminder',args,'external') is None
    action=store.create_action(ctx,tool_name='schedule_reminder',arguments=args,preview='合成提醒预览',ttl_seconds=ttl_seconds)
    goal.record('schedule_reminder',args,{'status':'draft','action_id':action['id'],'version':1,'preview':action['preview'],'executed':False},'external')
    return store,ctx,args,action


def _claim_test_action(store,ctx,action):
    store.mark_presented(ctx,action['id'],expected_version=action['version'],event_id='first')
    store.approve_action(ctx,action['id'],expected_version=action['version'],digest=action['digest'])
    assert store.begin_execution(ctx,action['id'],expected_version=action['version'])['claimed']


def test_confirmed_goal_restores_native_receipt_and_call_cache_after_restart(tmp_path):
    from am_outcome.goals import GoalJournal
    store,ctx,args,action=_pending_reminder_goal(tmp_path);_claim_test_action(store,ctx,action)
    receipt={'status':'succeeded','verified':True,'receipt_id':'synthetic-plan','message':'合成提醒计划已启用。'}
    store.finish_execution(ctx,action['id'],status='succeeded',result=receipt)
    assert 'result' not in store.action_metadata(ctx,action['id'])
    store.close();store=ConversationStore(tmp_path/'continuation.db',clock=lambda:101)
    resumed=GoalJournal(store,ctx,'next','继续',CAT)
    assert resumed.fulfilled()
    cached=resumed.before('schedule_reminder',args,'external')
    assert cached==receipt
    resumed.record('schedule_reminder',args,cached,'external')
    assert resumed.fulfilled()
    assert not store.begin_execution(ctx,action['id'],expected_version=1)['claimed']
    assert len(store.list_actions(ctx,active_only=False))==1
    store.close()


def test_native_unknown_goal_blocks_until_verified_reconciliation(tmp_path):
    from am_outcome.goals import GoalJournal
    store,ctx,args,action=_pending_reminder_goal(tmp_path);_claim_test_action(store,ctx,action)
    store.finish_execution(ctx,action['id'],status='unknown',result={'code':'SYNTHETIC_INTERRUPTED'})
    for event in ('continue-one','continue-two'):
        resumed=GoalJournal(store,ctx,event,'继续',CAT)
        assert not resumed.fulfilled() and not resumed.data['ambiguous']
        with pytest.raises(ConversationError,match='GOAL_RESULT_RECONCILE_REQUIRED'):
            resumed.before('schedule_reminder',args,'external')
    receipt={'status':'succeeded','verified':True,'receipt_id':'synthetic-plan'}
    store.finish_execution(ctx,action['id'],status='succeeded',result=receipt)
    resumed=GoalJournal(store,ctx,'verified','继续',CAT)
    assert resumed.fulfilled() and resumed.before('schedule_reminder',args,'external')==receipt
    assert not store.begin_execution(ctx,action['id'],expected_version=1)['claimed']
    store.close()


def test_changed_approved_payload_does_not_fulfill_old_goal(tmp_path):
    from am_outcome.goals import GoalJournal
    store,ctx,args,action=_pending_reminder_goal(tmp_path)
    action=store.revise_action(ctx,action['id'],expected_version=1,arguments=dict(args,body='另一事项'),preview='修订后的预览')
    _claim_test_action(store,ctx,action)
    store.finish_execution(ctx,action['id'],status='succeeded',result={'status':'succeeded','verified':True,'receipt_id':'new-plan'})
    resumed=GoalJournal(store,ctx,'next','继续',CAT)
    assert not resumed.fulfilled() and resumed.data['ambiguous']
    with pytest.raises(ConversationError,match='GOAL_SELECTION_REQUIRED'):resumed.before('schedule_reminder',args,'external')
    store.close()


@pytest.mark.parametrize('terminal',['cancelled','expired','failed'])
def test_closed_pending_goal_cannot_create_a_replacement_on_repeated_call(tmp_path,terminal):
    from am_outcome.goals import GoalJournal
    store,ctx,args,action=_pending_reminder_goal(tmp_path,ttl_seconds=1 if terminal=='expired' else 1800)
    if terminal=='cancelled':store.cancel_action(ctx,action['id'],expected_version=1)
    elif terminal=='failed':
        _claim_test_action(store,ctx,action)
        store.finish_execution(ctx,action['id'],status='failed',result={'status':'failed'})
    else:
        # Expire only the preview, while the parent goal still has content time.
        store._now=lambda:102
    resumed=GoalJournal(store,ctx,'next','继续',CAT)
    assert not resumed.fulfilled()
    cached=resumed.before('schedule_reminder',args,'external')
    assert cached['status']==terminal and cached['verified'] is False
    resumed.record('schedule_reminder',args,cached,'external')
    assert resumed.before('schedule_reminder',args,'external')==cached
    assert len(store.list_actions(ctx,active_only=False))==1
    store.close()


def test_readonly_reconciliation_unit_is_not_an_execution_alias(tmp_path):
    from am_outcome.goals import GoalJournal
    store,ctx,args,action=_pending_reminder_goal(tmp_path);_claim_test_action(store,ctx,action)
    store.finish_execution(ctx,action['id'],status='unknown',result={'code':'SYNTHETIC_INTERRUPTED'})
    pending=GoalJournal(store,ctx,'lookup','继续',CAT)
    pending.record('reconcile_send',{'action_id':action['id']},{'status':'unknown','action_id':action['id']},'read')
    resumed=GoalJournal(store,ctx,'next','继续',CAT)
    assert not resumed.data['ambiguous'] and not resumed.fulfilled()
    with pytest.raises(ConversationError,match='GOAL_RESULT_RECONCILE_REQUIRED'):resumed.before('schedule_reminder',args,'external')
    store.close()


def test_success_without_verifiable_receipt_cannot_recreate_pending_action(tmp_path):
    from am_outcome.goals import GoalJournal
    store,ctx,args,action=_pending_reminder_goal(tmp_path);_claim_test_action(store,ctx,action)
    store.finish_execution(ctx,action['id'],status='succeeded',result={'status':'succeeded','verified':False})
    resumed=GoalJournal(store,ctx,'next','继续',CAT)
    assert not resumed.fulfilled()
    assert resumed.before('schedule_reminder',args,'external')=={'status':'succeeded','verified':False}
    assert len(store.list_actions(ctx,active_only=False))==1
    store.close()


def test_goal_receipt_restore_cannot_use_metadata_to_bypass_source_guard(tmp_path):
    from am_outcome.goals import GoalJournal
    store,ctx,args,action=_pending_reminder_goal(tmp_path);_claim_test_action(store,ctx,action)
    store.finish_execution(ctx,action['id'],status='succeeded',result={'status':'succeeded','verified':True,'receipt_id':'synthetic-plan'})
    with store._connection(write=True) as db:db.execute("UPDATE conversation_actions SET source_access_version='v2' WHERE id=?",(action['id'],))
    assert store.action_metadata(ctx,action['id'])['status']=='succeeded'
    with pytest.raises(ConversationError,match='SOURCE_ACCESS_CHANGED'):GoalJournal(store,ctx,'next','继续',CAT)
    store.close()


def test_known_failed_local_goal_retains_original_explicit_retry_path(tmp_path):
    from am_outcome.goals import GoalJournal
    ctx=AccessContext('t','a','u','c',is_owner=True,content_expires_at=1000,allowed_project_ids=frozenset({'p'}))
    store=ConversationStore(tmp_path/'local-retry.db',clock=lambda:100)
    args={'project_id':'p','description':'核对测试排期'}
    first=GoalJournal(store,ctx,'first','为需求75登记跟进：核对测试排期',CAT)
    assert first.before('create_followup',args,'local') is None
    first.record('create_followup',args,{'status':'failed'},'local')
    resumed=GoalJournal(store,ctx,'next','继续',CAT)
    assert resumed.before('create_followup',args,'local') is None
    store.close()


def test_goal_receipt_restore_retains_owner_role_requirement(tmp_path):
    from am_outcome.goals import GoalJournal
    store,ctx,args,action=_pending_reminder_goal(tmp_path);_claim_test_action(store,ctx,action)
    store.finish_execution(ctx,action['id'],status='succeeded',result={'status':'succeeded','verified':True,'receipt_id':'synthetic-plan'})
    with pytest.raises(ConversationError,match='OWNER_REQUIRED'):GoalJournal(store,replace(ctx,is_owner=False),'next','继续',CAT)
    store.close()
