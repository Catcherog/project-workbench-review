"""Additional FIX2 transaction/provenance boundaries; all I/O synthetic."""
from contextlib import contextmanager
import json
import sqlite3
import pytest
from test_harness_host import harness, convo, ux, service, am_rig, base_rig, execute, incoming, call, answer, project
from am_harness.reservation import ingress_context, reconcile_local_commit


def stop(rig, text='停止当前任务'):
    with ingress_context():
        rig[1].admit(incoming(rig,text))


def run(rig,text,outputs=()):
    conv,h=rig;conv[1].outputs.extend(outputs);row=incoming(rig,text);ident=h.admit(row)
    return row,ident,h.run_once()


def candidate(rig):
    execute(rig,'保存合成待批准知识规则',[call('propose_knowledge',{'kind':'rule','content':'FIX2合成知识'})])
    return dict(rig[1].bridge.knowledge._db.execute('SELECT * FROM knowledge_records ORDER BY created_at DESC').fetchone())


def test_unknown_revise_knowledge_stops_after_one_model_call(harness,monkeypatch):
    conv,h=harness;old=candidate(harness);original=h.tasks.transaction_guard;before=len(conv[1].prompts)
    @contextmanager
    def lost(*a,**kw):
        with original(*a,**kw) as conn:
            yield conn
            raise RuntimeError('synthetic gateway commit interruption')
    monkeypatch.setattr(h.tasks,'transaction_guard',lost)
    _,ident,result=run(harness,'修订这条合成知识规则',[call('revise_knowledge',{'record_id':old['id'],'version':1,'content':'FIX2合成知识新版本'}),answer('不应继续调用模型')])
    assert result.status=='unknown' and result.error=='HARNESS_LOCAL_COMMIT_UNKNOWN'
    assert len(conv[1].prompts)==before+1 and h.tasks.lane_status()['state']=='quarantined'
    assert h.bridge.knowledge._db.execute('SELECT count(*) FROM knowledge_records').fetchone()[0]==2
    reservation=h.s.rows("SELECT id,state FROM am_harness_reservations WHERE run_id=? AND kind='local_database'",(ident,))[0]
    assert reservation['state']=='reserved'
    assert reconcile_local_commit(h,reservation['id'])=='succeeded'
    assert h.tasks.lane_status()['state']=='quarantined' and h.run_once().status=='idle'


@pytest.mark.parametrize('where',['before','after'])
@pytest.mark.parametrize('control',['stop','revise'])
def test_knowledge_approval_orders_control_against_commit(harness,monkeypatch,where,control):
    conv,h=harness;record=candidate(harness);original=h.bridge.knowledge.approve
    def changed(*a,**kw):
        command='停止当前任务' if control=='stop' else '更正当前任务：仅解释待批准的含义'
        if where=='before':stop(harness,command)
        result=original(*a,**kw)
        if where=='after':stop(harness,command)
        return result
    monkeypatch.setattr(h.bridge.knowledge,'approve',changed)
    _,ident,result=run(harness,'批准知识 '+record['id']+' v1')
    assert result.status=='stale'
    actual=h.bridge.knowledge._db.execute('SELECT status FROM knowledge_records WHERE id=?',(record['id'],)).fetchone()[0]
    assert actual==('candidate' if where=='before' else 'approved')
    receipts=h.s.rows("SELECT state FROM am_harness_reservations WHERE run_id=? AND kind='local_database'",(ident,))
    assert receipts==([] if where=='before' else [{'state':'succeeded'}])
    assert not h.s.rows("SELECT 1 FROM am_conversation_outputs WHERE json_extract(reply,'$.event_id')=?",('harness:'+ident+':v1',))


@pytest.mark.parametrize('missing',['executor','binding'])
def test_direct_knowledge_without_binding_never_uses_legacy(harness,missing):
    conv,h=harness;record=candidate(harness)
    h.bridge.agent.local_control_executor=(None if missing=='executor' else lambda ctx,e,n,a,apply:apply())
    _,ident,result=run(harness,'批准知识 '+record['id']+' v1')
    assert result.error=='HARNESS_LOCAL_BINDING_REQUIRED'
    assert h.bridge.knowledge._db.execute('SELECT status FROM knowledge_records WHERE id=?',(record['id'],)).fetchone()[0]=='candidate'


def test_knowledge_version_guard_stays_authoritative(harness):
    conv,h=harness;record=candidate(harness)
    _,ident,result=run(harness,'批准知识 '+record['id']+' v2')
    assert result.status!='completed'
    assert h.bridge.knowledge._db.execute('SELECT status FROM knowledge_records WHERE id=?',(record['id'],)).fetchone()[0]=='candidate'
    assert not h.s.rows("SELECT 1 FROM am_harness_reservations WHERE run_id=? AND state='succeeded'",(ident,))


def test_direct_pending_cancel_is_fenced(harness,monkeypatch):
    conv,h=harness
    execute(harness,'准备给我发送测试消息',[call('send_message',{'target':'self','body':'FIX2合成发送预览'})])
    with h.bridge.store.original._connection() as db:action=dict(db.execute('SELECT * FROM conversation_actions').fetchone())
    original=h.bridge.store.original.cancel_action
    def interrupted(*a,**kw):stop(harness);return original(*a,**kw)
    monkeypatch.setattr(h.bridge.store.original,'cancel_action',interrupted)
    _,ident,result=run(harness,'取消 '+action['id'])
    with h.bridge.store.original._connection() as db:current=dict(db.execute('SELECT * FROM conversation_actions WHERE id=?',(action['id'],)).fetchone())
    assert result.status=='stale' and current['status']==action['status']=='draft'
    assert not h.s.rows('SELECT * FROM am_conversation_sends')


def test_knowledge_transaction_rolls_back_before_commit(harness):
    _,h=harness;k=h.bridge.knowledge;before=k._db.execute('SELECT count(*) FROM knowledge_records').fetchone()[0]
    with pytest.raises(RuntimeError,match='KNOWN_ABORT'):
        with k._transaction():
            k._db.execute("CREATE TABLE rollback_probe(value TEXT)")
            raise RuntimeError('KNOWN_ABORT')
    assert not k._db.in_transaction
    assert not k._db.execute("SELECT 1 FROM sqlite_master WHERE name='rollback_probe'").fetchone()
    assert k._db.execute('SELECT count(*) FROM knowledge_records').fetchone()[0]==before


def test_cleanup_failure_does_not_mask_original_unknown(harness):
    _,h=harness;k=h.bridge.knowledge;original=k._db
    class CleanupFailure:
        def __getattr__(self,key):return getattr(original,key)
        def execute(self,sql,*a):
            if sql=='ROLLBACK':raise sqlite3.OperationalError('synthetic rollback failure')
            return original.execute(sql,*a)
    k._db=CleanupFailure()
    try:
        with pytest.raises(RuntimeError,match='HARNESS_LOCAL_COMMIT_UNKNOWN'):
            with k._transaction():raise RuntimeError('HARNESS_LOCAL_COMMIT_UNKNOWN')
    finally:
        k._db=original
        if original.in_transaction:original.rollback()


def dynamic(rig,marker='FIX2动态项目回答标记',multiple=False):
    conv,h=rig
    row=incoming(rig,'仅用于取得合成项目标识')
    with h.bridge.request_context(dict(row)) as ctx:projects=h.bridge.projects.list_projects(ctx)
    ids=[p['id'] for p in projects][:2]
    outputs=[call('list_projects',{}),call('read_project',{'project_id':ids[0]})]
    if multiple:outputs.append(call('read_project',{'project_id':ids[1]}))
    outputs.append(answer(marker))
    _,ident=execute(rig,'请列出项目目录并分析其中的项目',outputs)
    return ident,ids[:2 if multiple else 1]


@pytest.mark.parametrize('invalidation',['unchanged','changed','expired','missing'])
def test_dynamic_multiple_projects_and_history_validity(harness,invalidation):
    conv,h=harness;marker='FIX2多项目历史标记';ident,ids=dynamic(harness,marker,True)
    saved=h.s.rows('SELECT * FROM am_harness_context_sources WHERE event_id=?',('harness:'+ident+':v1',))[0]
    deps=json.loads(saved['dependencies']);assert {'ledger:'+p for p in ids} <= set(deps)
    if invalidation=='changed':
        conv[0][5].values[1][4]='合成来源已变化';h.service.snapshots.refresh().result(3)
    elif invalidation=='expired':
        h.s.execute('UPDATE am_harness_context_sources SET expires=? WHERE event_id=?',(h.s.clock()-1,'harness:'+ident+':v1'))
    elif invalidation=='missing':
        h.s.execute("UPDATE am_harness_context_sources SET dependencies='{}',expiries='{}' WHERE event_id=?",('harness:'+ident+':v1',))
    _,later=execute(harness,'请展开上一条回答',[answer('合成后续说明')])
    assert (marker in conv[1].prompts[-1])==(invalidation=='unchanged')
    if invalidation=='unchanged':
        inherited=h.s.rows('SELECT expiries FROM am_harness_context_sources WHERE event_id=?',('harness:'+later+':v1',))[0]
        assert all(json.loads(inherited['expiries'])[s]<=t for s,t in json.loads(saved['expiries']).items())


def test_catalog_only_history_also_obeys_source_version(harness):
    conv,h=harness;marker='FIX2项目目录标记'
    _,ident=execute(harness,'请给我项目目录',[call('list_projects',{}),answer(marker)])
    saved=h.s.rows('SELECT * FROM am_harness_context_sources WHERE event_id=?',('harness:'+ident+':v1',))[0]
    assert 'ledger-catalog' in json.loads(saved['dependencies'])
    conv[0][5].values[1][4]='合成新来源';h.service.snapshots.refresh().result(3)
    execute(harness,'展开上一条回答',[answer('新一轮说明')]);assert marker not in conv[1].prompts[-1]


@pytest.mark.parametrize('damage',['missing','expired'])
def test_publication_refuses_incomplete_dynamic_provenance(harness,monkeypatch,damage):
    conv,h=harness;original=h.publish;entered=[]
    def damaged(conn,run,outcome):
        entered.append(True)
        event=outcome['prepared']['reply']['event_id']
        if damage=='missing':conn.execute("UPDATE am_harness_context_sources SET dependencies='{}',expiries='{}' WHERE event_id=?",(event,))
        else:conn.execute('UPDATE am_harness_context_sources SET expires=? WHERE event_id=?',(h.s.clock()-1,event))
        return original(conn,run,outcome)
    monkeypatch.setattr(h.runtime,'publish',damaged)
    _,ident,result=run(harness,'请列出目录并分析第一个项目',[call('list_projects',{}),call('read_project',{'project_id':project(conv)}),answer('不应发布的合成项目答案')])
    assert entered==[True] and result.status=='failed'
    assert not h.s.rows('SELECT * FROM am_conversation_outputs')


def test_true_queue_expiry_has_no_dispatch_and_notifies_once(harness):
    conv,h=harness;row=incoming(harness,'排队问题');ident=h.admit(row);conv[0][4].now+=121
    h.tasks.purge_expired();h.sync_terminal();h.sync_terminal()
    saved=h.s.rows('SELECT lease_generation,state FROM am_harness_runs WHERE id=?',(ident,))[0]
    notices=h.s.rows("SELECT o.body FROM outbox o JOIN am_notifications n ON n.outbox_id=o.id WHERE n.kind='harness_error'")
    assert saved=={'lease_generation':0,'state':'expired'} and len(notices)==1
    assert '排队超时' in notices[0]['body'] and not conv[1].prompts
