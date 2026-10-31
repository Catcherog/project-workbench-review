"""Post-measurement risk probes; never added to the frozen 48-case denominator."""
from pathlib import Path
from dataclasses import replace
import copy,hashlib,json,os,time,traceback
import pytest
from test_harness_host import harness,convo,ux,service,am_rig,base_rig,incoming,execute,call,project
from test_gateway import drain
from test_model_tasks import fixture_setup
from am_response.pipeline import ResponsePipeline
from am_response.gateway import GatewayProjection
from am_response.semantics import PROFILE
from model_proxy import OriginalCoordinatorProxy
TASK=Path(__file__).resolve().parents[1]
CASES=[('AUD-SAME-01','为需求75分别登记跟进：确认油脂交期；核对测试排期'),('AUD-COMPOUND-01','为需求75登记跟进：确认油脂交期；2030年3月2日09:30提醒我确认油脂交期'),('AUD-RESUME-01','继续剩下的事项，核对测试排期')]
PARAMS=[(c,m) for i,c in enumerate(CASES) for m in (('legacy','enforce') if i%2==0 else ('enforce','legacy'))]

@pytest.mark.parametrize('case,mode',PARAMS,ids=[c[0]+'-'+m for c,m in PARAMS])
def test_supplementary(harness,case,mode):
    assert os.environ.get('AM_R2_FIX1_L2')=='1'
    assert len(list((TASK/'evidence/full-model').glob('*.json')))==288
    manifest=json.loads((TASK/'input/supplementary-model-manifest.json').read_text())
    assert manifest['source_commit']==os.environ['AM_R2_EVAL_SHA']
    path=TASK/'evidence/supplementary-model'/(case[0]+'-'+mode+'.json');path.parent.mkdir(exist_ok=True)
    if path.exists():pytest.skip('immutable observed attempt')
    conv,h=harness;proxy=OriginalCoordinatorProxy('SYN-PAR-01')
    result={'case_id':case[0],'question':case[1],'mode':mode,'source_commit':manifest['source_commit'],'manifest_hash':hashlib.sha256((TASK/'input/supplementary-model-manifest.json').read_bytes()).hexdigest(),'transport_case':'SYN-PAR-01','real_feishu_delivery':False,'naturalness':'not_evaluated','not_in_primary_denominator':True,'turns':[]}
    started=time.monotonic()
    def invoke(text,**extra):
        t=time.monotonic();row=incoming(harness,text);ident=h.admit(row)
        run=h.run_once().__dict__ if isinstance(ident,str) and ident.startswith('run_') else None
        drain(conv[0][1])
        for out in h.s.rows("SELECT outbox_id FROM am_conversation_outputs WHERE state='awaiting_verification'"):h.bridge.verify_presentation(out['outbox_id'])
        result['turns'].append({'question':text,'event_id':row['id'],'run':run,'seconds':time.monotonic()-t,**extra})
    try:
        seed=copy.deepcopy(json.loads((TASK/'input/evaluation-manifest.json').read_text())['cases'][40]);seed.update(case_id=case[0],intent=case[1],evidence_or_receipt={'fixture':'audited compound obligations; synthetic only'})
        _,result['setup']=fixture_setup(harness,seed)
        original_config=replace(h.bridge.agent.config,goal_tracking=True)
        if case[0]=='AUD-RESUME-01':
            h.bridge.agent.config=replace(original_config,max_rounds=1)
            h.bridge.agent.response_pipeline=ResponsePipeline({'mode':'legacy'})
            execute(harness,'为需求75分别登记跟进：确认油脂交期；核对测试排期',[call('create_followup',{'project_id':project(conv),'description':'确认油脂交期'})])
            result['scripted_native_precondition']={'initial_goal':'two matters, only the first committed','items_before':h.s.rows('SELECT * FROM action_items'),'initial_step_used_real_qwen':False}
        h.bridge.agent.config=original_config
        h.bridge.agent.response_pipeline=ResponsePipeline({'mode':mode,'profile_version':PROFILE,'families':['query','analysis','followup','worknote','knowledge','document','approval','sending','schedule','report','control']},binding=h.bridge.response_binding,targets=lambda c:h.bridge._current(c)['project_catalog'],clock=h.s.clock)
        h.s.response_projection=GatewayProjection(h.s)
        def model(prompt,**kw):
            conv[1].prompts.append(prompt);return proxy.complete(prompt,**kw)
        conv[1].complete=model
        result['setup_seconds']=time.monotonic()-started;started=time.monotonic()
        invoke(case[1])
        if case[0]=='AUD-COMPOUND-01':
            with h.bridge.store._connection() as db:actions=[dict(x) for x in db.execute("SELECT * FROM conversation_actions WHERE status='draft' AND tool_name='schedule_reminder'")]
            allowed=[]
            for action in actions:
                args=json.loads(action['arguments_json'])
                from datetime import datetime
                from fs_agent.scheduler import TZ
                try:
                    at=datetime.fromisoformat(args.get('at',''))
                    if at.tzinfo is None:at=at.replace(tzinfo=TZ)
                    time_matches=at==datetime(2030,3,2,9,30,tzinfo=TZ)
                except (ValueError,TypeError):time_matches=False
                if (action['presented_version']==action['version'] and args.get('target')=='self' and args.get('frequency')=='once' and args.get('body')=='确认油脂交期' and time_matches):allowed.append(action)
            if len(allowed)==1:
                action=allowed[0];invoke('确认执行 '+action['id']+' v'+str(action['version']),synthetic_exact_preview_confirmation=True)
                invoke('继续剩下的事项')
            else:result['confirmation_not_given']='no unique current verified preview exactly matching frozen self/body/time/frequency'
        with h.bridge.store._connection() as db:
            result['goals']=[dict(x) for x in db.execute('SELECT state,data_json FROM conversation_goals_v2')]
            result['actions']=[dict(x) for x in db.execute('SELECT * FROM conversation_actions')]
            result['presentations']=[json.loads(x[0]) for x in db.execute('SELECT data_json FROM conversation_presentations_v2 ORDER BY rowid')]
        result['items']=h.s.rows('SELECT * FROM action_items');result['plans']=h.s.rows('SELECT * FROM reminder_plans')
        result['event_outbox']=[];result['readbacks']=[]
        for turn in result['turns']:
            for out in h.s.rows('SELECT o.* FROM outbox o JOIN am_outbox_events e ON e.outbox_id=o.id WHERE e.event_id=?',(turn['event_id'],)):
                result['event_outbox'].append(out)
                if out['state']=='sent':result['readbacks'].append({'event_id':turn['event_id'],'verified':bool(conv[0][3].verify_text(out['message_id'],conv[0][0].query_readback_row(out)))})
        result['status']='observed'
        expected_items=1 if case[0]=='AUD-COMPOUND-01' else 2
        result['bounded_checks']={'exact_item_count':len(result['items'])==expected_items,'no_extra_plan':len(result['plans'])<=(1 if case[0]=='AUD-COMPOUND-01' else 0),'all_saved_replies_verified':bool(result['readbacks']) and all(x['verified'] for x in result['readbacks'])}
        result['bounded_checks']['projects_match']=all(x['project_ref']==result['setup']['project_id'] for x in result['items'])
        matters=['确认油脂交期'] if case[0]=='AUD-COMPOUND-01' else ['确认油脂交期','核对测试排期']
        result['bounded_checks']['each_distinct_matter_once']=all(sum(matter in x['description'] for x in result['items'])==1 for matter in matters)
        if case[0]=='AUD-COMPOUND-01':result['bounded_checks']['one_confirmed_plan']=len(result['plans'])==1
        if case[0]=='AUD-RESUME-01':result['bounded_checks']['first_committed_item_preserved']=all(x['id'] in {y['id'] for y in result['items']} for x in result['scripted_native_precondition']['items_before'])
    except Exception as exc:result.update(status='error',error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
    finally:
        result.update(task_seconds=time.monotonic()-started,model_calls=proxy.records,provider_transport_calls=len(proxy.records))
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
        print(json.dumps({'case':case[0],'mode':mode,'status':result['status'],'bounded_checks':result.get('bounded_checks'),'error':result.get('error')},ensure_ascii=False),flush=True)
    if any(x.get('error') in ('STOP_UNKNOWN','MODEL_PAUSED') for x in proxy.records) or result.get('error') in ('EVALUATION_MODEL_RESULT_UNKNOWN','EVALUATION_SOURCE_CHANGED'):pytest.exit('Original model requires reconciliation',returncode=3)
