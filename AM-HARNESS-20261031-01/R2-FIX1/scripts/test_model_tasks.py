"""Frozen L2 full-loop runs, original Qwen, production tools, isolated SQLite/ports.

Run explicitly from this task. Never collected as ordinary production regression.
"""
from pathlib import Path
from dataclasses import replace
import os,json,time,hashlib,traceback
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from test_harness_host import harness,convo,ux,service,am_rig,base_rig,incoming,project,execute,call
from test_gateway import drain
from am_response.pipeline import ResponsePipeline
from am_response.gateway import GatewayProjection
from am_response.semantics import PROFILE
from model_proxy import OriginalCoordinatorProxy

TASK=Path(__file__).resolve().parents[1]
MANIFEST=json.loads((TASK/'input/evaluation-manifest.json').read_text())
PARAMS=[]
for repeat in range(1,4):
 for index,c in enumerate(MANIFEST['cases']):
  for mode in (('legacy','enforce') if (repeat+index)%2 else ('enforce','legacy')):PARAMS.append((repeat,c,mode))


def fixture_setup(harness,case):
    conv,h=harness;am,g,s,api,clock,port=conv[0];clock.now=datetime(2030,3,1,9,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    # Existing source adapter publishes these synthetic rows and native IDs.
    evidence=case['evidence_or_receipt'];progress=json.dumps(evidence,ensure_ascii=False)
    g.reminders.port.people=[{'id':'ou_engineer_a','name':'合成甲工'},{'id':'ou_engineer_b','name':'合成乙工'}]
    g.reminders.port.group_info['name']='合成群'
    port.values[1][5]='试样确认负责人：AR1合成甲工'
    port.values[2][5]='负责人：AR2合成乙工'
    if case['case_id']=='SYN-QRY-02':port.values[1][2]='预计2030.3.8交付；实际交付时间尚未核实。'
    if case['case_id']=='SYN-QRY-03':port.values[1][3]='syn-private-todo-1：合成样品照片待补'
    port.values[1][0]='需求75:合成青岚';port.values[2][0]='需求76:合成星榆'
    port.values[1][4]=progress;port.values[2][4]=progress
    port.values.append(['需求77:合成海棠','','','待确认','来源甲和来源乙范围不同，尚未核实。','AR1合成甲工',''])
    am.snapshots.refresh().result(3)
    p=project(conv);caseid=case['case_id'];state=case['starting_state'];text=case['intent']
    for before,after in [('合成青岚','需求75'),('合成星榆','需求76'),('合成海棠','需求77')]:text=text.replace(before,after)
    if caseid=='SYN-FUP-02':text=case['intent']
    setup={'project_id':p,'native_objects':{},'original_seed_intent':case['intent']}
    # Objects are created through their production stores; fixture-only initial
    # versions/states model the supplied seed, never a production database.
    if 'followup' in state or caseid.startswith('SYN-PAR') or state.get('completed_steps'):
        item=am.items.create(am.owner,'fixture-followup',project_ref=p,description='合成试样确认',requirements='',assignees=[am.owner],source={'project_title':'需求75'})
        f=state.get('followup',{});s.execute('UPDATE action_items SET version=?,state=?,paused=? WHERE id=?',(f.get('version',1),f.get('state','open'),int(f.get('paused',False)),item['id']))
        if caseid=='SYN-FUP-04':s.execute("UPDATE action_items SET latest_feedback=? WHERE id=?",('已提交合成资料；合成验收依据 syn-acceptance-1 已批准。',item['id']))
        setup['native_objects']['followup']=item['id']
        if f.get('id'):text=text.replace(f['id'],item['id'])
    # A request context provides original identity/project authorization to stores.
    origin=incoming(harness,'读取需求75')
    with h.bridge.request_context(origin) as ctx:
        if caseid in ('SYN-NOT-02','SYN-NOT-04'):
            for index in range(2 if caseid.endswith('02') else 1):
                note=h.bridge.store.create_task(ctx,project_id=p,title='准备样品照片'+str(index+1),details='合成内部笔记')
                setup['native_objects']['note'+str(index)]=note['id']
        if caseid.startswith('SYN-KNW') and caseid[-2:] in ('02','03','04'):
            row=h.bridge.knowledge.submit(ctx,kind='rule',content='外包装变更前先核对尺寸。',source={'uri':'synthetic://rule','observed_at':'2030-03-01T01:00:00+00:00'},scope='private')
            if caseid.endswith('04'):
                for _ in range(2):row=h.bridge.knowledge.submit(ctx,kind='rule',content='外包装变更前先核对尺寸。',source={'uri':'synthetic://rule','observed_at':'2030-03-01T01:00:00+00:00'},scope='private',logical_id=row['logical_id'],expected_version=row['version'])
                setup['knowledge_version_contract']={'candidate':3,'approved':3,'design_example_receipt':4,'reason':'original store approval retains current version'}
            setup['native_objects']['knowledge']=row['id']
            if caseid.endswith('04'):text='批准知识 '+row['id']+' v'+str(row['version'])
            if caseid.endswith('03'):text='不要采用知识 '+row['id']+' v'+str(row['version'])
        if caseid.startswith(('SYN-APR','SYN-OUT')) and caseid not in ('SYN-APR-02','SYN-OUT-02','SYN-OUT-04'):
            args={'target':'group','group_id':'oc_reminder','recipient_ids':['ou_engineer_a'],'project_id':p,'body':'请核对合成试样，日期2030年3月4日。'}
            tool=h.bridge.registry.resolve(ctx,'send_message',args)
            execute(harness,'准备发送合成通知',[call('send_message',args)])
            a=h.bridge.store.list_actions(ctx)[0]
            if caseid in ('SYN-APR-01','SYN-APR-04'):
                revised=dict(args,body=args['body']+'请以当前版本为准。')
                execute(harness,'修改当前合成通知预览',[call('revise_pending_action',{'action_id':a['id'],'expected_version':a['version'],'arguments':revised})])
                a=h.bridge.store.get_action(ctx,a['id'])
            setup['native_objects']['action']=a['id']
            if caseid in ('SYN-APR-01','SYN-OUT-01'):text='确认执行 '+a['id']+' v'+str(a['version'])
            if caseid=='SYN-APR-03':text='取消 '+a['id']
        if caseid.startswith('SYN-DOC') or caseid in ('SYN-OUT-02','SYN-OUT-04'):
            d=g.logic.create(origin,'charter');setup['native_objects']['draft']=d['id']
            if caseid in ('SYN-DOC-04','SYN-OUT-02','SYN-OUT-04'):
                s.execute("UPDATE logic_drafts SET state='ready',content='合成章程原稿',content_hash='synthetic-h',accepted_hash='synthetic-h' WHERE id=?",(d['id'],))
            s.execute('INSERT OR REPLACE INTO am_conversation_documents VALUES(?,?,?,?)',(d['id'],ctx.session_id,p,'fixture-origin'))
    # Seed schedule state through the original preview/confirmation path.
    if caseid in ('SYN-REM-01','SYN-REM-03','SYN-REM-04','SYN-ERR-01','SYN-CAN-02'):
        execute(harness,'每天09:30提醒我合成试样确认，持续到2030年3月5日',[call('schedule_reminder',{'target':'self','body':'合成试样确认','frequency':'daily','at':'09:30','until':'2030-03-05T23:59:00+08:00'})])
        with h.bridge.store._connection() as db:action=dict(db.execute('SELECT * FROM conversation_actions ORDER BY created_at DESC LIMIT 1').fetchone())
        execute(harness,'确认执行 '+action['id']+' v'+str(action['version']))
        plan=s.rows('SELECT * FROM reminder_plans')[0]
        setup['native_objects']['plan']=plan['id']
        if caseid=='SYN-REM-04':am.scheduler.control(am.owner,'fixture-pause',plan['id'],plan['version'],'pause')
        if caseid=='SYN-REM-03':
            clock.now=plan['next_at'];am.scheduler.scan()
            s.execute("UPDATE reminder_occurrences SET state='unknown',readback_state='pending'")
        if caseid=='SYN-REM-01':text='合成提醒计划 '+plan['id']+' 已按当前版本启用，说明实际时刻及目前是否发生提醒。'
    if caseid in ('SYN-CAN-01','SYN-CAN-04'):
        earlier=incoming(harness,'解释需求75的进展与证据')
        oldrun=h.admit(earlier);setup['native_objects']['old_run']=oldrun
        if caseid=='SYN-CAN-01':
            lease=h.tasks.claim('synthetic-held-worker',lease_seconds=120)
            text='停止当前任务'
            setup['original_run_claimed']=lease is not None
    if caseid=='SYN-CAN-03':
        execute(harness,'给需求75保存内部笔记',[call('save_work_note',{'project_id':p,'title':'合成准备样品照片'})])
        execute(harness,'准备发送合成通知',[call('send_message',{'target':'self','body':'合成待取消通知'})])
        a=h.bridge.store.list_actions(ctx)[0]
        text='取消 '+a['id'];setup['native_objects']['cancel_pending_action']=a['id']
    if caseid=='SYN-PAR-04':
        from am_outcome.goals import GoalJournal
        catalog=am.snapshots.get()['rows']
        with h.bridge.request_context(origin) as fresh_ctx:
            journal=GoalJournal(h.bridge.store,fresh_ctx,'fixture-multi-goal','为需求75和需求76分别登记跟进',catalog)
            completed=s.rows('SELECT * FROM action_items')[0]
            journal.record('create_followup',{'project_id':p,'description':completed['description']},{'item':completed},'local')
        text='继续需求76的试样跟进，负责人为合成乙工；保留需求75已建立事项。'
    if caseid=='SYN-QRY-04':
        earlier=incoming(harness,'需求75谁负责')
        execute(harness,'需求75谁负责');execute(harness,'需求76谁负责')
        h.admit(earlier);drain(g)
        for output in s.rows("SELECT outbox_id FROM am_conversation_outputs WHERE state='awaiting_verification'"):h.bridge.verify_presentation(output['outbox_id'])
        setup['delivered_focus_sequence']='75 then 76; older 75 finishes last'
    if caseid=='SYN-NOT-03':
        from contextlib import contextmanager
        original=h.tasks.transaction_guard
        @contextmanager
        def lost_commit(*args,**kwargs):
            with original(*args,**kwargs) as conn:
                yield conn
                raise RuntimeError('synthetic lost gateway commit')
        h.tasks.transaction_guard=lost_commit
    if caseid=='SYN-FUP-03':
        tool=h.bridge.registry._tools['change_followup'];original=tool.handler
        def cancel_before_commit(*args):
            h.admit(incoming(harness,'停止当前任务'))
            return original(*args)
        h.bridge.registry._tools['change_followup']=replace(tool,handler=cancel_before_commit)
    if caseid=='SYN-FUP-02':
        port.values.append(['需求78:合成海棠','','','待确认','另一个同名项目','AR2合成乙工','']);am.snapshots.refresh().result(3)
    if caseid=='SYN-ANA-03':
        # Actual original source-access guard will observe a changed epoch.
        current=h.bridge.agent.source_access_version
        h.bridge.agent.source_access_version=lambda:'revoked-synthetic'
    if caseid=='SYN-ERR-03':
        # Do not run an actual model request in an unresolved lane.
        s.execute("UPDATE am_harness_lane SET state='quarantined'")
    return text,setup


@pytest.mark.parametrize('repeat,case,mode',PARAMS,ids=[f"{r}-{c['case_id']}-{m}" for r,c,m in PARAMS])
def test_full_task(harness,repeat,case,mode):
    if os.environ.get('AM_R2_FIX1_L2')!='1':pytest.skip('explicit original-coordinator evaluation only')
    path=TASK/('evidence/fixture-preflight' if os.environ.get('AM_R2_FIX1_DRY')=='1' else 'evidence/full-model')/f"{repeat}-{case['case_id']}-{mode}.json"
    if path.exists():pytest.skip('immutable recorded attempt; no repeat')
    path.parent.mkdir(parents=True,exist_ok=True)
    conv,h=harness;result={'case_id':case['case_id'],'family':case['family'],'repeat':repeat,'mode':mode,
        'source_commit':os.environ.get('AM_R2_EVAL_SHA'),'layer':'L2_real_agent_original_qwen_synthetic_ports','real_feishu_delivery':False,'naturalness':'not_evaluated',
        'eligible_free_expression':case['eligible_free_expression'],'manifest_hash':hashlib.sha256((TASK/'input/evaluation-manifest.json').read_bytes()).hexdigest()}
    proxy=OriginalCoordinatorProxy(case['case_id']);start=time.monotonic()
    try:
        text,setup=fixture_setup(harness,case);result.update(question=text,setup=setup)
        result['setup_seconds']=time.monotonic()-start
        start=time.monotonic()
        setup_sent=len(conv[0][3].sent)
        h.bridge.agent.config=replace(h.bridge.agent.config,goal_tracking=True)
        h.bridge.agent.response_pipeline=ResponsePipeline({'mode':mode,'profile_version':PROFILE,'families':['query','analysis','followup','worknote','knowledge','document','approval','sending','schedule','report','control']},binding=h.bridge.response_binding,targets=lambda c:h.bridge._current(c)['project_catalog'],clock=h.s.clock)
        h.s.response_projection=GatewayProjection(h.s)
        def model(prompt,**kw):
            conv[1].prompts.append(prompt)
            if os.environ.get('AM_R2_FIX1_DRY')=='1':
                from types import SimpleNamespace
                return SimpleNamespace(text=json.dumps({'type':'answer','text':'合成预检：缺少必要信息，尚未执行其他动作。'}),model='fixture-only',elapsed=0)
            return proxy.complete(prompt,**kw)
        conv[1].complete=model
        fault_events=[]
        if case['case_id']=='SYN-QRY-03':
            h.config=replace(h.config,fastpath_enabled=False);h.bridge.agent.fastpath=None
            original_lifecycle=h.bridge.agent.lifecycle
            def cancel_prepared(ctx,phase,args):
                original_lifecycle(ctx,phase,args)
                if phase=='before_finish' and not fault_events:
                    stopped=incoming(harness,'停止当前任务');fault_events.append(stopped['id']);h.admit(stopped)
                    original_lifecycle(ctx,phase,args)
            cancel_prepared.strict_bound=True
            h.bridge.agent.lifecycle=cancel_prepared
            result['fault_injection']='after model/prepared result, before final save; real original cancellation'
        row=incoming(harness,text,thread='synthetic-ambiguous' if case['case_id']=='SYN-CAN-02' else None);result['input_received_epoch']=time.time();result['event_id']=row['id'];result['run_id']=h.admit(row)
        if isinstance(result['run_id'],str) and result['run_id'].startswith('run_'):
            run=h.run_once();result['run_result']=run.__dict__
        drain(conv[0][1])
        for out in h.s.rows("SELECT outbox_id FROM am_conversation_outputs WHERE state='awaiting_verification'"):
            h.bridge.verify_presentation(out['outbox_id'])
        result['event_ids']=[row['id'],*fault_events]
        result['turns']=[{'question':text,'event_id':row['id'],'run_result':result.get('run_result')}]
        if case['case_id']=='SYN-FUP-04':
            with h.bridge.store._connection() as db:
                choices=[dict(r) for r in db.execute("SELECT * FROM conversation_actions WHERE status='draft' AND tool_name='close_followup'")]
            allowed=[a for a in choices if json.loads(a['arguments_json']).get('item_id')==setup['native_objects']['followup'] and json.loads(a['arguments_json']).get('version')==5 and a['presented_version']==a['version']]
            if len(allowed)==1:
                a=allowed[0];confirmation='确认执行 '+a['id']+' v'+str(a['version'])
                follow=incoming(harness,confirmation);ident=h.admit(follow)
                follow_result=h.run_once().__dict__ if isinstance(ident,str) and ident.startswith('run_') else None
                drain(conv[0][1])
                for output in h.s.rows("SELECT outbox_id FROM am_conversation_outputs WHERE state='awaiting_verification'"):h.bridge.verify_presentation(output['outbox_id'])
                result['event_ids'].append(follow['id']);result['turns'].append({'question':confirmation,'event_id':follow['id'],'run_result':follow_result,'synthetic_user_confirmation':True})
            else:result['continuation_blocked']='no unique current verified close preview for the frozen object/version'
        if case['case_id']=='SYN-KNW-04':
            follow=incoming(harness,'刚才批准的规则是什么？');ident=h.admit(follow)
            follow_result=h.run_once().__dict__ if isinstance(ident,str) and ident.startswith('run_') else None
            drain(conv[0][1])
            for output in h.s.rows("SELECT outbox_id FROM am_conversation_outputs WHERE state='awaiting_verification'"):h.bridge.verify_presentation(output['outbox_id'])
            result['event_ids'].append(follow['id']);result['turns'].append({'question':'刚才批准的规则是什么？','event_id':follow['id'],'run_result':follow_result})
        with h.bridge.store._connection() as db:
            result['notes']=[dict(r) for r in db.execute('SELECT * FROM conversation_tasks')]
            result['actions']=[dict(r) for r in db.execute('SELECT * FROM conversation_actions')]
            result['presentations']=[json.loads(r[0]) for r in db.execute('SELECT data_json FROM conversation_presentations_v2')]
            result['goals']=[dict(r) for r in db.execute('SELECT state,data_json FROM conversation_goals_v2')]
        result['selected_text']=conv[0][3].sent[-1]['body'] if len(conv[0][3].sent)>setup_sent else None
        result['delivery_rows']=h.s.rows('SELECT state,body FROM outbox')
        result['items']=h.s.rows('SELECT * FROM action_items')
        result['knowledge']=[dict(r) for r in h.bridge.knowledge._db.execute('SELECT id,logical_id,version,status,scope,project_id,content FROM knowledge_records')]
        result['documents']=h.s.rows('SELECT id,revision,state,document_type,content_hash,accepted_hash,target FROM logic_drafts')
        result['send_records']=h.s.rows('SELECT action_id,state,message_id,receipt FROM am_conversation_sends')
        result['occurrences']=h.s.rows('SELECT id,plan_id,state,readback_state FROM reminder_occurrences')
        result['event_outbox']=[dict(r) for eid in result['event_ids'] for r in h.s.rows('SELECT e.event_id,o.state,o.message_id,o.body FROM am_outbox_events e JOIN outbox o ON o.id=e.outbox_id WHERE e.event_id=?',(eid,))]
        result['reply_verification']=h.s.rows('SELECT event_id,state,verified_at FROM am_conversation_outputs')
        result['independent_readbacks']=[]
        for eid in result['event_ids']:
            for out in h.s.rows('SELECT o.* FROM outbox o JOIN am_outbox_events e ON e.outbox_id=o.id WHERE e.event_id=?',(eid,)):
                if out['state']=='sent':
                    result['independent_readbacks'].append({'event_id':eid,'body_sha256':hashlib.sha256(out['body'].encode()).hexdigest(),'verified':bool(conv[0][3].verify_text(out['message_id'],h.service.query_readback_row(out))) if hasattr(h,'service') else bool(conv[0][3].verify_text(out['message_id'],conv[0][0].query_readback_row(out))),'layer':'synthetic_platform_port'})
        if result['event_outbox']:result['selected_text']=result['event_outbox'][-1]['body']
        else:result['selected_text']=None
        result['plans']=h.s.rows('SELECT id,state,version FROM reminder_plans')
        result['inbox_state']=h.s.rows('SELECT state,error FROM am_inbox ORDER BY rowid DESC LIMIT 1')
        result['tool_calls']=[p['outcome']['work_units'] for p in result['presentations']]
        result['status']='observed'
    except Exception as exc:
        result.update(status='guard_suppressed' if case['case_id']=='SYN-ANA-03' and str(exc)=='SOURCE_ACCESS_CHANGED' else 'error',error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
    finally:
        result.update(total_seconds=time.monotonic()-start,model_calls=proxy.records,model_calls_total=len(proxy.records),task_terminal_epoch=time.time(),fixture_clock=h.s.clock())
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
        print(json.dumps({'case':case['case_id'],'repeat':repeat,'mode':mode,'status':result['status'],'calls':len(proxy.records),'seconds':round(result['total_seconds'],2),'error':result.get('error')},ensure_ascii=False),flush=True)

    if os.environ.get("AM_R2_FIX1_DRY")=="1":assert result["status"]!="error",result.get("error")

    if any(r.get("error") in ("STOP_UNKNOWN","MODEL_PAUSED") for r in proxy.records) or result.get("error") in ("EVALUATION_MODEL_RESULT_UNKNOWN","EVALUATION_SOURCE_CHANGED"):pytest.exit("Original model requires reconciliation; no further evaluation queued",returncode=3)
