import json
from dataclasses import replace

from test_followup_native import native, service, am_rig, base_rig
from test_gateway import drain, event


def test_data_free_recovery_reopens_owner_work_view_through_real_callback(native):
    n = native
    row = dict(n.row, _source_access_version='old-source', _query_read=True,
               _query_grant=['*'], _snapshot_meta={'private': 'never-copy'},
               _view_version=88, _interaction='old-interaction')
    n.am.ux_error(row, 'SOURCE_ACCESS_CHANGED')
    n.reader.register_source(replace(n.source, enabled=False))
    drain(n.g)
    card = n.s.rows('SELECT * FROM am_cards ORDER BY rowid DESC LIMIT 1')[0]
    assert card['message_id']
    snapshot = json.loads(card['snapshot'])
    action = next(k for k, v in snapshot['actions'].items() if v['page'] == 'work')
    payload = {
        'header': {'app_id': n.g.config.app_id, 'tenant_key': n.g.config.tenant_key,
                   'event_id': 'independent-recovery-click', 'event_type': 'card.action.trigger'},
        'event': {'operator': {'open_id': n.am.owner},
                  'context': {'open_chat_id': n.row['chat'], 'open_message_id': card['message_id']},
                  'action': {'value': {'flow': 'am_self', 'nonce': card['nonce'], 'action': action}}}}
    assert n.am.ingest(payload) == (True, True)
    n.am.step()
    assert n.s.rows('SELECT state,error FROM am_inbox WHERE id=?',
                    ('independent-recovery-click',)) == [{'state': 'done', 'error': None}]
    new_card = n.s.rows('SELECT * FROM am_cards ORDER BY rowid DESC LIMIT 1')[0]
    output = n.s.rows('SELECT body FROM outbox WHERE id=?', (new_card['outbox_id'],))[0]['body']
    assert '我的跟进' in output
    assert 'never-copy' not in output
    assert not n.s.rows('SELECT * FROM followup_intents')
    assert not n.calls


def test_navigation_rejects_foreign_app_and_does_not_create_output(native):
    n = native
    incoming = event('我的跟进', number=9999, user=n.am.owner, chat=n.row['chat'])
    incoming['header']['app_id'] = 'foreign-app'
    assert n.am.ingest(incoming) == (False, False)
    assert not n.calls
