"""Resume one genuine, still-valid callback after a pre-approval read failure.

Explicit maintenance action for this acceptance run. Does not create an event,
approve an intent, alter any body, extend expiry or call a sending API. The
original consumer must revalidate the preserved event and current preview.
"""
from pathlib import Path
import hashlib
import json
import sqlite3
import time

TASK = Path(__file__).resolve().parents[1]
cfg = json.loads((Path.home() / '.local/share/local-qwen-feishu/config.json').read_text())
poc = json.loads(Path(cfg['poc_config']).read_text())
dbpath = Path(poc['service']['root_directory']) / 'state/gateway.sqlite3'
observed = json.loads((TASK / 'private/failed-confirmation-inbox.json').read_text())
assert len(observed) == 1
old = observed[0]
assert old['kind'] == 'card' and old['state'] == 'failed' and old['error'] == 'REMINDER_PLATFORM_READ_2200'
value = json.loads(old['body'])
assert value['value']['flow'] == 'am_self' and value['value']['action'] == 'confirm_send_once'
with sqlite3.connect(dbpath) as conn:
    conn.row_factory = sqlite3.Row
    conn.execute('BEGIN IMMEDIATE')
    event = conn.execute('SELECT * FROM am_inbox WHERE id=?', (old['id'],)).fetchone()
    assert dict(event) == old, 'EVENT_CHANGED'
    card = conn.execute('SELECT * FROM am_cards WHERE nonce=?', (value['value']['nonce'],)).fetchone()
    assert card and card['flow'] == 'followup'
    assert (card['actor'], card['chat'], card['message_id']) == (event['user'], event['chat'], value['source_message'])
    assert time.time() < min(card['expires'], event['expires']), 'EXPIRED_APPROVAL_CANNOT_BE_RETRIED'
    binding = conn.execute('SELECT * FROM followup_bindings WHERE preview_id=?', (card['object_id'],)).fetchone()
    assert binding and not binding['invalidated']
    assert conn.execute('SELECT count(*) FROM followup_intents WHERE preview_id=?', (card['object_id'],)).fetchone()[0] == 0
    assert not conn.execute("SELECT 1 FROM followup_audit WHERE object_id=? AND event='recorded_callback_read_retry'", (event['id'],)).fetchone()
    changed = conn.execute("UPDATE am_inbox SET state='received',error=NULL WHERE id=? AND state='failed' AND error='REMINDER_PLATFORM_READ_2200' AND body=?",
                           (event['id'], old['body'])).rowcount
    assert changed == 1
    conn.execute('INSERT INTO followup_audit(tenant_id,object_id,event,detail,recorded_at) VALUES(?,?,?,?,?)',
                 (event['tenant'], event['id'], 'recorded_callback_read_retry', 'pre_approval_platform_2200; original_event_preserved', time.time()))
    conn.commit()
result = {'original_event_sha256': hashlib.sha256(old['id'].encode()).hexdigest(),
          'original_body_sha256': hashlib.sha256(old['body'].encode()).hexdigest(),
          'original_created_at': old['created'], 'preview_expires_at': card['expires'],
          'retried_at': time.time(), 'prior_error': old['error'],
          'prior_intents': 0, 'original_event_and_body_preserved': True,
          'new_callback_created': False, 'expiry_extended': False, 'direct_send_calls': 0,
          'scope': 'one genuine callback requeued once; original consumer rechecks all gates'}
(TASK / 'evidence/recorded-confirmation-retry.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
