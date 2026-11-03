"""Independent-review counterexamples using native stores and synthetic I/O."""
from dataclasses import replace
import json
import pytest
from test_harness_response_v2 import response, presentations
from test_harness_host import harness, convo, ux, service, am_rig, base_rig, incoming, execute, call, answer, project
from am_outcome.adapters import adapt
from am_outcome.completion import resolve_goals, check_goals
from am_outcome.goals import GoalJournal
from am_conversation.store import ConversationStore
from am_conversation.types import AccessContext, ConversationError
from am_response.pipeline import ResponsePipeline
from am_response.semantics import PROFILE

CAT=[{'id':'p','title':'需求75','aliases':[]}]
REQUEST='为需求75分别登记跟进：确认交期；确认交期变更原因'

def test_F01_two_overlapping_matters_create_two_native_items(response):
    conv,h=response;pid=project(conv)
    h.bridge.agent.config=replace(h.bridge.agent.config,goal_tracking=True)
    execute(response,REQUEST,[call('create_followup',{'project_id':pid,'description':s}) for s in ('确认交期','确认交期变更原因')])
    items=h.s.rows('SELECT * FROM action_items')
    assert len(items)==2
    assert {x['description'] for x in items}=={'确认交期','确认交期变更原因'}
    assert presentations(h)[-1]['business_completion']=='fulfilled'

def test_F01_one_native_receipt_cannot_satisfy_two_steps():
    goals,complete=resolve_goals(REQUEST,CAT)
    units=[adapt('create_followup',{'project_id':'p','description':s},{'item':{'id':'one','version':1,'state':'open'}},'local',key=str(i)) for i,s in enumerate(('确认交期','确认交期变更原因'))]
    assert check_goals(goals,complete,units)[1]!='fulfilled'

@pytest.mark.parametrize('changed',['确认油脂交期 ','核实油脂交货日期'])
def test_F02_lost_result_continuation_never_creates_again(response,changed):
    conv,h=response;pid=project(conv)
    h.bridge.agent.config=replace(h.bridge.agent.config,goal_tracking=True)
    tool=h.bridge.registry._tools['create_followup'];original=tool.handler
    commits=[]
    def lost(*args):
        result=original(*args);commits.append(result['item']['id'])
        raise RuntimeError('SYNTHETIC_RESULT_LOST_AFTER_COMMIT')
    h.bridge.registry._tools['create_followup']=replace(tool,handler=lost)
    config=h.bridge.agent.config;h.bridge.agent.config=replace(config,max_rounds=1)
    execute(response,'为需求75登记跟进：确认油脂交期',[call('create_followup',{'project_id':pid,'description':'确认油脂交期'}),answer('结果待核对')])
    conv[1].outputs.clear();h.bridge.agent.config=config
    assert len(h.s.rows('SELECT * FROM action_items'))==1
    h.bridge.registry._tools['create_followup']=tool
    conv[1].outputs.extend([call('create_followup',{'project_id':pid,'description':changed}),answer('结果待核对')])
    h.admit(incoming(response,'继续'));h.run_once()
    assert len(h.s.rows('SELECT * FROM action_items'))==1
    assert h.s.rows('SELECT id FROM action_items')[0]['id']==commits[0]
    with h.bridge.store._connection() as db:
        goal=json.loads(db.execute('SELECT data_json FROM conversation_goals_v2').fetchone()[0])
    saved=list(goal['calls'].values())
    assert len(saved)==1 and saved[0]['result']['verified'] is True
    assert saved[0]['arguments']['description']=='确认油脂交期'
    assert saved[0]['result']['reconciled_operation_id']
    assert goal['completion']=='fulfilled'

def fact_pipeline(fact,question='需求75进展如何，明天提醒我'):
    ctx=AccessContext('t','a','u','c',is_owner=True)
    pipe=ResponsePipeline({'mode':'enforce','families':['query','analysis'],'profile_version':PROFILE},targets=lambda c:CAT)
    token=pipe.begin(ctx,'e',question)
    pipe.record('read_information',{}, {'facts':[dict(fact_id='f',**fact)],'complete_response':True,'has_more':False},'read')
    return pipe,token,pipe.envelope()

def compact(e,segments,omitted=None):
    return {'snapshot':e.digest[:16],'segments':segments+[{'kind':'locked','ref':i} for i,_ in enumerate(e.data['protected_blocks'])],'omitted':omitted or []}

@pytest.mark.parametrize('attack',['question_ref','omitted'])
def test_F03_question_does_not_cover_required_fact(attack):
    p,t,e=fact_pipeline({'field':'progress','value':'测试尚未完成'})
    try:
        plan=compact(e,[{'kind':'text','intent':'question','text':'明天几点提醒你？','refs':[0] if attack=='question_ref' else [],'next':[0]}],[0] if attack=='omitted' else [])
        assert p.validate(plan,e,6000)[0] is None
    finally:p.end(t)

def test_F03_fact_statement_and_legal_question_pass():
    p,t,e=fact_pipeline({'field':'progress','value':'测试尚未完成'})
    try:
        plan=compact(e,[{'kind':'text','intent':'answer','text':'根据记录，测试尚未完成。','refs':[0]}, {'kind':'text','intent':'question','text':'明天几点提醒你？','refs':[],'next':[0]}])
        assert p.validate(plan,e,6000)[0]
    finally:p.end(t)

@pytest.mark.parametrize('text,accepted',[('根据记录，明天完成。',False),('根据记录，预计明天完成。',True)])
def test_F04_forecast_metadata_is_a_required_qualifier(text,accepted):
    p,t,e=fact_pipeline({'field':'forecast','value':'明天完成','assertion_type':'forecast','evidence':{'quote':'预计明天完成'}},'需求75进展如何')
    try:
        result=p.validate(compact(e,[{'kind':'text','intent':'answer','text':text,'refs':[0]}]),e,6000)
        assert bool(result[0]) is accepted
    finally:p.end(t)

def journal_fixture(tmp_path,request=REQUEST):
    ctx=AccessContext('t','a','u','c',is_owner=True,content_expires_at=1000,allowed_project_ids=frozenset({'p'}))
    store=ConversationStore(tmp_path/'goals.db',clock=lambda:100)
    return store,ctx,GoalJournal(store,ctx,'first',request,CAT)

def test_F01_cache_retains_original_call_and_step(tmp_path):
    store,ctx,j=journal_fixture(tmp_path)
    args={'project_id':'p','description':'确认交期'};raw={'item':{'id':'one','version':1,'state':'open'}}
    assert j.before('create_followup',args,'local') is None
    unit=j.record('create_followup',args,raw,'local')
    changed=dict(args,description='确认交期 ')
    assert j.before('create_followup',changed,'local')==raw
    replay=j.record('create_followup',changed,raw,'local')
    assert replay==unit and replay['target']==args
    assert len(j.data['units'])==len(j.data['calls'])==1
    assert replay['goal_step_id']==j.data['goals'][0]['step_id'] and replay['submission_id']
    store.close()

def test_F01_duplicate_model_calls_commit_once(response):
    conv,h=response;pid=project(conv);h.bridge.agent.config=replace(h.bridge.agent.config,goal_tracking=True)
    execute(response,REQUEST,[call('create_followup',{'project_id':pid,'description':s}) for s in ('确认交期','确认交期 ','确认交期变更原因')])
    assert len(h.s.rows('SELECT * FROM action_items'))==2
    units=[u for u in presentations(h)[-1]['outcome']['work_units'] if u['operation']=='create_followup']
    assert len(units)==2 and len({u['submission_id'] for u in units})==2

@pytest.mark.parametrize('changed',['确认交期 ','核实交货日期'])
def test_F02_unknown_without_native_proof_stays_barred_after_restart(tmp_path,changed):
    store,ctx,j=journal_fixture(tmp_path,'为需求75登记跟进：确认交期')
    assert j.before('create_followup',{'project_id':'p','description':'确认交期'},'local') is None
    store.close();store=ConversationStore(tmp_path/'goals.db',clock=lambda:101)
    resumed=GoalJournal(store,ctx,'next','继续',CAT,reconcile=lambda *a:None)
    with pytest.raises(ConversationError,match='GOAL_RESULT_RECONCILE_REQUIRED'):
        resumed.before('create_followup',{'project_id':'p','description':changed},'local')
    assert len(resumed.data['calls'])==1 and not resumed.fulfilled()
    store.close()

def test_F01_ambiguous_goal_requires_selection(tmp_path):
    store,ctx,j=journal_fixture(tmp_path,'为需求75分别登记跟进；登记跟进')
    with pytest.raises(ConversationError,match='GOAL_SELECTION_REQUIRED'):
        j.before('create_followup',{'project_id':'p','description':'未指定的事项'},'local')
    assert not j.data['calls'];store.close()

def test_F03_frozen_required_set_and_real_semantic_coverage():
    p,t,e=fact_pipeline({'field':'progress','value':'测试尚未完成'})
    try:
        cid=e.data['claims'][0]['id']
        assert e.data['required_claim_ids']==[cid] and e.data['allowed_omission_ids']==[]
        plan=compact(e,[{'kind':'text','intent':'answer','text':'根据记录，测试尚未完成。','refs':[0]}])
        p.assessor=lambda *a:{'profile_version':PROFILE,'decision':'pass','checks':[]}
        assert p.validate(plan,e,6000)==(None,'semantic_fact_coverage_missing')
        plan['required_claim_ids']=[]
        assert p.validate(plan,e,6000)[0] is None
    finally:p.end(t)

@pytest.mark.parametrize('field,value,metadata,good,bad',[
    ('forecast','明天完成',{'assertion_type':'forecast'},'预计明天完成','明天完成'),
    ('progress','核对排期',{'assertion_type':'recommendation'},'建议核对排期','核对排期'),
    ('progress','测试未完成',{'polarity':'negative'},'测试未完成','测试已完成'),
    ('progress','明天测试完成',{'time_scope':'明天'},'明天测试完成','今天测试完成'),
    ('progress','仅样机测试完成',{'scope':'仅样机'},'仅样机测试完成','测试完成'),
    ('progress','报告已提交',{'business_state':'submitted'},'报告已提交','报告已验收'),
])
def test_F04_typed_constraints_cannot_be_replaced_by_attribution(field,value,metadata,good,bad):
    p,t,e=fact_pipeline(dict(field=field,value=value,**metadata),'需求75进展如何')
    try:
        for text,expected in [(good,True),(bad,False)]:
            candidate,_=p.validate(compact(e,[{'kind':'text','intent':'answer','text':'根据记录，'+text+'。','refs':[0]}]),e,6000)
            assert bool(candidate) is expected
    finally:p.end(t)

@pytest.mark.parametrize('text,accepted',[
    ('根据记录，需求75项目的试样确认负责人是AR1合成甲工。',True),
    ('根据记录，需求75的试样确认负责人为AR1合成甲工。',True),
    ('根据记录，需求76项目的试样确认负责人是AR1合成甲工。',False),
    ('根据记录，需求75项目的测试负责人是AR1合成甲工。',False),
    ('根据记录，需求75项目的试样确认负责人是AR2合成乙工。',False),
    ('根据记录，AR1合成甲工项目的试样确认负责人是需求75。',False),
    ('根据记录，需求75项目的试样确认负责人是AR1合成甲工，已批准。',False),
])
def test_supported_owner_relation_preserves_subject_role_value(text,accepted):
    p,t,e=fact_pipeline({'field':'人员与职责','value':'试样确认负责人：AR1合成甲工','subject_id':'p','subject_label':'需求75'},'需求75谁负责')
    try:
        assert bool(p.validate(compact(e,[{'kind':'text','intent':'answer','text':text,'refs':[0]}]),e,6000)[0]) is accepted
    finally:p.end(t)

@pytest.mark.parametrize('text,accepted',[
    ('根据记录，需求75的进展为测试尚未完成。',True),
    ('根据记录，需求75项目进展是测试还没有完成。',True),
    ('根据记录，需求75的进展为：测试尚未完成。',True),
    ('根据记录，需求75的测试尚未完成。',True),
    ('根据记录，需求75测试尚未完成。',True),
    ('根据记录，需求76的进展为测试尚未完成。',False),
    ('根据记录，需求75的进展为测试已完成。',False),
    ('根据记录，需求75的进展为负责人认为测试尚未完成。',False),
])
def test_supported_progress_relation_is_an_ordered_proposition(text,accepted):
    p,t,e=fact_pipeline({'field':'progress','value':'测试尚未完成','subject_id':'p','subject_label':'需求75'},'需求75进展如何')
    try:
        assert bool(p.validate(compact(e,[{'kind':'text','intent':'answer','text':text,'refs':[0]}]),e,6000)[0]) is accepted
    finally:p.end(t)

@pytest.mark.parametrize('text,accepted',[
    ('根据记录，需求75预计明天完成。',True),
    ('根据记录，需求76预计明天完成。',False),
    ('根据记录，需求75明天完成。',False),
    ('根据记录，需求75预计今天完成。',False),
])
def test_subject_forecast_relation_keeps_qualifiers(text,accepted):
    p,t,e=fact_pipeline({'field':'forecast','value':'明天完成','assertion_type':'forecast','subject_id':'p','subject_label':'需求75'},'需求75进展如何')
    try:
        assert bool(p.validate(compact(e,[{'kind':'text','intent':'answer','text':text,'refs':[0]}]),e,6000)[0]) is accepted
    finally:p.end(t)

def test_quote_negation_cannot_borrow_another_claim_qualifier():
    p,t,e=fact_pipeline({'field':'progress','value':'完成','subject_id':'p','evidence':{'quote':'未完成'}},'需求75进展如何')
    try:
        p.record('read_information',{}, {'facts':[{'fact_id':'other','field':'progress','subject_id':'p','value':'测试未完成'}],'complete_response':True},'read')
        e=p.envelope()
        plan=compact(e,[{'kind':'text','intent':'answer','text':'根据记录，完成。测试未完成。','refs':[0,1]}])
        assert p.validate(plan,e,6000)[0] is None
    finally:p.end(t)

def test_attributed_verbatim_value_is_source_projection_not_free_credit():
    p,t,e=fact_pipeline({'field':'forecast','value':'明天完成','assertion_type':'forecast'},'需求75进展如何')
    try:
        candidate,reason=p.validate(compact(e,[{'kind':'text','intent':'answer','text':'根据记录，预计明天完成。','refs':[0]}]),e,6000)
        assert candidate and reason=='source_projection'
    finally:p.end(t)

def test_F04_canonical_fallback_keeps_forecast():
    from types import SimpleNamespace
    from am_conversation.types import AgentReply
    p,t,e=fact_pipeline({'field':'forecast','value':'明天完成','assertion_type':'forecast','evidence':{'quote':'预计明天完成'}},'需求75进展如何')
    try:
        state=p.state();state['proposal_outcome']=e
        p.proposed(compact(e,[{'kind':'text','intent':'answer','text':'根据记录，明天完成。','refs':[0]}]))
        reply,pres=p.finish(SimpleNamespace(config=SimpleNamespace(max_reply_chars=6000),_guard=lambda *a:None,_checkpoint=lambda *a:None),state['ctx'],AgentReply('e','明天完成','answered'))
        assert '预计明天完成' in reply.text and not pres['adopted']
    finally:p.end(t)

def test_F03_only_host_selected_unrelated_field_is_optional():
    p,t,e=fact_pipeline({'field':'progress','value':'测试尚未完成'},'需求75进展如何')
    try:
        p.record('read_information',{}, {'facts':[{'fact_id':'owner','field':'负责人','value':'AR1合成甲工'}],'complete_response':True},'read')
        e=p.envelope();assert len(e.data['required_claim_ids'])==len(e.data['allowed_omission_ids'])==1
        plan=compact(e,[{'kind':'text','intent':'answer','text':'根据记录，测试尚未完成。','refs':[0]}],[1])
        assert p.validate(plan,e,6000)[0]
    finally:p.end(t)
