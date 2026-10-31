"""R1-FIX1 boundaries on the current R2 host. Synthetic I/O only."""
from contextlib import contextmanager
import json
import threading
import pytest
from test_harness_host import harness, convo, ux, service, am_rig, base_rig, execute, incoming, call, answer, project, SETTINGS
from am_harness_host import HarnessHost
from am_harness.context import ContextError
from am_harness.store import Scope


def stop(rig, command='停止当前任务'):
    _, host = rig
    host.admit(incoming(rig, command))


def run(rig, text, outputs):
    conv, host = rig
    conv[1].outputs.extend(outputs)
    row = incoming(rig, text)
    ident = host.admit(row)
    return row, ident, host.run_once()


@pytest.mark.parametrize('mode', ['cancel','revise'])
@pytest.mark.parametrize('tool', ['create_followup','save_work_note','propose_knowledge','submit_project_update'])
def test_local_create_stops_at_actual_store_boundary(harness, monkeypatch, tool, mode):
    conv,h = harness
    p = project(conv)
    specs = {
        'create_followup': (h.service.items, 'create', {'project_id':p,'description':'合成待核记录'}, lambda: h.s.rows('SELECT * FROM action_items')),
        'save_work_note': (h.bridge.store.original, 'create_task', {'project_id':p,'title':'合成待核记录'}, lambda: _notes(harness)),
        'propose_knowledge': (h.bridge.knowledge, 'submit', {'kind':'rule','content':'合成待核规则'}, lambda: list(h.bridge.knowledge._db.execute('SELECT * FROM knowledge_records'))),
        'submit_project_update': (h.service.updates, 'collect', {'project_id':p,'content':'合成待核记录'}, lambda: h.s.rows('SELECT * FROM progress_collections')),
    }
    target,method,args,read = specs[tool]
    original=getattr(target,method)
    def interrupted(*a,**kw):
        stop(harness, '停止当前任务' if mode=='cancel' else '更正当前任务：仅解释待核含义')
        return original(*a,**kw)
    monkeypatch.setattr(target,method,interrupted)
    before=read()
    _,ident,result=run(harness,'登记跟进与项目反馈：合成待核记录和合成待核规则',[call(tool,args)])
    assert read()==before
    state=h.s.rows('SELECT state,revision FROM am_harness_runs WHERE id=?',(ident,))[0]
    assert state['state']==('cancelled' if mode=='cancel' else 'queued')
    assert result.status=='stale'


def _notes(rig):
    _,h=rig
    with h.bridge.store.original._connection() as c:
        return [dict(x) for x in c.execute('SELECT * FROM conversation_tasks')]


@pytest.mark.parametrize('operation', ['processing','pause','resume','cancel'])
def test_followup_changes_cancel_before_commit(harness,monkeypatch,operation):
    conv,h=harness
    execute(harness,'登记合成跟进',[call('create_followup',{'description':'合成记录'})])
    item=h.s.rows('SELECT * FROM action_items')[0]
    before=h.service.items.get(item['id']);original=h.service.items.change
    def interrupted(*a,**kw):
        stop(harness);return original(*a,**kw)
    monkeypatch.setattr(h.service.items,'change',interrupted)
    run(harness,'修改合成跟进',[call('change_followup',{'item_id':item['id'],'version':item['version'],'operation':operation})])
    assert h.service.items.get(item['id'])==before


def test_feedback_and_reminder_control_cancel_before_commit(harness,monkeypatch):
    conv,h=harness
    execute(harness,'登记合成跟进',[call('create_followup',{'description':'合成记录'})])
    item=h.s.rows('SELECT * FROM action_items')[0]
    original=h.service.items.feedback
    def interrupted(*a,**kw):stop(harness);return original(*a,**kw)
    monkeypatch.setattr(h.service.items,'feedback',interrupted)
    run(harness,'合成反馈原话',[call('submit_followup_feedback',{'item_id':item['id'],'version':1,'kind':'processing','content':'合成反馈原话'})])
    assert not h.s.rows('SELECT * FROM item_feedback')
    # Original scheduler fixture, no actual send or approval bypass.
    from datetime import datetime,timezone
    at=datetime.fromtimestamp(h.s.clock()+3600,timezone.utc).isoformat()
    execute(harness,'请准备在17:00提醒我',[call('schedule_reminder',{'target':'self','body':'合成提醒','frequency':'once','at':at})])
    execute(harness,'确认第1项')
    plan=h.s.rows('SELECT * FROM reminder_plans')[0]
    original_control=h.service.scheduler.control
    def stop_control(*a,**kw):stop(harness);return original_control(*a,**kw)
    monkeypatch.setattr(h.service.scheduler,'control',stop_control)
    run(harness,'暂停合成计划',[call('control_reminder',{'plan_id':plan['id'],'version':plan['version'],'operation':'pause'})])
    assert h.service.scheduler.plan(plan['id'])==plan


@pytest.mark.parametrize('tool',['create_followup','save_work_note'])
def test_committed_local_result_survives_later_stop(harness,monkeypatch,tool):
    conv,h=harness
    target,method=(h.service.items,'create') if tool=='create_followup' else (h.bridge.store.original,'create_task')
    original=getattr(target,method)
    def after(*a,**kw):
        result=original(*a,**kw);stop(harness);return result
    monkeypatch.setattr(target,method,after)
    args={'description':'合成记录'} if tool=='create_followup' else {'project_id':project(conv),'title':'合成笔记'}
    _,ident,result=run(harness,'保存合成跟进记录',[call(tool,args)])
    assert len(h.s.rows('SELECT * FROM action_items') if tool=='create_followup' else _notes(harness))==1
    assert result.status=='stale'
    reservations=h.s.rows('SELECT * FROM am_harness_reservations WHERE run_id=?',(ident,))
    assert reservations and all(x['state']=='succeeded' for x in reservations)
    with h.bridge.store.original._connection() as c:
        assert not c.execute('SELECT 1 FROM conversation_actions').fetchone()


def test_cross_database_commit_ambiguity_requires_reconciliation(harness,monkeypatch):
    conv,h=harness; original=h.tasks.transaction_guard
    @contextmanager
    def lost(*a,**kw):
        with original(*a,**kw) as conn:
            yield conn
            raise RuntimeError('synthetic lost gateway commit')
    monkeypatch.setattr(h.tasks,'transaction_guard',lost)
    _,ident,result=run(harness,'记录笔记',[call('save_work_note',{'project_id':project(conv),'title':'合成提交'})])
    assert result.status=='unknown' and h.tasks.lane_status()['state']=='quarantined'
    assert len(_notes(harness))==1
    reservations=h.s.rows('SELECT * FROM am_harness_reservations WHERE run_id=?',(ident,))
    assert reservations and reservations[0]['state']=='reserved'
    with h.bridge.store.original._connection() as c:
        assert c.execute('SELECT count(*) FROM am_harness_local_commits').fetchone()[0]==1
    from am_harness.reservation import reconcile_local_commit
    assert reconcile_local_commit(h, reservations[0]['id']) == 'succeeded'
    assert h.tasks.lane_status()['state']=='quarantined'
    assert h.run_once().status=='idle'
    assert len(_notes(harness))==1


def test_missing_local_executor_does_not_fall_through_to_legacy(harness):
    conv,h=harness;h.bridge.agent.local_executor=None
    run(harness,'登记记录',[call('create_followup',{'description':'绝不能写入'}),answer('未登记。')])
    assert not h.s.rows('SELECT * FROM action_items')


@pytest.mark.parametrize('invalid',['unverified','cancelled','expired','permission','revision','unsent'])
def test_unusable_history_never_reaches_prompt(harness,invalid):
    conv,h=harness;marker='合成历史独特标记'
    row,ident=execute(harness,'普通第一轮',[answer(marker)])
    if invalid=='unverified':h.s.execute('UPDATE am_harness_outbox SET verified=0')
    elif invalid=='cancelled':stop(harness,'取消任务 '+ident)
    elif invalid=='unsent':h.s.execute("UPDATE am_conversation_outputs SET state='pending'")
    elif invalid=='revision':h.s.execute('UPDATE am_harness_runs SET revision=revision+1 WHERE id=?',(ident,))
    else:
        with h.bridge.store.original._connection(write=True) as c:
            c.execute("UPDATE conversation_messages SET "+('content_expires=0' if invalid=='expired' else "access_fingerprint='revoked'")+" WHERE role='assistant'")
    execute(harness,'请解释上一条',[answer('不引用不可用记录。')])
    assert marker not in conv[1].prompts[-1]


def test_equal_text_does_not_alias_undelivered_newer_event(harness):
    conv,h=harness;marker='同文不同事件标记'
    execute(harness,'第一轮',[answer(marker)])
    conv[1].outputs.append(answer(marker));row=incoming(harness,'第二轮');h.admit(row);assert h.run_once().status=='completed'
    # Only the first event is acknowledged; the second identical body is pending.
    execute(harness,'再展开第一轮',[answer('第三轮')])
    assert marker in conv[1].prompts[-1]


def test_old_model_project_cannot_overwrite_new_fast_focus(harness,monkeypatch):
    conv,h=harness;entered=threading.Event();release=threading.Event()
    execute(harness,'需求75谁负责')
    original=h.bridge.store.original.focus_setter
    def delayed(ctx,p,event=None):
        if h.bridge._current(ctx)['row']['body']=='请分析需求76的情况':
            entered.set();assert release.wait(4)
        return original(ctx,p,event)
    monkeypatch.setattr(h.bridge.store.original,'focus_setter',delayed)
    conv[1].outputs.append(answer('旧任务需求76回答。'))
    row=incoming(harness,'请分析需求76的情况');h.admit(row)
    results=[];worker=threading.Thread(target=lambda:results.append(h.run_once()));worker.start()
    assert entered.wait(3)
    try:execute(harness,'需求75谁负责')
    finally:release.set();worker.join(4)
    assert not worker.is_alive() and results[0].status=='completed'
    execute(harness,'那负责人呢？')
    assert 'AR1测试甲' in conv[0][3].sent[-1]['body'] and 'AR2乙' not in conv[0][3].sent[-1]['body']


@pytest.mark.parametrize('different', ['actor','thread','expiry','cancel'])
def test_focus_scope_and_lifetime(harness,different):
    conv,h=harness
    row,ident=execute(harness,'分析需求75',[answer('需求75分析')])
    if different=='expiry':conv[0][4].now+=601
    if different=='cancel':stop(harness,'取消任务 '+ident)
    if different=='actor':h.service.query_scope.setdefault('users',{})['ou_b']=['*']
    target=incoming(harness,'那负责人呢？',actor='ou_b' if different=='actor' else 'ou_a',thread='other' if different=='thread' else None)
    with h.bridge.request_context(dict(target)) as ctx:
        assert h.focus.get(ctx) is None


def test_local_budget_refusal_is_typed_and_next_request_runs(harness):
    conv,h=harness;original=h.bridge.agent.context_builder
    def too_large(ctx,**kw):kw['system']='合成超长系统内容'*10000;return original(ctx,**kw)
    h.bridge.agent.context_builder=too_large
    _,ident,result=run(harness,'普通问题',[])
    assert result.status=='failed' and result.error=='MANDATORY_CONTEXT_TOO_LARGE'
    assert h.tasks.lane_status()['state']=='idle' and not conv[1].prompts
    h.bridge.agent.context_builder=original
    execute(harness,'再问普通问题',[answer('可正常处理。')])


@pytest.mark.parametrize('code',['MANDATORY_CONTEXT_TOO_LARGE','STOP_UNKNOWN'])
def test_provider_exception_text_is_not_local_preparation_proof(harness,code):
    conv,h=harness
    def unknown(*a,**kw):raise RuntimeError(code)
    conv[1].complete=unknown
    _,ident,result=run(harness,'普通问题',[])
    assert result.status=='unknown' and h.tasks.lane_status()['state']=='quarantined'


def notices(h):return h.s.rows("SELECT * FROM am_notifications WHERE kind='harness_error'")


def test_maintenance_expiry_survives_host_reconstruction(harness):
    conv,h=harness;row=incoming(harness,'待过期任务');ident=h.admit(row)
    conv[0][4].now+=121;h.tasks.purge_expired()
    h.close();h.installation.restore();h.bridge.agent.lifecycle=None
    h.bridge.store=h.bridge.agent.store=h.bridge.store.original
    fresh=HarnessHost(h.service,SETTINGS);h.service.harness=fresh
    try:
        fresh.sync_terminal();fresh.sync_terminal()
        assert len(notices(fresh))==1
        assert fresh.s.rows('SELECT state,error FROM am_inbox WHERE id=?',(row['id'],))[0]=={'state':'harness_expired','error':'DEADLINE_EXCEEDED'}
        assert fresh.run_once().status=='idle' and not conv[1].prompts
    finally:fresh.close()


def test_expired_identity_does_not_prevent_internal_terminal_sync(harness,monkeypatch):
    conv,h=harness;row=incoming(harness,'待过期任务');h.admit(row)
    conv[0][4].now+=121;h.tasks.purge_expired()
    def denied(*a,**kw):raise RuntimeError('QUERY_IDENTITY_REVOKED')
    monkeypatch.setattr(h.bridge,'_grant',denied)
    h.sync_terminal()
    assert not notices(h)
    assert h.s.rows('SELECT state,error FROM am_inbox WHERE id=?',(row['id'],))[0]['state']=='harness_expired'
    assert h.s.rows('SELECT expires FROM am_inbox WHERE id=?',(row['id'],))[0]['expires']==row['expires']


def test_notice_retry_uses_durable_idempotency_without_replay(harness,monkeypatch):
    conv,h=harness;row=incoming(harness,'待过期任务');h.admit(row)
    conv[0][4].now+=121;h.tasks.purge_expired()
    original=h.failure_notice
    monkeypatch.setattr(h,'failure_notice',lambda saved:False);h.sync_terminal();assert not notices(h)
    monkeypatch.setattr(h,'failure_notice',original);conv[0][4].now+=31;h.sync_terminal();h.sync_terminal()
    assert len(notices(h))==1 and h.run_once().status=='idle'
    assert not conv[1].prompts


def test_content_expiry_finishes_inbox_without_late_notice(harness):
    conv,h=harness;row=incoming(harness,'待过期任务');h.admit(row)
    conv[0][4].now=row['expires']+1;h.tasks.purge_expired();h.sync_terminal()
    assert not notices(h)
    assert h.s.rows('SELECT state FROM am_inbox WHERE id=?',(row['id'],))[0]['state']=='harness_expired'


def test_optional_notes_selected_whole_with_omission_reason(harness):
    conv,h=harness;row=incoming(harness,'解释这些工作笔记')
    body='合成完整条目，保持条件。'*250
    with h.bridge.request_context(dict(row)) as ctx:
        for i in range(4):h.bridge.store.create_task(ctx,project_id=project(conv),title='合成'+str(i),details=body)
    conv[1].outputs.append(answer('按完整条目处理。'));h.admit(row);assert h.run_once().status=='completed'
    from am_conversation.model import _PROMPT
    envelope=json.loads(conv[1].prompts[-1][len(_PROMPT):])
    selected=[]
    for m in envelope['messages']:
        if m['content'].startswith('AM_SOURCE_DATA\n'):
            selected.extend(json.loads(m['content'].split('\n',1)[1])['tasks'])
    assert 0 < len(selected) < 4
    assert all(json.loads(item['details'])['record']['details']==body for item in selected)
    selection=[e for e in h.trace.records if e['event']=='context_selection'][-1]
    assert selection['omitted_budget_notes']==4-len(selected)


def test_history_dependency_and_original_expiry_propagate(harness):
    conv,h=harness
    row,ident=execute(harness,'请分析需求75',[answer('合成项目分析记录。')])
    before=h.s.rows('SELECT * FROM am_harness_context_sources WHERE event_id=?',('harness:'+ident+':v1',))[0]
    row2,ident2=execute(harness,'把上一条回答展开说明',[answer('基于前一条记录继续说明。')])
    after=h.s.rows('SELECT * FROM am_harness_context_sources WHERE event_id=?',('harness:'+ident2+':v1',))[0]
    assert json.loads(before['dependencies'])
    assert json.loads(before['dependencies']).items() <= json.loads(after['dependencies']).items()
    for key,end in json.loads(before['expiries']).items():assert json.loads(after['expiries'])[key]<=end


def test_local_change_has_atomic_committed_reservation(harness):
    conv,h=harness
    execute(harness,'登记跟进',[call('create_followup',{'description':'合成跟进'})])
    item=h.s.rows('SELECT * FROM action_items')[0]
    _,ident=execute(harness,'暂停跟进',[call('change_followup',{'item_id':item['id'],'version':1,'operation':'pause'})])
    rows=h.s.rows('SELECT * FROM am_harness_reservations WHERE run_id=?',(ident,))
    assert {r['kind'] for r in rows} >= {'local_transaction','followup_change'}
    assert all(r['state']=='succeeded' for r in rows)
