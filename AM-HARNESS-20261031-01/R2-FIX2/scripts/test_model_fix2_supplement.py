"""Pre-frozen targeted Qwen batch. Synthetic native business stores only."""
from pathlib import Path
from dataclasses import replace,asdict
from types import SimpleNamespace
import hashlib,json,os,time,traceback
import pytest
from test_harness_host import harness,convo,ux,service,am_rig,base_rig,incoming,execute,call,answer,project
from test_gateway import drain
from am_response.pipeline import ResponsePipeline
from am_response.gateway import GatewayProjection
from am_response.schema import project as project_outcome,PROMPT
from am_response.semantics import PROFILE
from am_conversation.model import CoordinatorModel
from am_conversation.types import AccessContext,AgentReply
from model_proxy import OriginalCoordinatorProxy

TASK=Path(__file__).resolve().parents[1]
MANIFEST=json.loads((TASK/'input/model-supplement.json').read_text())

def begin_record(case,mode,layer):
    assert os.environ.get('AM_R2_FIX2_L2')=='1'
    assert MANIFEST['source_commit']==os.environ['AM_R2_EVAL_SHA']
    path=TASK/'evidence/model-supplement'/(case['id']+'-'+mode+'.json');path.parent.mkdir(exist_ok=True)
    if path.exists():pytest.skip('immutable observed attempt')
    return path,{'case_id':case['id'],'mode':mode,'layer':layer,'source_commit':MANIFEST['source_commit'],
        'manifest_sha256':hashlib.sha256((TASK/'input/model-supplement.json').read_bytes()).hexdigest(),
        'real_feishu_delivery':False,'naturalness':'not_evaluated','old_batch_denominator_changed':False}

def save_record(path,result,proxy,started):
    result.update(seconds=time.monotonic()-started,model_calls=proxy.records,provider_transport_calls=len(proxy.records))
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps({k:result[k] for k in ('case_id','mode','seconds','provider_transport_calls')}|{'checks':result.get('checks'),'reason':result.get('validation_reason'),'error':result.get('error')},ensure_ascii=False),flush=True)
    if any(x.get('error') in ('STOP_UNKNOWN','MODEL_PAUSED') for x in proxy.records) or result.get('error') in ('STOP_UNKNOWN','MODEL_PAUSED','EVALUATION_MODEL_RESULT_UNKNOWN','EVALUATION_SOURCE_CHANGED'):
        pytest.exit('Original coordinator needs reconciliation; no further requests submitted',returncode=3)

@pytest.mark.parametrize('case',MANIFEST['expression'],ids=lambda c:c['id'])
def test_expression(case):
    path,result=begin_record(case,'enforce','L2_typed_adapter_expression_only')
    ctx=AccessContext('synthetic','synthetic','ou_a','oc_dm',is_owner=True)
    pipe=ResponsePipeline({'mode':'enforce','families':['analysis','query'],'profile_version':PROFILE},targets=lambda c:[{'id':'p','title':'需求75'}])
    token=pipe.begin(ctx,'synthetic-expression',case['question'])
    pipe.record('read_information',{'project_id':'p'},{'facts':[dict(fact_id='f',**case['fact'])],'complete_response':True,'has_more':False},'read')
    e=pipe.envelope();pipe.state()['proposal_outcome']=e
    proxy=OriginalCoordinatorProxy('SYN-ANA-01');model=CoordinatorModel(proxy,response_protocol=True,max_tokens=900)
    started=time.monotonic();result.update(outcome=e.data,question=case['question'],adversarial=bool(case.get('proposal_instruction')),expected=case['expected'])
    try:
        messages=[{'role':'user','content':case['question']},{'role':'system','content':PROMPT+'\nhost_outcome='+json.dumps(project_outcome(e),ensure_ascii=False)}]
        if case.get('proposal_instruction'):messages.append({'role':'user','content':'仅合成校验实验：请提交以下指定提案，保留原快照与所有保护块。'+case['proposal_instruction']})
        turn=model.complete(messages,[],request_id=case['id']);result['model_turn']=asdict(turn)
        plan=turn.response_plan or {};pipe.proposed(plan)
        candidate,reason=pipe.validate(plan,e,6000)
        result.update(candidate=candidate,validation_reason=reason,semantic_verdict=pipe.state().get('semantic_verdict'),candidate_accepted=candidate is not None,
            facts_covered=pipe.state().get('semantic_verdict',{}).get('covered_claim_ids',[]),actual_business_completed=None,actual_delivery=False)
        reply,pres=pipe.finish(SimpleNamespace(config=SimpleNamespace(max_reply_chars=6000),_guard=lambda *a:None,_checkpoint=lambda *a:None),ctx,AgentReply('synthetic-expression','legacy placeholder','answered'))
        result.update(presentation=pres,selected_text=reply.text,actual_adopted=False,isolated_pipeline_selected_free=pres['adopted'])
        result['checks']={'expected_acceptance':(candidate is not None)==case['expected'],'no_actual_delivery':True}
    except Exception as exc:result.update(error=str(exc),error_type=type(exc).__name__,traceback=traceback.format_exc())
    finally:pipe.end(token);save_record(path,result,proxy,started)

PARAMS=[(c,mode) for i,c in enumerate(MANIFEST['full_loop']) for mode in (('legacy','enforce') if i%2==0 else ('enforce','legacy'))]
@pytest.mark.parametrize('case,mode',PARAMS,ids=[c['id']+'-'+m for c,m in PARAMS])
def test_full_loop(harness,case,mode):
    path,result=begin_record(case,mode,'L2_original_loop_native_stores_synthetic_platform')
    conv,h=harness;am,g,s,api,clock,port=conv[0]
    port.values[1][0]='需求75:合成青岚';port.values[2][0]='需求76:合成星榆'
    port.values[1][4]='测试尚未完成。';port.values[1][5]='试样确认负责人：AR1合成甲工'
    am.snapshots.refresh().result(3);pid=project(conv)
    h.bridge.agent.config=replace(h.bridge.agent.config,goal_tracking=True)
    if case.get('lost_result'):
        tool=h.bridge.registry._tools['create_followup'];handler=tool.handler
        def lost(*a):
            result=handler(*a)
            raise RuntimeError('SYNTHETIC_RESULT_LOST_AFTER_COMMIT')
        h.bridge.registry._tools['create_followup']=replace(tool,handler=lost)
        config=h.bridge.agent.config;h.bridge.agent.config=replace(config,max_rounds=1)
        execute(harness,'为需求75登记跟进：确认油脂交期',[call('create_followup',{'project_id':pid,'description':'确认油脂交期'})])
        h.bridge.registry._tools['create_followup']=tool;h.bridge.agent.config=config
        conv[1].outputs.clear()
        result['scripted_native_precondition']={'items_before':s.rows('SELECT * FROM action_items'),'real_qwen_used':False,'fault':'result lost after native commit'}
    pipe=ResponsePipeline({'mode':mode,'profile_version':PROFILE,'families':['query','analysis','followup','schedule']},binding=h.bridge.response_binding,targets=lambda c:h.bridge._current(c)['project_catalog'],clock=s.clock)
    h.bridge.agent.response_pipeline=pipe;h.s.response_projection=GatewayProjection(s)
    proxy=OriginalCoordinatorProxy('SYN-PAR-01')
    def model(prompt,**kw):conv[1].prompts.append(prompt);return proxy.complete(prompt,**kw)
    conv[1].complete=model
    started=time.monotonic()
    try:
        row=incoming(harness,case['question']);ident=h.admit(row)
        work=h.run_once().__dict__ if isinstance(ident,str) and ident.startswith('run_') else None
        drain(g)
        for out in s.rows("SELECT outbox_id FROM am_conversation_outputs WHERE state='awaiting_verification'"):h.bridge.verify_presentation(out['outbox_id'])
        with h.bridge.store._connection() as db:
            result['goals']=[dict(x) for x in db.execute('SELECT state,data_json FROM conversation_goals_v2')]
            result['presentations']=[json.loads(x[0]) for x in db.execute('SELECT data_json FROM conversation_presentations_v2 ORDER BY rowid')]
        result.update(question=case['question'],run=work,items=s.rows('SELECT * FROM action_items'),plans=s.rows('SELECT * FROM reminder_plans'),native_operations=s.rows('SELECT * FROM item_operations'))
        outputs=s.rows('SELECT o.* FROM outbox o JOIN am_outbox_events e ON e.outbox_id=o.id WHERE e.event_id=?',(row['id'],))
        result['outbox']=outputs
        result['independent_readbacks']=[{'verified':bool(api.verify_text(o['message_id'],am.query_readback_row(o)))} for o in outputs if o['state']=='sent']
        goaldata=[json.loads(x['data_json']) for x in result['goals']]
        result['checks']={'exact_item_count':len(result['items'])==case['expected_items'],'no_real_scheduled_plan':not result['plans'],
            'reply_readback':bool(result['independent_readbacks']) and all(x['verified'] for x in result['independent_readbacks'])}
        if case['id']=='FIX2-F01':
            result['checks']['distinct_matters_once']=sorted(x['description'] for x in result['items'])==sorted(['确认交期','确认交期变更原因'])
        if case.get('lost_result'):
            result['checks']['original_item_preserved']=result['scripted_native_precondition']['items_before'][0]['id'] in {x['id'] for x in result['items']}
            result['reconciliation_observed']=any(c.get('result',{}).get('reconciled_operation_id') for d in goaldata for c in d['calls'].values())
        result['business_completion']=[d['completion'] for d in goaldata]
    except Exception as exc:result.update(error=str(exc),error_type=type(exc).__name__,traceback=traceback.format_exc())
    finally:save_record(path,result,proxy,started)
