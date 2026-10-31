"""Projection beside the original outbox, never a second dispatcher."""
import json
from am_outcome.types import fingerprint, encode, OutcomeEnvelope, VERSION as OUTCOME_VERSION
from am_conversation.types import ConversationError
from .schema import VERSION


class GatewayProjection:
    def __init__(self, store):
        self.store = store
        with store.tx() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS am_response_outbox_v2 (
                outbox_id TEXT PRIMARY KEY, presentation_id TEXT NOT NULL,
                origin_event_id TEXT NOT NULL, scope_key TEXT NOT NULL,
                semantic_hash TEXT NOT NULL, rendered_hash TEXT NOT NULL,
                data_json TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
                message_id TEXT, verified_at REAL, expires REAL NOT NULL)''')

            # Original outbox remains the sole execution authority. A trigger also
            # covers rejection/unknown/restart paths that do not call receipt().
            conn.execute("""CREATE TRIGGER IF NOT EXISTS am_response_outbox_state_v2
                AFTER UPDATE OF state ON outbox BEGIN
                UPDATE am_response_outbox_v2 SET state=CASE
                  WHEN NEW.state='pending' THEN 'queued'
                  WHEN NEW.state='sent' AND state='verified' AND message_id=NEW.message_id THEN 'verified'
                  ELSE NEW.state END WHERE outbox_id=NEW.id; END""")
            conn.execute("""UPDATE am_response_outbox_v2 SET state=(SELECT CASE
                WHEN o.state='pending' THEN 'queued'
                WHEN o.state='sent' AND am_response_outbox_v2.state='verified' AND o.message_id=am_response_outbox_v2.message_id THEN 'verified'
                ELSE o.state END FROM outbox o WHERE o.id=outbox_id)
                WHERE EXISTS(SELECT 1 FROM outbox o WHERE o.id=outbox_id)""")
            conn.execute("""CREATE VIEW IF NOT EXISTS am_response_delivery_v2 AS
                SELECT p.*, o.state AS authoritative_state, o.error AS delivery_error
                FROM am_response_outbox_v2 p JOIN outbox o ON o.id=p.outbox_id""")

    def bind(self, conn, row, outbox_id, kind, body, artifact):
        scope = [row['tenant'], row['app'], row['user'], row['chat'],
                 (row.get('_source_meta') or {}).get('thread', '')]
        origin = row.get('message_id') or row.get('id')
        if not origin: raise ConversationError('PRESENTATION_ORIGIN_REQUIRED')
        rendered = fingerprint({'kind': kind, 'body': body, 'artifact': artifact})
        prepared = row.get('_response_v2')
        if prepared is not None:
            if prepared['outcome']['binding']['origin_event_id'] != origin:
                raise ConversationError('PRESENTATION_ORIGIN_MISMATCH')
            presentation_id, semantic = prepared['presentation_id'], prepared['semantic_hash']
            data = {k: prepared[k] for k in ('schema_version', 'selected_source', 'reason', 'eligible',
                'attempted', 'accepted', 'adopted', 'business_completion', 'naturalness', 'mode',
                'task_model_calls', 'task_repair_calls', 'presentation_calls', 'prepare_ms', 'total_ms')}
            data.update(families=prepared['outcome']['families'],
                        dependencies=prepared['outcome']['dependencies'],
                        engine_event_id=prepared['outcome']['binding']['engine_event_id'])
        else:
            # Explicit protected compatibility: exact payload retained; no
            # guessed business completion or fabricated generation success.
            presentation_id = fingerprint([scope, origin, outbox_id, 'protected'])
            semantic = rendered
            data = {'schema_version': VERSION, 'selected_source': 'legacy_protected',
                    'families': [row.get('_response_family', 'legacy')],
                    'business_completion': row.get('_response_completion', 'unclassified'),
                    'origin_kind': row.get('_response_kind', row.get('kind', 'unknown')),
                    'object_id': row.get('_response_object'), 'object_version': row.get('_response_version'),
                    'payload_binding': row.get('_response_payload_hash'), 'required_block': rendered,
                    'eligible': False, 'attempted': False, 'accepted': False, 'adopted': False,
                    'presentation_calls': 0, 'naturalness': 'not_evaluated'}
            data['outcome'] = OutcomeEnvelope.freeze({
                'schema_version': OUTCOME_VERSION,
                'binding': {'kind': 'event', 'scope': scope, 'origin_event_id': origin,
                            'engine_event_id': origin, 'purpose_id': outbox_id},
                'intent': {'goal_set_complete': False}, 'families': data['families'],
                'completion': 'blocked', 'work_units': [], 'claims': [],
                'protected_blocks': [{'id': 'legacy-payload', 'role': 'legacy', 'required': True,
                                      'payload_ref': outbox_id, 'payload_hash': rendered}],
                'pending_actions': [], 'dependencies': {'global_source_access_version': row.get('_source_access_version'),
                                                        'complete': False, 'policy': 'original_guards'},
                'allowed_next_steps': [], 'expires_at': row['expires']}).data
        conn.execute('INSERT INTO am_response_outbox_v2(outbox_id,presentation_id,origin_event_id,scope_key,semantic_hash,rendered_hash,data_json,expires) VALUES(?,?,?,?,?,?,?,?)',
                     (outbox_id, presentation_id, origin, fingerprint(scope), semantic, rendered,
                      encode(data), min(row['expires'], prepared['expires_at'] if prepared else row['expires'])))

    def receipt(self, conn, row, message_id, *, verified=False):
        saved = conn.execute('SELECT * FROM am_response_outbox_v2 WHERE outbox_id=?', (row['id'],)).fetchone()
        out = conn.execute('SELECT * FROM outbox WHERE id=?', (row['id'],)).fetchone()
        if saved is None or out is None: return False
        actual = fingerprint({'kind': out['kind'], 'body': out['body'], 'artifact': out['artifact']})
        if (actual != saved['rendered_hash'] or out['state'] != 'sent' or out['message_id'] != message_id
                or saved['expires'] <= self.store.clock()): return False
        conn.execute('UPDATE am_response_outbox_v2 SET state=CASE WHEN ? THEN \'verified\' ELSE CASE WHEN state=\'verified\' THEN state ELSE \'sent\' END END,message_id=?,verified_at=CASE WHEN ? THEN ? ELSE verified_at END WHERE outbox_id=?',
                     (verified, message_id, verified, self.store.clock(), row['id']))
        return True

    def cleanup(self, conn, now):
        conn.execute('DELETE FROM am_response_outbox_v2 WHERE expires<=?', (now,))
