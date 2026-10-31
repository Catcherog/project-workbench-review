"""Original AM service, SQLite, permissions and business journals; synthetic I/O."""
import json
import threading
import time
import pytest
from test_conversation_integration import convo, ux, service, am_rig, base_rig, call, answer, project
from test_gateway import event, drain
from am_harness_host import HarnessHost
from am_harness.controls import parse_control
from am_harness.store import Scope

SETTINGS = dict(enabled=True, fastpath_enabled=True, control_enabled=True, durable_queue_enabled=True)


@pytest.fixture
def harness(convo):
    am = convo[0][0]
    am.harness = HarnessHost(am, SETTINGS)
    yield convo, am.harness
    am.harness.close()


def incoming(harness, text, *, actor='ou_a', chat='oc_dm', thread=None):
    convo, h = harness; am,g,s,api,clock,port = convo[0]
    n = len(s.rows('SELECT id FROM am_inbox'))+500
    payload = event(text, number=n, user=actor, chat=chat)
    payload['event']['message']['create_time'] = str(int(clock()*1000))
    if thread:payload['event']['message']['thread_id'] = thread
    assert am.ingest(payload) == (True,True)
    return s.rows('SELECT * FROM am_inbox ORDER BY rowid DESC LIMIT 1')[0]


def execute(harness, text, outputs=()):
    convo,h = harness; convo[1].outputs.extend(outputs)
    row = incoming(harness,text); result = h.admit(row)
    if isinstance(result,str) and result.startswith('run_'):
        work = h.run_once()
        assert work.status == 'completed', (work, h.s.rows('SELECT state,error FROM am_harness_runs'))
    drain(convo[0][1])
    for out in h.s.rows("SELECT outbox_id FROM am_conversation_outputs WHERE state='awaiting_verification'"):
        h.bridge.verify_presentation(out['outbox_id'])
    return row, result


@pytest.mark.parametrize('question', ['需求75的项目进展','需求75关键日期','需求75有哪些待办','需求75谁负责'])
def test_fast_fields_and_event_dedupe(harness,question):
    convo,h = harness; row,out = execute(harness,question)
    assert not convo[1].prompts
    assert h.admit(row) == out
    assert len(h.s.rows('SELECT * FROM outbox')) == 1
    assert not h.s.rows('SELECT * FROM am_harness_runs')


def test_complex_run_original_outbox_strict_origin_and_receipt(harness):
    convo,h = harness
    row,ident = execute(harness,'请解释测试计划与完成证据的区别',[answer('计划日期只表示安排，完成情况需要结果证据。')])
    run = h.tasks.get(Scope(*h.bridge._identity(row)),ident)
    assert run.state == 'succeeded'
    binding = h.s.rows('SELECT * FROM am_harness_outbox')[0]
    assert binding['state'] == 'sent' and binding['verified'] == 1
    assert h.s.rows('SELECT * FROM am_conversation_outputs')[0]['event_id'] == row['id']
    assert h.hooks.strict_bound is True and h.runtime.store.path == h.effects.store.path
    assert any(e['event']=='first_useful' for e in h.trace.records)


def test_cancel_during_model_and_independent_read(harness):
    convo,h = harness; entered=threading.Event(); release=threading.Event()
    original=convo[1].complete
    def slow(*args,**kw):
        entered.set(); assert release.wait(3)
        return original(*args,**kw)
    convo[1].complete=slow; convo[1].outputs.append(answer('不应发布的旧回复'))
    row=incoming(harness,'解释项目管理方法');ident=h.admit(row)
    result=[]; worker=threading.Thread(target=lambda:result.append(h.run_once()));worker.start()
    assert entered.wait(2)
    try:
        read=incoming(harness,'需求75谁负责');h.admit(read)
        assert len(convo[1].prompts)==0  # blocked model has not returned
        stop=incoming(harness,'停止当前任务');h.admit(stop)
    finally:
        release.set();worker.join(3)
    assert not worker.is_alive()
    run=h.tasks.get(Scope(*h.bridge._identity(row)),ident)
    assert run.state=='cancelled' and h.tasks.lane_status()['state']=='idle'
    assert not h.s.rows('SELECT * FROM am_harness_outbox')
    assert all('不应发布' not in o['body'] for o in h.s.rows('SELECT * FROM outbox'))


def test_revise_keeps_real_control_source_and_new_engine_id(harness):
    convo,h = harness; convo[1].outputs.append(answer('这是更正要求后的回答。'))
    row=incoming(harness,'解释第一种方案');ident=h.admit(row)
    correction=incoming(harness,'更正当前任务：解释另一种方案');h.admit(correction)
    result=h.run_once();assert result.status=='completed',result
    saved=h.s.rows('SELECT * FROM am_conversation_outputs')[0]
    assert saved['event_id']==correction['id']
    assert json.loads(saved['reply'])['event_id']=='harness:'+ident+':v2'
    assert h.s.rows('SELECT body FROM am_inbox WHERE id=?',(row['id'],))[0]['body']==row['body']
    drain(convo[0][1]);assert h.s.rows('SELECT verified FROM am_harness_outbox')[0]['verified']==1


def test_cancel_pending_output_and_history(harness):
    convo,h=harness;convo[1].outputs.append(answer('这个未发送回复不能进入后续历史。'))
    row=incoming(harness,'解释一个通用方法');ident=h.admit(row);assert h.run_once().status=='completed'
    stop=incoming(harness,'取消任务 '+ident);h.admit(stop)
    assert h.s.rows('SELECT state FROM am_harness_outbox')[0]['state']=='suppressed'
    with h.bridge.request_context(dict(row)) as ctx:
        assert all('未发送回复' not in str(m) for m in h.bridge.store.history(ctx))
    drain(convo[0][1]);assert not any('未发送回复' in o['body'] for o in convo[0][3].sent)


def test_unbound_engine_cannot_execute(harness):
    _,h=harness;row=incoming(harness,'普通问题')
    with h.bridge.request_context(dict(row)) as ctx:
        with pytest.raises(Exception,match='HARNESS_UNBOUND_RUN'):
            h.bridge.agent.handle(ctx,'unbound','普通问题')


def test_revoked_identity_fails_admission(harness):
    convo,h=harness;row=incoming(harness,'需求75谁负责')
    convo[0][5].authorize_private_user=lambda actor: (_ for _ in ()).throw(RuntimeError('QUERY_IDENTITY_REVOKED'))
    h.service.query_identity.seconds=0
    with pytest.raises(Exception,match='QUERY_IDENTITY_REVOKED'):h.admit(row)
    assert not h.s.rows('SELECT * FROM outbox')


def test_send_original_approval_and_actual_reservations(harness):
    convo,h=harness
    args={'target':'self','body':'合成 Harness 本人发送测试'}
    execute(harness,'准备给我发一条测试消息',[call('send_message',args)])
    assert not h.s.rows('SELECT * FROM am_harness_reservations')
    execute(harness,'确认第1项')
    saved=h.s.rows('SELECT kind,state FROM am_harness_reservations')
    assert {r['kind'] for r in saved}=={'action','send'}
    assert all(r['state']=='succeeded' for r in saved)
    assert len(h.s.rows('SELECT * FROM am_conversation_sends'))==1


def test_noop_control_redelivery_does_not_stop_new_run(harness):
    _,h=harness;stop=incoming(harness,'停止当前任务');h.admit(stop)
    row=incoming(harness,'解释通用工作流程');ident=h.admit(row);h.admit(stop)
    assert h.tasks.get(Scope(*h.bridge._identity(row)),ident).state=='queued'


def test_payload_tamper_rejected_in_dispatch_transaction(harness):
    convo,h=harness;convo[1].outputs.append(answer('原始合成回复'))
    row=incoming(harness,'说明一个普通概念');h.admit(row);assert h.run_once().status=='completed'
    h.s.execute("UPDATE outbox SET body='modified' WHERE id IN (SELECT outbox_id FROM am_harness_outbox)")
    drain(convo[0][1]);assert h.s.rows('SELECT state FROM am_harness_outbox')[0]['state']=='suppressed'
    assert not convo[0][3].sent


def test_group_thread_binding(harness):
    convo,h=harness;am,g,s,api,clock,port=convo[0]
    payload=event('请说明计划与验收的关系',number=900,chat='oc_reminder',group=True,mentioned=True)
    payload['event']['message']['thread_id']='thread-a';payload['event']['message']['create_time']=str(int(clock()*1000))
    assert am.ingest(payload)==(True,True)
    row=s.rows('SELECT * FROM am_inbox ORDER BY rowid DESC LIMIT 1')[0]
    convo[1].outputs.append(answer('计划节点不能证明已验收。'))
    h.admit(row);result=h.run_once();assert result.status=='completed',result
    s.execute("UPDATE am_source_meta SET metadata=? WHERE id=?",(json.dumps({'thread':'thread-b'}),row['id']))
    drain(g);assert s.rows('SELECT state FROM am_harness_outbox')[0]['state']=='suppressed'


def test_original_pump_handles_control_while_worker_is_busy(harness):
    convo,h=harness;am,g,s,api,clock,port=convo[0]
    entered=threading.Event();release=threading.Event();wake=threading.Event()
    am.enable_background(wake.set)
    original=convo[1].complete
    def slow(*a,**kw):
        entered.set();assert release.wait(5)
        return original(*a,**kw)
    convo[1].complete=slow;convo[1].outputs.append(answer('旧回复必须被抑制'))
    row=incoming(harness,'请解释一个流程')
    limit=time.monotonic()+3
    while not entered.is_set() and time.monotonic()<limit:
        am.pump();wake.wait(.01);wake.clear()
    assert entered.is_set()
    try:
        stop=incoming(harness,'停止当前任务')
        limit=time.monotonic()+3
        while time.monotonic()<limit:
            am.pump()
            if s.rows('SELECT state FROM am_inbox WHERE id=?',(stop['id'],))[0]['state']=='done':break
            wake.wait(.01);wake.clear()
        assert s.rows('SELECT state FROM am_harness_runs')[0]['state']=='cancelled'
    finally:
        release.set()
        h.close()
    assert not s.rows('SELECT * FROM am_harness_outbox')


def test_unknown_send_retains_one_original_action_and_no_retry(harness):
    from fs_agent.feishu import SendUnknown
    convo,h=harness;port=convo[0][1].reminders.port
    args={'target':'group','group_id':'oc_reminder','recipient_ids':['ou_engineer_a'],'body':'Harness合成发送'}
    execute(harness,'准备发给工程师甲这条消息',[call('send_message',args)])
    port.error=SendUnknown('synthetic lost receipt')
    execute(harness,'确认第1项')
    assert len(port.sent)==1, h.s.rows('SELECT body FROM outbox')
    assert all(r['state']=='unknown' for r in h.s.rows('SELECT state FROM am_harness_reservations'))
    execute(harness,'按这个发')
    assert len(port.sent)==1


def test_cancel_before_actual_send_reservation_prevents_send(harness):
    convo,h=harness;args={'target':'self','body':'不应发出的合成正文'}
    execute(harness,'准备给我发送测试文字',[call('send_message',args)])
    original=h.bridge.business.target;once=[]
    def target(ctx,args,event):
        result=original(ctx,args,event)
        if not once:
            once.append(True)
            stop=incoming(harness,'停止当前任务');h.admit(stop)
        return result
    h.bridge.business.target=target
    row=incoming(harness,'确认第1项');h.admit(row);result=h.run_once()
    assert result.status=='stale'
    assert not h.s.rows('SELECT * FROM am_conversation_sends')
    assert not h.s.rows("SELECT * FROM am_harness_reservations WHERE kind='send'")


def test_cancel_after_send_preserves_verified_receipt(harness):
    convo,h=harness;args={'target':'self','body':'合成已提交动作'}
    execute(harness,'准备给我发送测试文字',[call('send_message',args)])
    api=convo[0][3];original=api.send
    def sent(row,guard):
        mid=original(row,guard)
        stop=incoming(harness,'停止当前任务');h.admit(stop)
        return mid
    api.send=sent
    row=incoming(harness,'确认第1项');ident=h.admit(row);result=h.run_once()
    assert result.status=='stale'
    assert h.s.rows('SELECT state FROM am_conversation_sends')[0]['state']=='verified'
    assert all(r['state']=='succeeded' for r in h.s.rows('SELECT state FROM am_harness_reservations'))
    assert h.tasks.get(Scope(*h.bridge._identity(row)),ident).state=='cancelled'


def test_reminder_activation_reservation_keeps_original_approval(harness):
    from datetime import datetime,timedelta
    from zoneinfo import ZoneInfo
    convo,h=harness;at=datetime.fromtimestamp(convo[0][4](),ZoneInfo('Asia/Shanghai'))+timedelta(days=1)
    args={'target':'self','body':'合成待办检查','frequency':'once','at':at.isoformat()}
    execute(harness,'请在'+at.isoformat()+'提醒我检查',[call('schedule_reminder',args)])
    execute(harness,'确认第1项')
    assert h.s.rows("SELECT state FROM am_harness_reservations WHERE kind='schedule'")[0]['state']=='succeeded'
    plan=h.s.rows('SELECT * FROM reminder_plans')[0]
    assert plan['approval_id'] and plan['state']=='active'
    assert not h.s.rows('SELECT * FROM reminder_occurrences')


def test_failed_receipt_readback_reconciles_without_resending(harness):
    convo,h=harness;api=convo[0][3];api.verify_allowed=False
    row,ident=execute(harness,'说明计划和完成的区别',[answer('计划不等于完成。')])
    out=h.s.rows('SELECT * FROM am_harness_outbox')[0]
    assert out['verified']==0 and out['state']=='needs_reconciliation'
    count=len(api.sent);api.verify_allowed=True
    assert h.reconcile_receipt(out['outbox_id'])
    assert len(api.sent)==count and h.s.rows('SELECT verified FROM am_harness_outbox')[0]['verified']==1


def test_wrong_actor_control_cannot_cancel_owner_run(harness):
    convo,h=harness;row=incoming(harness,'解释一个工作流程');ident=h.admit(row)
    scope=Scope(*h.bridge._identity(row))
    outsider=incoming(harness,'取消任务 '+ident,actor='ou_b',chat='oc_other')
    with pytest.raises(Exception):h.admit(outsider)
    assert h.tasks.get(scope,ident).state=='queued'


def test_admission_restart_does_not_replay_committed_event(harness):
    convo,h=harness;row=incoming(harness,'说明工作流程');ident=h.admit(row)
    h.s.execute("UPDATE am_inbox SET state='harness_admitting' WHERE id=?",(row['id'],))
    # The durable submit dedupe is the authority after a crash in the gap
    # between submit commit and inbox bookkeeping.
    assert h.admit(row)==ident
    assert len(h.s.rows('SELECT * FROM am_harness_runs'))==1


@pytest.mark.parametrize('code,state',[('MODEL_BUSY','failed'),('STOP_UNKNOWN','unknown')])
def test_worker_failure_has_one_data_free_notice_without_retry(harness,code,state):
    from fs_agent.config import BoundaryError
    convo,h=harness
    def refused(*a,**kw):raise BoundaryError(code)
    convo[1].complete=refused
    row=incoming(harness,'请解释合成问题');ident=h.admit(row)
    result=h.run_once();assert result.status==state
    saved=h.s.rows('SELECT * FROM am_harness_runs WHERE id=?',(ident,))[0]
    assert h.failure_notice(saved)
    notices=h.s.rows("SELECT o.body FROM outbox o JOIN am_notifications n ON n.outbox_id=o.id WHERE n.kind='harness_error'")
    assert len(notices)==1
    assert '请解释合成问题' not in notices[0]['body'] and '任务' in notices[0]['body']
    assert not h.s.rows('SELECT * FROM am_harness_outbox')
    assert h.tasks.lane_status()['state']==('quarantined' if state=='unknown' else 'idle')
    if state=='unknown':assert h.s.meta('provider_pause')=='STOP_UNKNOWN'


def test_control_admission_has_capacity_when_normal_inbox_is_full(harness):
    _,h=harness
    for i in range(32):incoming(harness,'合成查询'+str(i))
    stop=incoming(harness,'停止当前任务')
    assert parse_control(stop['body']).operation=='cancel'
    assert len(h.s.rows("SELECT * FROM am_inbox WHERE state='received'"))==33


@pytest.mark.parametrize('change',['source_version','access_version'])
def test_fast_answer_provenance_expires_but_original_user_text_remains(harness,tmp_path,change):
    from types import SimpleNamespace
    from test_conversation_fix1 import info_fixture
    convo,h=harness;info=None
    if change=='access_version':
        info,_,_=info_fixture(tmp_path)
        h.service.information=SimpleNamespace(store=info,query=lambda row,p:{'version':'v','facts':[],'coverage':{}})
    try:
        original,out=execute(harness,'需求75谁负责')
        prior=h.s.rows('SELECT * FROM am_harness_context_sources WHERE event_id=?',(original['id'],))
        assert prior and json.loads(prior[0]['dependencies'])
        old_body=convo[0][3].sent[-1]['body'].splitlines()[0]
        if change=='source_version':
            snap=h.service.snapshots.get();snap['version']='synthetic-new-source-version'
            with h.service.snapshots.lock:
                h.service.snapshots.versions[snap['version']]=snap;h.service.snapshots.latest=snap['version']
        else:info.mark_source_error('s','revoked',True)
        execute(harness,'请解释一个一般概念',[answer('这是合成的通用回答。')])
        prompt=convo[1].prompts[-1]
        assert '需求75谁负责' in prompt
        assert old_body not in prompt
    finally:
        if info is not None:h.service.information=None;info.close()


def test_fast_replay_cannot_renew_source_version_or_expiry(harness):
    _,h=harness;row,out=execute(harness,'需求75谁负责')
    before=h.s.rows('SELECT * FROM am_harness_context_sources WHERE event_id=?',(row['id'],))[0]
    snap=h.service.snapshots.get();snap['version']='changed-after-publication';snap['observed_at']+=1
    with h.service.snapshots.lock:
        h.service.snapshots.versions[snap['version']]=snap;h.service.snapshots.latest=snap['version']
    assert h.admit(row)==out
    assert h.s.rows('SELECT * FROM am_harness_context_sources WHERE event_id=?',(row['id'],))[0]==before


@pytest.mark.parametrize('phase',['before_dispatch','during_model','next_history'])
def test_parallel_source_revocation_contract_is_preserved(harness,tmp_path,phase):
    from types import SimpleNamespace
    from test_conversation_fix1 import info_fixture
    convo,h=harness;info,_,_=info_fixture(tmp_path)
    h.service.information=SimpleNamespace(store=info,query=lambda row,p:{'version':'v','facts':[],'coverage':{}})
    try:
        text='合成来源限定信息'
        convo[1].outputs.append(answer(text))
        row=incoming(harness,'解释一个通用概念');ident=h.admit(row)
        if phase=='during_model':
            original=convo[1].complete
            def revoke(*a,**kw):
                result=original(*a,**kw);info.mark_source_error('s','revoked',True);return result
            convo[1].complete=revoke
        result=h.run_once()
        if phase=='during_model':
            assert result.status=='failed' and result.error=='SOURCE_ACCESS_CHANGED'
            assert h.tasks.lane_status()['state']=='idle'
            assert not h.s.rows('SELECT * FROM am_harness_outbox')
        else:
            assert result.status=='completed',result
            if phase=='next_history':drain(convo[0][1])
            info.mark_source_error('s','revoked',True)
            if phase=='before_dispatch':
                drain(convo[0][1]);assert not convo[0][3].sent
            else:
                with h.bridge.request_context(dict(row)) as ctx:
                    history=h.bridge.store.history(ctx)
                    assert any(m['role']=='user' for m in history)
                    assert all(text not in m['content'] for m in history)
    finally:
        h.service.information=None;info.close()


@pytest.mark.parametrize('cancel_before', [False,True])
def test_native_document_actual_journal_reservation(harness,cancel_before):
    from contextlib import ExitStack
    from test_document_standards import fixture_native,FakeCloud,profile_and_slots
    from fs_agent.document_native import NativePublisher
    from am_harness.reservation import action_context
    convo,h=harness
    execute(harness,'准备给我发送测试文字',[call('send_message',{'target':'self','body':'合成预览授权记录'})])
    row=incoming(harness,'确认第1项');ident=h.admit(row);lease=h.tasks.claim('synthetic-doc-worker')
    with h.context(lease.run) as ctx,h.hooks.bind(lease.fence):
        action=h.bridge.store.list_actions(ctx)[0]
        h.bridge.store.approve_action(ctx,action['id'],expected_version=action['version'],digest=action['digest'])
        h.bridge.store.begin_execution(ctx,action['id'],expected_version=action['version'])
        action=h.bridge.store.get_action(ctx,action['id'])
        native=fixture_native();cloud=FakeCloud(native);_,slots=profile_and_slots()
        publisher=NativePublisher(h.s,cloud,folder='synthetic',host='example.com')
        draft={'id':'synthetic-draft','revision':1,'content_hash':'hash1','accepted_hash':'hash1','expires':row['expires']}
        document={'fields':[{'field_id':s['field_id'],'text':'synthetic '+str(i)} for i,s in enumerate(slots)],'issues':[],'template_hash':'templatehash'}
        with action_context(h,ctx,action):
            if cancel_before:
                h.tasks.cancel(lease.run.scope,'synthetic-stop',ident)
                with pytest.raises(Exception,match='FENCE|CANCELLED'):
                    publisher.save(draft,document,native,slots)
                assert not cloud.writes and not h.s.rows('SELECT * FROM amdoc_native_writes')
            else:
                result=publisher.save(draft,document,native,slots)
                assert result['state']=='verified'
                assert h.s.rows("SELECT kind FROM am_harness_reservations WHERE kind='native_document'")
                assert publisher.save(draft,document,native,slots)['receipt']==result['receipt']
                assert len(cloud.writes)==2
    h.tasks.finish(lease,state='failed',error='SYNTHETIC_TEST_FINISHED')
