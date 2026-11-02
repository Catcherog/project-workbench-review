"""Read-only independent platform and native verification for the approved test."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import sqlite3
import time

from fs_agent.config import Config
from fs_agent.feishu import Feishu
from fs_agent.reminder_feishu import ReminderPort
from fs_agent.business_port import BusinessPort
from lark_oapi.api.im.v1 import ListMessageRequest

TASK = Path(__file__).resolve().parents[1]
settings = json.loads((Path.home() / '.local/share/local-qwen-feishu/config.json').read_text())
config = Config.load(Path(settings['poc_config']))
api = Feishu(config)
reminder = ReminderPort(config, api.client)
port = BusinessPort(SimpleNamespace(config=config, api=api, reminders=SimpleNamespace(port=reminder)), None)
previews = json.loads((TASK / 'private/owner-previews.json').read_text())
summary = {'readback_only': True, 'at': time.time(), 'channels': [], 'new_send_calls_by_verifier': 0}
private = []
with sqlite3.connect((config.root / 'state/gateway.sqlite3').resolve().as_uri() + '?mode=ro', uri=True) as db:
    db.row_factory = sqlite3.Row
    for preview in previews['results']:
        if not preview['ok']:
            summary['channels'].append({'channel': preview['channel'], 'status': 'blocked_before_preview', 'reason': preview['error']})
            continue
        card = db.execute('SELECT * FROM am_cards WHERE nonce=?', (preview['nonce'],)).fetchone()
        intents = db.execute('SELECT * FROM followup_intents WHERE preview_id=?', (card['object_id'],)).fetchall()
        item = db.execute('SELECT * FROM action_items WHERE id=?', (preview['item_id'],)).fetchone()
        report = {'channel': preview['channel'], 'intent_count': len(intents), 'item_state': item['state'],
                  'item_not_business_closed': item['state'] != 'closed'}
        if not intents:
            report['status'] = 'no_approved_intent'
            summary['channels'].append(report)
            continue
        assert len(intents) == 1
        intent = intents[0]
        occurrences = db.execute('SELECT o.* FROM reminder_occurrences o JOIN followup_adoptions a ON a.occurrence_id=o.id WHERE a.intent_id=?', (intent['intent_id'],)).fetchall()
        assert len(occurrences) == 1
        occurrence = occurrences[0]
        report.update(intent_state=intent['state'], crossed_send_boundary=intent['crossed_send_boundary'],
                      native_state=occurrence['state'], native_attempts=occurrence['attempts'], native_error=occurrence['error'],
                      native_readback=occurrence['readback_state'], status='native_observed')
        if occurrence['message_id']:
            payload = json.loads(occurrence['payload'])
            message = reminder.read(occurrence['message_id'])
            exact = message['message_id'] == occurrence['message_id'] and port.verify(payload, message)
            assert exact, 'EXACT_MESSAGE_MISMATCH'
            report.update(status='exact_platform_message_verified', exact_body_target_mentions=True,
                          message_id_sha256=hashlib.sha256(message['message_id'].encode()).hexdigest(),
                          request_uuid_sha256=hashlib.sha256(occurrence['request_key'].encode()).hexdigest(),
                          sent_at=message['created_at'])
            private.append({'channel': preview['channel'], 'message': message, 'occurrence': dict(occurrence), 'intent': dict(intent)})
            if payload['target']['kind'] == 'group':
                group = payload['target']['payload']['group']['id']
                assert reminder.allowed(group)
                request = (ListMessageRequest.builder().container_id_type('chat').container_id(group)
                           .start_time(str(int(occurrence['send_started']) - 2))
                           .end_time(str(int(time.time()) + 1)).page_size(50).build())
                data = reminder._data(api.client.im.v1.message.list(request))
                matches = [m for m in data.items or [] if port.verify(payload, reminder._message(m))]
                report.update(bounded_window_complete=not data.has_more,
                              matching_messages_in_window=len(matches),
                              matched_only_exact_message=not data.has_more and len(matches) == 1 and matches[0].message_id == occurrence['message_id'])
            elif payload['target']['kind'] == 'recipient_p2p':
                # Only this explicitly requested owner test, in its already
                # verified bot DM. Unrelated messages are never saved.
                assert preview.get('owner_self_test') is True
                assert payload['target']['user'] == card['actor'] == config.owner
                assert payload['target']['chat'] == card['chat']
                assert 0 <= time.time() - occurrence['send_started'] < 86400
                request = (ListMessageRequest.builder().container_id_type('chat')
                           .container_id(payload['target']['chat'])
                           .start_time(str(int(occurrence['send_started']) - 2))
                           .end_time(str(int(time.time()) + 1)).page_size(50).build())
                data = reminder._data(api.client.im.v1.message.list(request))
                matches = [m for m in data.items or [] if port.verify(payload, reminder._message(m))]
                report.update(bounded_window_complete=not data.has_more,
                              matching_messages_in_window=len(matches),
                              matched_only_exact_message=not data.has_more and len(matches) == 1 and matches[0].message_id == occurrence['message_id'])
        feedback = db.execute('SELECT kind,applied FROM item_feedback WHERE item_id=?', (preview['item_id'],)).fetchall()
        report['feedback'] = [dict(row) for row in feedback]
        report['reply_links'] = db.execute('SELECT count(*) FROM followup_reply_links WHERE item_id=?', (preview['item_id'],)).fetchone()[0]
        summary['channels'].append(report)
(TASK / 'private/owner-send-readback.json').write_text(json.dumps(private, ensure_ascii=False, indent=2) + '\n')
(TASK / 'private/owner-send-readback.json').chmod(0o600)
(TASK / 'evidence/owner-send-readback.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summary, ensure_ascii=False))
