"""UX2-FIX1: synthetic inputs through the real inbox, cards and business loop."""
import json
from datetime import datetime, timedelta
import pytest
from test_am_ux1 import ux, service, am_rig, base_rig, request, click, latest, text
from test_am_ux2 import confirm_plan
from test_gateway import drain
from fs_agent.scheduler import TZ
from fs_agent.feishu import SendRejected, SendUnknown
from fs_agent.presentation import visible_metrics
from group_ai import QwenGroupAssistant
from test_group_ai import Provider
from group_ledger import parse_rows, render_project


def occurrence(ux):
    p = confirm_plan(ux, ['0', '1'])
    am, g, s, api, clock, _ = ux
    clock.now = p['next_at']; am.scheduler.scan()
    o = s.rows('SELECT * FROM reminder_occurrences')[0]
    s.execute("UPDATE reminder_occurrences SET state='sent',message_id='om_feedback',readback_state='verified' WHERE id=?", (o['id'],))
    return o


def feedback(ux, o, event_id, kind='help', detail='治具未到，需要协助', actor='ou_engineer_a', eta=None):
    am, g, s, api, clock, _ = ux
    values = {'kind': kind, 'detail': detail}
    if eta is not None: values['eta'] = eta
    e = {'header': {'app_id': g.config.app_id, 'tenant_key': g.config.tenant_key,
                    'event_id': event_id, 'event_type': 'card.action.trigger'},
         'event': {'operator': {'open_id': actor},
                   'context': {'open_chat_id': 'oc_reminder', 'open_message_id': 'om_feedback'},
                   'action': {'value': {'flow': 'am_self', 'feedback': o['id'],
                                        'nonce': json.loads(o['payload'])['feedback_nonce'], 'action': 'feedback_form'},
                              'form_value': values}}}
    accepted = am.ingest(e)
    if accepted[1]: am.step(); drain(g)
    return s.rows('SELECT * FROM am_inbox WHERE id=?', (event_id,))[0]


def test_F01_new_round_same_text_and_replay(ux):
    o = occurrence(ux); am, g, s, api, clock, _ = ux; n = len(api.sent)
    feedback(ux, o, 'A1'); clock.now += 60
    feedback(ux, o, 'B', 'submitted', '已上传报告初稿'); clock.now += 60
    feedback(ux, o, 'A2')
    assert [h['kind'] for h in am.items.history(o['item_id'])] == ['help', 'submitted', 'help']
    assert am.items.get(o['item_id'])['state'] == 'blocked'
    assert len(api.sent) == n + 6
    feedback(ux, o, 'A2'); feedback(ux, o, 'A2-doubleclick')
    # An old event replay still belongs to the original operation, even after A-B-A.
    feedback(ux, o, 'A1')
    assert len(api.sent) == n + 6
    feedback(ux, o, 'second-person', actor='ou_engineer_b')
    feedback(ux, o, 'A2-after-other-person')
    assert len(am.items.history(o['item_id'])) == 4 and len(api.sent) == n + 8
    assert am.items.get(o['item_id'])['decision_version'] == 1


@pytest.mark.parametrize('progress', ['上述计划已取消，新的测试日期另行确定。',
    '排期以评审后的通知为准。', '昨日公布的安排不再适用。'])
def test_F02_schedule_preserves_cross_field_dependency(ux, tmp_path, progress):
    ux[-1].values[1][2] = '计划2026-11-06完成测试。'
    ux[-1].values[1][4] = progress
    provider = Provider([]); ai = QwenGroupAssistant(provider, tmp_path / 'ai')
    r = ai.reply('需求75什么时候完成测试？', [], None, lambda: parse_rows(ux[-1].values))
    assert progress in r.text or ('原文' in r.text and '2026-11-06' not in r.text)
    assert not provider.calls
    request(ux, '/project 需求75什么时候完成测试？', 1)
    assert progress in text(ux) or ('原文' in text(ux) and '2026-11-06' not in text(ux))


def test_F02_global_people_condition_is_not_omitted(ux):
    roles = '\n'.join(f'职责{n}：AR{n}合成人员，负责本项目第{n}类资料核对，不代表专业验收。' for n in range(100, 108))
    condition = '本表所有职责须经项目经理确认后生效。'
    ux[-1].values[1][5] = roles + condition
    request(ux, '/project 需求75谁负责', 1)
    assert condition in text(ux) or ('原文' in text(ux) and 'AR100' not in text(ux))


@pytest.mark.parametrize('entry', ['menu', '/briefing', '/changes'])
def test_F03_actual_entry_and_long_snapshot(ux, entry):
    request(ux, '/menu', 1); click(ux, 'projects')
    tail = '终末限定：只有合成型号可用，尚未验收。'
    complete = ('完整合成记录，前提仍有效。\n' * 900) + tail
    ux[-1].values[1][4] = complete
    if entry == 'menu':
        request(ux, '/menu', 2); click(ux, 'more'); click(ux, 'briefing')
    else: request(ux, entry, 2)
    snap = json.loads(latest(ux)['snapshot'])
    assert 'briefing_snapshot' in snap['data']
    assert len(snap['envelope']['summary']) < 400
    assert any(a.get('section') == 'changes' for a in snap['actions'].values())
    assert any(a.get('section') == 'todos' for a in snap['actions'].values()) == (entry != '/changes')
    assert not ux[2].rows('SELECT * FROM am_briefing_deliveries')
    click(ux, 'briefing_detail', overrides={'section': 'changes'})
    pieces = []
    for _ in range(30):
        snap = json.loads(latest(ux)['snapshot']); pieces.append(snap['envelope']['summary'])
        nxt = next((a for a in snap['actions'].values() if a['page'] == 'long_content' and a['offset'] > snap['data'].get('_long_index', 0)), None)
        if not nxt: break
        click(ux, 'long_content', overrides={'offset': nxt['offset']})
    assert tail in ''.join(pieces) and ''.join(pieces).count('完整合成记录') == 900
    assert not ux[2].rows('SELECT * FROM am_briefing_deliveries')


def test_F04_definitely_deleted_navigation_is_rebuilt_once(ux):
    request(ux, '/menu', 1); am, g, s, api, clock, _ = ux; old = latest(ux)['message_id']
    del api.messages[old]; original = api.update_card
    def deleted(row, guard):
        if row['update_message_id'] == old: raise SendRejected('UPDATE_TARGET_DELETED')
        return original(row, guard)
    api.update_card = deleted
    api.navigation_target_unavailable = lambda mid, row: mid == old
    request(ux, '/menu', 2); request(ux, '/menu', 3); request(ux, '/menu', 4)
    assert latest(ux)['message_id'] and latest(ux)['message_id'] != old
    assert sum(x['operation'] == 'create' for x in api.sent) == 2
    assert s.rows("SELECT * FROM outbox WHERE state='rejected'")


@pytest.mark.parametrize('mode', ['applied', 'not_applied', 'create_unknown'])
def test_F04_unknown_has_one_status_and_no_blind_republish(ux, mode):
    am, g, s, api, clock, _ = ux
    if mode != 'create_unknown': request(ux, '/menu', 1)
    original_send, original_update = api.send, api.update_card
    attempted = []
    def fail(row, guard):
        attempted.append(row['id'])
        if mode == 'applied': original_update(row, guard)
        raise SendUnknown('SYNTHETIC_TIMEOUT')
    if mode == 'create_unknown':
        api.send = fail; request(ux, '/menu', 1); api.send = original_send
    else:
        api.update_card = fail; click(ux, 'projects'); api.update_card = original_update
    unknown = s.rows("SELECT * FROM outbox WHERE state='unknown'")[0]
    request(ux, '/menu', 2); request(ux, '/menu', 3)
    if mode == 'applied':
        assert s.rows('SELECT state FROM outbox WHERE id=?', (unknown['id'],))[0]['state'] == 'sent'
        assert sum(x['operation'] == 'create' for x in api.sent) == 1
    else:
        assert '核对' in text(ux) and '不确定' in text(ux)
        assert sum(x['operation'] == 'create' for x in api.sent) == (1 if mode == 'create_unknown' else 2)
        assert len(attempted) == 1
        assert s.rows('SELECT state FROM outbox WHERE id=?', (unknown['id'],))[0]['state'] == 'unknown'
        assert any(a['page'] == 'reconcile_navigation' for a in json.loads(latest(ux)['snapshot'])['actions'].values())


@pytest.mark.parametrize('question,fields', [('进展和负责人分别是什么', ['项目进展','人员与职责']),
    ('进展和日期', ['项目进展','关键日期']), ('进展、日期、待办和负责人', ['项目进展','关键日期','待办','人员与职责']),
    ('谁负责', ['人员与职责'])])
def test_F05_explicit_fields_private_group_and_quote(ux, tmp_path, question, fields):
    values = ux[-1].values
    values[1][2:6] = ['预计11月测试。', '跟进报告。', '测试中，尚未验收。', 'AR1测试甲']
    provider = Provider([]); ai = QwenGroupAssistant(provider, tmp_path / 'ai')
    result = ai.reply('需求75的'+question, [], None, lambda: parse_rows(values))
    assert all(f in result.text for f in fields) and not provider.calls
    if len(fields) == 1: assert '项目进展' not in result.text
    request(ux, '/project 需求75的'+question, 1)
    assert all(f in text(ux) for f in fields)
    request(ux, '进展和负责人分别是什么', 2, parent_id=latest(ux)['message_id'])
    assert '测试中，尚未验收。' in text(ux) and 'AR1测试甲' in text(ux)


def test_F06_missing_eta_is_private_and_preserves_input(ux):
    o = occurrence(ux); am, g, s, api, clock, _ = ux; n = len(api.sent)
    result = feedback(ux, o, 'eta-missing', 'eta', '有效说明需要保留')
    assert result['state'] == 'failed' and not am.items.history(o['item_id'])
    assert len(api.sent) == n + 1 and api.sent[-1]['user'] == 'ou_engineer_a'
    assert api.sent[-1]['chat_type'] == 'p2p' and '日期' in text(ux)
    correction = s.rows("SELECT * FROM am_cards WHERE flow='feedback_correction' ORDER BY rowid DESC LIMIT 1")[0]
    assert '有效说明需要保留' in correction['snapshot']
    g.reminders.port.read_card = lambda mid: {'chat_id':'oc_engineer_dm','sender_id':g.config.bot_open_id,'deleted':False}
    when = (datetime.fromtimestamp(clock(), TZ)+timedelta(days=1)).strftime('%Y-%m-%d %H:%M +0800')
    # Correction submit goes through the private card callback; shared card unchanged.
    e = {'header': {'app_id': g.config.app_id,'tenant_key': g.config.tenant_key,'event_id': 'eta-corrected','event_type':'card.action.trigger'},
         'event': {'operator': {'open_id':'ou_engineer_a'},'context': {'open_chat_id':'oc_engineer_dm','open_message_id':correction['message_id']},
                   'action': {'value': {'flow':'am_self','nonce':correction['nonce'],'action':'submit'},'form_value': {'kind':'eta','eta':when,'detail':'有效说明需要保留'}}}}
    assert am.ingest(e) == (True, True); am.step(); drain(g)
    assert len(am.items.history(o['item_id'])) == 1
    assert len(api.sent) == n + 3
    e['header']['event_id'] = 'eta-corrected-doubleclick'
    assert am.ingest(e) == (True, True); am.step(); drain(g)
    assert len(api.sent) == n + 3
    feedback(ux, o, 'other-engineer', actor='ou_engineer_b')
    assert len(am.items.history(o['item_id'])) == 2


def test_F07_project_actions_preserve_search_position(ux):
    request(ux, '/menu', 1); click(ux, 'projects'); click(ux, 'search', form={'query':'需求75'})
    origin = json.loads(latest(ux)['snapshot'])['data']['origin']
    click(ux, 'project'); click(ux, 'project_actions'); click(ux, 'project'); click(ux, 'projects')
    snap = json.loads(latest(ux)['snapshot'])
    assert snap['fields']['query']['default'] == '需求75' and snap['data']['origin'] == origin


def test_F01_legacy_claim_and_atomic_retry(ux, monkeypatch):
    o=occurrence(ux);am,g,s,api,clock,_=ux
    feedback(ux,o,'legacy-first');n=len(api.sent)
    # Simulate the additive migration with a pre-existing UX2 operation journal.
    s.execute('DELETE FROM feedback_heads');s.execute('DELETE FROM feedback_claims')
    feedback(ux,o,'legacy-doubleclick')
    assert len(am.items.history(o['item_id']))==1 and len(api.sent)==n
    original=am.items.log
    def crash(*args,**kwargs):raise RuntimeError('SYNTHETIC_CRASH_BEFORE_COMMIT')
    monkeypatch.setattr(am.items,'log',crash)
    feedback(ux,o,'interrupted','submitted','材料初稿')
    assert len(am.items.history(o['item_id']))==1
    assert len(s.rows('SELECT * FROM feedback_claims'))==1
    assert '尚未确认' in text(ux) and len(api.sent)==n+1
    monkeypatch.setattr(am.items,'log',original)
    feedback(ux,o,'retry-after-interruption','submitted','材料初稿')
    assert len(am.items.history(o['item_id']))==2 and len(api.sent)==n+3


def test_F04_temporary_rejection_cannot_rebuild(ux):
    request(ux,'/menu',1);am,g,s,api,clock,_=ux;mid=latest(ux)['message_id']
    api.update_card=lambda *a: (_ for _ in ()).throw(SendRejected('TEMPORARY_DENIAL'))
    api.navigation_target_unavailable=lambda *a:False
    request(ux,'/menu',2);request(ux,'/menu',3)
    assert sum(x['operation']=='create' for x in api.sent)==2 and '被拒绝' in text(ux)
    assert s.rows('SELECT message_id FROM am_interactions WHERE kind=?',('navigation',))[0]['message_id']==mid


def test_F04_recovery_button_restores_only_after_exact_readback(ux):
    request(ux,'/menu',1);am,g,s,api,clock,_=ux;original=api.update_card
    api.update_card=lambda *a: (_ for _ in ()).throw(SendUnknown('SYNTHETIC_TIMEOUT'))
    click(ux,'projects');api.update_card=original
    unknown=s.rows("SELECT * FROM outbox WHERE state='unknown'")[0]
    delivery=s.rows('SELECT * FROM am_view_outputs WHERE outbox_id=?',(unknown['id'],))[0]
    request(ux,'/menu',2);click(ux,'reconcile_navigation')
    assert s.rows('SELECT state FROM outbox WHERE id=?',(unknown['id'],))[0]['state']=='unknown'
    api.messages[delivery['target_message']]=unknown['body']
    click(ux,'reconcile_navigation')
    assert '我的工作' in text(ux) and latest(ux)['message_id']==delivery['target_message']
    assert s.rows('SELECT state FROM outbox WHERE id=?',(unknown['id'],))[0]['state']=='sent'
    assert sum(x['operation']=='create' for x in api.sent)==2


def test_F06_unauthorized_actor_gets_no_private_prompt(ux):
    o=occurrence(ux);n=len(ux[3].sent)
    result=feedback(ux,o,'not-assigned','eta','私人内容',actor='ou_other')
    assert result['error']=='NOT_ASSIGNEE' and len(ux[3].sent)==n
    assert not ux[0].items.history(o['item_id'])


def test_request_timings_separate_read_render_and_readback(ux, monkeypatch):
    import time,threading
    am,g,s,api,clock,port=ux
    reader=port.read
    def slow_read():time.sleep(.012);return reader()
    monkeypatch.setattr(port,'read',slow_read)
    g.provider.lock=threading.Lock();g.provider.lock.acquire()
    try:
        request(ux,'需求75谁负责',1)
    finally:g.provider.lock.release()
    r=s.rows('SELECT * FROM am_request_timings WHERE event_id=?',('om1',))[0];stages=json.loads(r['stages'])
    assert r['model_busy']==1 and r['readback_verified']==1 and r['actionable'] is not None and r['finished'] is not None
    assert stages['source_read']['seconds']>=.012 and stages['source_read']['calls']==1
    assert all(k in stages for k in ('authorization','authorization_delivery','rendering','publish','readback'))
    assert not g.provider.prompts
