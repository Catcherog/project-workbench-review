"""Real host/storage/outbox integration; platform/model I/O remains synthetic."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_harness_host import harness, convo, ux, service, am_rig, base_rig, incoming, execute, call, answer, project
from test_gateway import drain
from am_response.pipeline import ResponsePipeline
from am_response.gateway import GatewayProjection
from am_outcome.types import fingerprint


@pytest.fixture
def response(harness, request):
    conv, h = harness
    h.bridge.agent.response_pipeline = ResponsePipeline({'mode': 'canonical'},
        binding=h.bridge.response_binding,
        targets=lambda ctx: h.bridge._current(ctx).get('project_catalog', []), clock=h.s.clock)
    h.bridge.agent.model.model.response_protocol = True
    h.s.response_projection = GatewayProjection(h.s)
    yield harness
    record_metrics(request.node.name, presentations(h), h.s)


def presentations(h):
    with h.bridge.store.original._connection() as db:
        return [json.loads(r[0]) for r in db.execute('SELECT data_json FROM conversation_presentations_v2 ORDER BY rowid')]


def record_metrics(case, records, store):
    directory = os.environ.get('AM_RESPONSE_EVIDENCE_PATH')
    if not directory: return
    rows = store.rows('SELECT presentation_id,state FROM am_response_outbox_v2')
    delivery = {r['presentation_id']: r['state'] for r in rows}
    data = []
    for record in records:
        entry = {k:v for k,v in record.items() if k != 'outcome'}
        entry.update(families=record['outcome']['families'],
                     delivery=delivery.get(record['presentation_id'], 'not_queued'),
                     case_id=case, layer='L1_real_host_synthetic_io')
        data.append(entry)
    path=Path(directory); path.mkdir(parents=True,exist_ok=True)
    (path/(fingerprint(case)+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


@pytest.mark.parametrize('field', ['项目进展', '关键日期', '有哪些待办', '谁负责'])
def test_fastpath_freezes_real_event_and_no_model(response, field):
    conv, h = response
    row, out = execute(response, '需求75' + field)
    saved = presentations(h)[0]
    assert saved['task_model_calls'] == saved['presentation_calls'] == 0
    assert saved['outcome']['binding']['kind'] == 'event'
    assert saved['outcome']['families'] == ['query']
    assert saved['outcome']['binding']['origin_event_id'] == row['id']
    assert h.admit(row) == out and len(presentations(h)) == 1
    assert h.s.rows('SELECT count(*) AS n FROM am_response_outbox_v2')[0]['n'] == 1


def test_identical_text_different_events_stays_distinct(response):
    _, h = response
    execute(response, '需求75谁负责'); execute(response, '需求75谁负责')
    p = presentations(h)
    assert len(p) == 2 and p[0]['presentation_id'] != p[1]['presentation_id']


def test_wrong_object_refused_before_note_write(response):
    conv, h = response
    p = project(conv)
    execute(response, '为需求75登记跟进', [call('save_work_note', {'project_id': p, 'title': '合成事项'}), answer('已登记跟进'), answer('已登记跟进')])
    with h.bridge.store.original._connection() as db:
        assert db.execute('SELECT count(*) FROM conversation_tasks').fetchone()[0] == 0
    saved = presentations(h)[0]
    assert saved['business_completion'] != 'fulfilled'
    assert next(u for u in saved['outcome']['work_units'] if u['operation']=='save_work_note')['result']['code'] == 'REQUESTED_FOLLOWUP_NOT_WORKNOTE'
    assert '尚未完成' in h.s.rows('SELECT body FROM outbox')[0]['body']


def test_two_goals_partial_result_and_failure_both_visible(response):
    conv, h = response
    row = incoming(response, '取得项目对象')
    with h.bridge.request_context(row) as ctx:
        ids = [p['id'] for p in h.bridge.projects.list_projects(ctx)]
    assert len(ids) >= 2
    a = call('create_followup', {'project_id': ids[0], 'description': '合成事项甲'})['tool_calls'][0]
    b = call('create_followup', {'project_id': ids[1], 'description': '合成事项乙', 'next_check': '2026-12-01T09:00:00+08:00'})['tool_calls'][0]
    b['id'] = 'second-call'
    execute(response, '分别为需求75和需求76登记跟进', [{'type': 'tool_calls', 'tool_calls': [a, b]}, answer('全部完成'), answer('全部完成')])
    result = presentations(h)[0]
    assert result['business_completion'] == 'partial'
    assert len([u for u in result['outcome']['work_units'] if u['effect']=='local']) == 2
    body = h.s.rows('SELECT body FROM outbox')[0]['body']
    assert '已登记' in body and '尚未' in body and '全部完成' not in body
    assert len(h.s.rows('SELECT * FROM action_items')) == 1


def test_direct_model_plan_without_second_model_call_or_old_rewriter(response):
    conv, h = response
    def forbidden(**kw): raise AssertionError('second expression pipeline')
    h.bridge.agent.output_finalizer = forbidden
    def plan(prompt, **kw):
        conv[1].prompts.append(prompt)
        payload = json.loads(prompt[prompt.index('{"messages":'):])
        raw = next(m['content'].split('host_outcome=', 1)[1] for m in payload['messages'] if 'host_outcome=' in m['content'])
        outcome = json.loads(raw)
        return SimpleNamespace(text=json.dumps({'type': 'response_plan', 'plan': {
            'envelope_fingerprint': outcome['outcome_hash'],
            'segments': [{'kind': 'text', 'intent': 'answer', 'text': '这是未核实的回答', 'claim_ids': []}],
            'omitted_optional_claim_ids': []}}, ensure_ascii=False))
    conv[1].complete = plan
    execute(response, '解释一个需要判断的问题')
    result = presentations(h)[0]
    assert result['attempted'] and not result['adopted']
    assert result['task_model_calls'] == 1 and result['presentation_calls'] == 0
    assert len(conv[1].prompts) == 1
    assert result['reason'] == 'claims_invalid'
    out = h.s.rows('SELECT * FROM outbox')[0]
    saved = h.s.rows('SELECT * FROM am_conversation_outputs')[0]
    assert out['body'] == json.loads(saved['reply'])['text']
    assert result['semantic_hash'] == fingerprint(out['body'])
    assert h.s.rows('SELECT state FROM am_response_outbox_v2')[0]['state'] == 'verified'


def test_preview_payload_version_and_original_confirmation(response):
    conv, h = response
    execute(response, '准备给我发合成消息', [call('send_message', {'target': 'self', 'body': '合成预览原文'})])
    first = presentations(h)[0]
    assert first['business_completion'] == 'awaiting_approval'
    assert not h.s.rows('SELECT * FROM am_conversation_sends')
    execute(response, '确认第1项')
    assert len(h.s.rows('SELECT * FROM am_conversation_sends')) == 1
    assert presentations(h)[1]['outcome']['work_units'][0]['verified'] is True
    assert presentations(h)[1]['business_completion'] == 'fulfilled'


def test_source_change_during_finalization_suppresses_body(response, monkeypatch):
    conv, h = response
    original = h.bridge.agent.response_pipeline.finish
    def invalidated(*a, **kw):
        result = original(*a, **kw)
        from am_harness.reservation import ingress_context
        with ingress_context():
            h.admit(incoming(response, '停止当前任务'))
        return result
    monkeypatch.setattr(h.bridge.agent.response_pipeline, 'finish', invalidated)
    conv[1].outputs.append(answer('不得发送'))
    row = incoming(response, '解释一个复杂问题'); h.admit(row)
    result = h.run_once()
    assert result.status == 'stale'
    assert not h.s.rows('SELECT * FROM am_conversation_outputs')


def test_protected_legacy_card_has_no_generation_credit(response):
    conv, h = response
    row = incoming(response, '测试保护卡片')
    h.service.card(row, object_id='synthetic-card', version=1, snapshot={'version': 1},
        title='合成卡片', body='尚未批准', actions=[('confirm', '确认')], flow='test')
    saved = json.loads(h.s.rows('SELECT data_json FROM am_response_outbox_v2')[0]['data_json'])
    assert saved['selected_source'] == 'legacy_protected' and not saved['adopted']
    assert saved['object_version'] == 1 and saved['payload_binding']


def test_presentation_retention_uses_original_expiry(response):
    conv, h = response
    execute(response, '需求75谁负责')
    h.s.execute('UPDATE am_response_outbox_v2 SET expires=?', (h.s.clock()-1,))
    with h.bridge.store.original._connection(write=True) as db:
        db.execute('UPDATE conversation_presentations_v2 SET expires=?', (h.s.clock()-1,))
    h.s.cleanup(); h.bridge.store.cleanup_messages()
    assert not presentations(h) and not h.s.rows('SELECT * FROM am_response_outbox_v2')


@pytest.mark.parametrize('code,category', [('MODEL_BUSY','not_dispatched'), ('STOP_UNKNOWN','provider_stop_unknown')])
def test_model_interrupt_is_classified_without_fallback_or_lane_release(response, code, category):
    conv, h = response
    from fs_agent.config import BoundaryError
    def fail(*a, **kw): raise BoundaryError(code)
    conv[1].complete = fail
    row=incoming(response, '解释这份合成方案'); h.admit(row)
    result=h.run_once()
    assert result.status != 'completed'
    assert not h.s.rows('SELECT * FROM am_conversation_outputs')
    with h.bridge.store.original._connection() as db:
        data=json.loads(db.execute('SELECT data_json FROM conversation_response_interrupts_v2').fetchone()[0])
    assert data['classification']==category
    assert not data['automatic_retry'] and not data['lane_released_by_response']
    if code=='STOP_UNKNOWN': assert h.tasks.lane_status()['state']=='quarantined'


@pytest.mark.parametrize('case_name', [
    'test_create_followup_and_pause_use_original_item_store',
    'test_group_send_waits_for_exact_text_readback_and_natural_confirmation',
    'test_unknown_send_never_repeats_and_can_reconcile',
    'test_schedule_activation_cancel_and_no_early_send',
    'test_teaching_natural_approval_is_scoped_and_delivered',
    'test_new_document_does_not_cancel_earlier_draft',
    'test_project_feedback_flows_to_owner_without_ledger_write',
    'test_change_reminder_time_requires_new_preview_and_keeps_plan_identity',
    'test_briefing_subscription_is_confirmed_and_cancellable',
    'test_consumed_once_reminder_can_still_be_listed_and_cancelled',
    'test_standard_target_change_requires_current_result_before_cloud_preview',
])
def test_real_business_adapters_under_new_pipeline(convo, case_name):
    import test_conversation_integration as original_cases
    am = convo[0][0]; bridge = am.conversation
    bridge.agent.response_pipeline = ResponsePipeline({'mode': 'canonical'}, binding=bridge.response_binding,
        targets=lambda ctx: bridge._current(ctx).get('project_catalog', []), clock=am.s.clock)
    bridge.agent.model.model.response_protocol = True
    am.s.response_projection = GatewayProjection(am.s)
    getattr(original_cases, case_name)(convo)
    with bridge.store._connection() as db:
        records = [json.loads(r[0]) for r in db.execute('SELECT data_json FROM conversation_presentations_v2')]
    assert records and all(p['presentation_calls'] == 0 for p in records)
    assert all(p['naturalness']=='not_evaluated' for p in records)
    record_metrics(case_name, records, am.s)


@pytest.mark.parametrize('change', ['missing_block', 'invented_fact', 'wrong_fingerprint', 'malformed_intent'])
def test_untrusted_plan_never_replaces_verified_result(response, change):
    conv, h = response
    pipeline = h.bridge.agent.response_pipeline
    row = incoming(response, '读取合成资料')
    from am_conversation.types import AgentReply
    with h.bridge.request_context(row) as ctx:
        token = pipeline.begin(ctx, row['id'], row['body'])
        try:
            pipeline.record('read_information', {}, {'facts': [{'fact_id':'f1', 'field':'progress', 'value':'试验预计完成，尚未验收。'}], 'complete_response':False, 'has_more':True}, 'read')
            envelope = pipeline.envelope(); data = envelope.data
            plan = {'envelope_fingerprint': envelope.digest, 'segments': [
                {'kind':'text', 'intent':'answer', 'text':'试验已验收。', 'claim_ids':[data['claims'][0]['id']]},
                *[{'kind':'locked', 'block_id':b['id']} for b in data['protected_blocks']]], 'omitted_optional_claim_ids':[]}
            if change=='missing_block': plan['segments']=plan['segments'][:1]
            if change=='wrong_fingerprint': plan['envelope_fingerprint']='0'*64
            if change=='malformed_intent': plan['segments'][0]['intent']=['answer']
            candidate, reason = pipeline.validate(plan, envelope, 6000)
            assert candidate is None
            if change=='invented_fact': assert reason=='semantic_profile_unavailable'
        finally:
            pipeline.end(token)
