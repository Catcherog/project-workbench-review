"""Five behavior regressions for AM-HARNESS R1.

All I/O is provided by the original synthetic test fixtures. These tests do not
start AM, access real Feishu/Qwen, change a service, or send a real message.
Every assertion describes correct behavior. On audited c968eca all five fail.
"""
import json

from test_harness_host import (
    harness, convo, ux, service, am_rig, base_rig,
    execute, incoming, call, answer, project,
)
from am_harness.store import Scope


def test_F01_stop_before_local_followup_commit_blocks_mutation(harness):
    conv, host = harness
    execute(harness, '登记需求75报告跟进', [call('create_followup', {
        'project_id': project(conv), 'description': '合成跟进',
    })])
    item = host.s.rows('SELECT * FROM action_items')[0]
    host.service.items.change('ou_a', 'setup-pause', item['id'], item['version'], 'pause')
    before = host.service.items.get(item['id'])
    original = host.service.items.change

    def cancel_before_commit(*args, **kwargs):
        stop = incoming(harness, '停止当前任务')
        host.admit(stop)
        return original(*args, **kwargs)

    host.service.items.change = cancel_before_commit
    conv[1].outputs.append(call('change_followup', {
        'item_id': item['id'], 'version': before['version'], 'operation': 'resume',
    }))
    row = incoming(harness, '恢复这项跟进')
    run_id = host.admit(row)
    result = host.run_once()
    after = host.service.items.get(item['id'])
    run = host.tasks.get(Scope(*host.bridge._identity(row)), run_id)
    print(json.dumps({'case': 'F01', 'run_state': run.state, 'worker_status': result.status,
                      'before': {'version': before['version'], 'paused': before['paused']},
                      'after': {'version': after['version'], 'paused': after['paused']}}))
    assert run.state == 'cancelled'
    assert after['paused'] == before['paused'] == 1
    assert after['version'] == before['version']


def test_F02_delivered_durable_reply_reaches_next_model_prompt(harness):
    conv, host = harness
    marker = '先核实原始记录，再判断是否可以结项。'
    row, run_id = execute(harness, '解释项目收尾判断方法', [answer(marker)])
    out = host.s.rows('SELECT * FROM am_harness_outbox')[0]
    saved = host.s.rows('SELECT * FROM am_conversation_outputs')[0]
    assert out['state'] == 'sent' and out['verified'] == 1
    assert saved['state'] == 'acknowledged'
    with host.bridge.request_context(dict(row)) as ctx:
        history = host.bridge.store.history(ctx)
    assert any(m['role'] == 'assistant' and marker in m['content'] for m in history)
    execute(harness, '把你上一条回答展开说明', [answer('接下来详细说明。')])
    prompt = conv[1].prompts[-1]
    print(json.dumps({'case': 'F02', 'source_event_id': saved['event_id'],
                      'engine_event_id': json.loads(saved['reply'])['event_id'],
                      'verified': out['verified'], 'delivery_state': saved['state'],
                      'visible_in_history': True, 'visible_in_next_prompt': marker in prompt},
                     ensure_ascii=False))
    assert marker in prompt


def test_F03_fast_pronoun_respects_completed_project_switch(harness):
    conv, host = harness
    execute(harness, '需求75的项目进展')
    row, _ = execute(harness, '请分析需求76的进展并提出建议',
                     [answer('需求76仍在处理中，建议先核对乙报告。')])
    with host.bridge.request_context(dict(row)) as ctx:
        focus = host.bridge.store.get_focus(ctx)
        titles = {p['id']: p['title'] for p in host.bridge.projects.list_projects(ctx)}
    assert '需求76' in titles[focus]
    # A repaired implementation may use a proven current quick focus or fall
    # back to the original model. Both may answer B; neither may answer stale A.
    execute(harness, '那负责人呢？', [answer('需求76的负责人是AR2乙。')])
    delivered = conv[0][3].sent[-1]['body']
    print(json.dumps({'case': 'F03', 'current_project': titles[focus],
                      'followup_answer': delivered}, ensure_ascii=False))
    assert 'AR2乙' in delivered and 'AR1测试甲' not in delivered


def test_F04_local_context_budget_failure_does_not_quarantine_global_lane(harness):
    conv, host = harness
    row = incoming(harness, '解释已有工作笔记如何处理')
    notes = []
    with host.bridge.request_context(dict(row)) as ctx:
        project_id = sorted(ctx.allowed_project_ids)[0]
        for i in range(3):
            notes.append(host.bridge.store.create_task(ctx, project_id=project_id,
                title='合成工作记录' + str(i), details='待核信息。' * 550))
    # If bounded selection is implemented the first request can succeed. A
    # classified pre-dispatch refusal is also acceptable; unknown is not.
    conv[1].outputs.append(answer('工作笔记是待核事项，需要结合当前证据处理。'))
    run_id = host.admit(row)
    result = host.run_once()
    lane = host.tasks.lane_status()
    print(json.dumps({'case': 'F04', 'status': result.status, 'error': result.error,
                      'lane': lane['state'], 'model_calls': len(conv[1].prompts)}))
    assert lane['state'] == 'idle'
    assert result.status != 'unknown'
    # Remove the deliberately large fixture before proving the next ordinary
    # request is runnable. This is local synthetic cleanup, not pause clearing.
    with host.bridge.request_context(dict(row)) as ctx:
        for note in notes:
            host.bridge.store.update_task(ctx, note['id'], expected_version=note['version'],
                                          changes={'status': 'closed'})
    conv[1].outputs.clear()
    later = incoming(harness, '解释一个简单概念')
    later_id = host.admit(later)
    conv[1].outputs.append(answer('计划表示安排，完成需要相应结果证据。'))
    later_result = host.run_once()
    assert later_result.status == 'completed'
    assert host.s.rows('SELECT state FROM am_harness_runs WHERE id=?', (later_id,))[0]['state'] == 'succeeded'


def test_F05_queued_expiry_updates_inbox_and_notifies_once(harness):
    conv, host = harness
    am = conv[0][0]
    am.enable_background()
    row = incoming(harness, '请解释排队的任务')
    run_id = host.admit(row)
    conv[0][4].now += 121
    for _ in range(2):
        am.pump()
        if host.worker is not None:
            host.worker.result(timeout=3)
        for future in list(am.io_futures.values()):
            future.result(timeout=3)
    am.step(maintenance=True)
    saved = host.s.rows('SELECT state,error FROM am_harness_runs WHERE id=?', (run_id,))[0]
    inbox = host.s.rows('SELECT state,error FROM am_inbox WHERE id=?', (row['id'],))[0]
    sql = "SELECT o.id FROM outbox o JOIN am_notifications n ON n.outbox_id=o.id WHERE n.kind='harness_error'"
    notices = host.s.rows(sql)
    print(json.dumps({'case': 'F05', 'run': saved, 'inbox': inbox,
                      'failure_notices': len(notices), 'model_calls': len(conv[1].prompts)}))
    assert saved['state'] == 'expired'
    assert inbox['state'] != 'harness_queued' and inbox['error'] == 'DEADLINE_EXCEEDED'
    assert len(notices) == 1
    am.pump()
    am.step(maintenance=True)
    assert len(host.s.rows(sql)) == 1
    assert not conv[1].prompts
