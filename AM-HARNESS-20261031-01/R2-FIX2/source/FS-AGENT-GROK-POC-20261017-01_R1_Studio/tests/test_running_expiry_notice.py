"""Independent audit boundary: running deadline is not an unstarted queue timeout."""
import json
import threading
from test_harness_host import harness, convo, ux, service, am_rig, base_rig, incoming, call, answer, project


def test_running_task_is_not_reported_as_unstarted_queue_timeout(harness):
    conv,h=harness
    entered=threading.Event()
    release=threading.Event()
    calls=[]
    original=conv[1].complete
    def blocked(*args,**kwargs):
        calls.append('model_dispatched')
        entered.set()
        assert release.wait(5)
        return original(*args,**kwargs)
    conv[1].complete=blocked
    conv[1].outputs.append(answer('合成晚返回回复'))
    row=incoming(harness,'解释一项通用工作方法')
    ident=h.admit(row)
    results=[]
    worker=threading.Thread(target=lambda:results.append(h.run_once()))
    worker.start()
    assert entered.wait(3)
    try:
        assert h.s.rows('SELECT state FROM am_harness_runs WHERE id=?',(ident,))[0]['state']=='running'
        conv[0][4].now+=121
        h.tasks.purge_expired()
        h.sync_terminal()
        lane=h.tasks.lane_status()['state']
        nextrow=incoming(harness,'另一个通用工作问题')
        nextident=h.admit(nextrow)
        idle=h.run_once()
        snapshot={
            'run':h.s.rows('SELECT state,error FROM am_harness_runs WHERE id=?',(ident,))[0],
            'worker_still_running':worker.is_alive(),
            'notices':h.s.rows("SELECT body FROM outbox WHERE body LIKE '%任务编号%'"),
            'model_has_started':entered.is_set(),
            'lane_state':lane,
            'automatic_model_replays':len(calls)-1,
            'next_run_state':h.s.rows('SELECT state FROM am_harness_runs WHERE id=?',(nextident,))[0]['state'],
            'next_run_attempt':idle.status,
        }
        print(json.dumps(snapshot,ensure_ascii=False))
        assert snapshot['run']=={'state':'expired','error':'DEADLINE_EXCEEDED'}
        assert snapshot['notices'] and snapshot['worker_still_running']
        assert lane=='quarantined'
        assert len(calls)==1 and idle.status=='idle' and snapshot['next_run_state']=='queued'
        assert all('排队超时' not in r['body'] for r in snapshot['notices']),snapshot
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
