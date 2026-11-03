"""Independent F01 regression: unknown cross-database commits must stay unknown.

Uses the fixed review snapshot's original host fixtures; all I/O is synthetic.
The expected behavior assertions intentionally fail against R1-FIX1.
"""
from contextlib import contextmanager
import json
import pytest
from test_harness_host import harness, convo, ux, service, am_rig, base_rig, incoming, execute, call, answer, project


@pytest.mark.parametrize('tool', ['propose_knowledge', 'record_report'])
def test_unknown_knowledge_commit_preserves_quarantine(harness, monkeypatch, tool):
    conv, host = harness
    original = host.tasks.transaction_guard
    @contextmanager
    def lost_gateway_commit(*args, **kwargs):
        with original(*args, **kwargs) as connection:
            yield connection
            raise RuntimeError('synthetic lost gateway commit')
    monkeypatch.setattr(host.tasks, 'transaction_guard', lost_gateway_commit)
    args = ({'kind':'rule','content':'合成知识提交中断标记'} if tool == 'propose_knowledge'
            else {'project_id':project(conv),'content':'合成知识提交中断标记'})
    conv[1].outputs.extend([call(tool, args), answer('工具结果需要核实。')])
    row = incoming(harness, '请保存这条合成知识和反馈资料')
    run_id = host.admit(row)
    result = host.run_once()
    records = [dict(row) for row in host.bridge.knowledge._db.execute('SELECT id,status,content FROM knowledge_records')]
    has_receipt_table = host.bridge.knowledge._db.execute("SELECT 1 FROM sqlite_master WHERE name='am_harness_local_commits'").fetchone()
    receipts = [dict(row) for row in host.bridge.knowledge._db.execute('SELECT * FROM am_harness_local_commits')] if has_receipt_table else []
    reservations = host.s.rows('SELECT state,kind FROM am_harness_reservations WHERE run_id=?', (run_id,))
    run = host.s.rows('SELECT state,error FROM am_harness_runs WHERE id=?', (run_id,))[0]
    lane = host.tasks.lane_status()
    observed = {'tool':tool,'result':result.__dict__,'run':run,'lane':lane['state'],
                'records':records,'receipt_count':len(receipts),'reservations':reservations,
                'model_calls':len(conv[1].prompts),'generic_error_in_second_prompt':len(conv[1].prompts)>1 and 'TOOL_UNAVAILABLE' in conv[1].prompts[-1]}
    print(json.dumps(observed,ensure_ascii=False,indent=2))
    assert len(records) == 1 and len(receipts) == 1
    assert reservations == [{'state':'reserved','kind':'local_database'}]
    assert result.status == 'unknown', observed
    assert run['state'] == 'unknown' and lane['state'] == 'quarantined', observed


def test_direct_knowledge_approval_is_fenced_at_commit(harness, monkeypatch):
    conv, host = harness
    execute(harness, '保存合成待批准知识', [call('propose_knowledge', {'kind':'rule','content':'合成知识批准取消标记'})])
    record = dict(host.bridge.knowledge._db.execute('SELECT * FROM knowledge_records').fetchone())
    assert record['status'] == 'candidate'
    original = host.bridge.knowledge.approve
    def interrupted(*args, **kwargs):
        host.admit(incoming(harness, '停止当前任务'))
        return original(*args, **kwargs)
    monkeypatch.setattr(host.bridge.knowledge, 'approve', interrupted)
    row = incoming(harness, '批准知识 ' + record['id'] + ' v1')
    run_id = host.admit(row)
    result = host.run_once()
    status = host.bridge.knowledge._db.execute('SELECT status FROM knowledge_records WHERE id=?', (record['id'],)).fetchone()[0]
    run = host.s.rows('SELECT state,error FROM am_harness_runs WHERE id=?', (run_id,))[0]
    reservations = host.s.rows('SELECT state,kind FROM am_harness_reservations WHERE run_id=?', (run_id,))
    observed = {'result':result.__dict__, 'run':run, 'knowledge_status':status, 'reservations':reservations}
    print(json.dumps(observed,ensure_ascii=False,indent=2))
    assert result.status == 'stale' and run['state'] == 'cancelled'
    assert status == 'candidate', observed
