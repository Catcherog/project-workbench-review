"""Recoverable event consumption and unique dispatch. No implicit network calls."""
from dataclasses import asdict
import json
import uuid

from ..models import Admission, ContractError, Event, dumps, key
from .contracts import Policy, business_fingerprint
from .information import Information
from . import routing, storage
from .lifecycle import Lifecycle
from .boundary import ToolBoundary
from .cutover import Cutover


class Harness(Lifecycle, ToolBoundary, Cutover):
    def __init__(self, store, config, *, classifier=None, adapters=None):
        config.validate()
        self.store, self.config = store, config
        self.classifier = classifier
        self.adapters = dict(adapters or {})
        storage.initialize(store)
        self.information = Information(store, config)
        with store.transaction() as db:
            tenant = db.execute("SELECT value FROM gw_meta WHERE key='tenant_id'").fetchone()
            if tenant and tenant[0] != config.tenant_id:
                raise ContractError('database belongs to another tenant')
            db.execute("INSERT OR IGNORE INTO gw_meta VALUES('tenant_id',?)", (config.tenant_id,))

    def task(self, task_id, db=None):
        sql = 'SELECT * FROM h1_tasks WHERE task_id=?'
        row = db.execute(sql, (task_id,)).fetchone() if db else self.store.one(sql, (task_id,))
        if not row:
            raise ContractError('unknown task')
        return dict(row)

    def ingest(self, event, policy=None, *, cursor=None, coverage=None):
        """Host has checked collection scope. Cursor and pending responsibility commit together."""
        event.validate()
        if event.tenant_id != self.config.tenant_id:
            raise ContractError('tenant mismatch')
        if policy:
            policy.validate()
            if event.chat_id not in policy.source_chats:
                raise ContractError('request source outside authorization')
            expected = self.config.owner_chat_id if event.channel == 'personal_dm' else event.chat_id
            if policy.reply_target != expected:
                raise ContractError('reply target requires a separately authorized operation')
            if event.channel == 'personal_dm' and policy.principal != self.config.owner_id:
                raise ContractError('passive assistance must act for the owner')
            if event.channel != 'personal_dm' and policy.principal != event.sender_id:
                raise ContractError('requester principal mismatch')
        accepted = bool(policy and not policy.revoked and not event.is_self and not event.is_deleted and
                        event.direction == 'inbound' and event.kind == 'message' and
                        (event.channel in {'bot_dm', 'personal_dm'} or self.config.bot_id in event.mentions))
        with self.store.transaction() as db:
            prior = db.execute('SELECT version,event_json,version_time FROM gw_items WHERE item_id=?',(event.item_id,)).fetchone()
            admission = self.store.ingest_in_tx(db, event)
            if prior and not admission.changed and event.revision and event.version_time >= prior['version_time']:
                previous = json.loads(prior['event_json'])
                if event.revision != previous.get('revision'):
                    # A real source revision can change attachments/ACL metadata without
                    # changing message text. Preserve the old immutable evidence version.
                    version=prior['version']+1
                    db.execute('UPDATE gw_item_versions SET event_json=? WHERE item_id=? AND version=?',
                               (prior['event_json'],event.item_id,prior['version']))
                    db.execute('UPDATE gw_items SET version=?,event_json=? WHERE item_id=?',
                               (version,dumps(event.to_dict()),event.item_id))
                    db.execute('INSERT INTO gw_item_versions VALUES(?,?,?,?)',
                               (event.item_id,version,dumps(event.to_dict()),event.content_hash))
                    admission=Admission(event.item_id,False,True,admission.handled)
            row = db.execute('SELECT version FROM gw_items WHERE item_id=?', (event.item_id,)).fetchone()
            if admission.changed:
                self.information.invalidate(event.item_id, db)
                db.execute("""INSERT INTO h1_inbox(item_id,version,policy_json,state,accepted,created)
                    VALUES(?,?,?,'pending',?,?) ON CONFLICT(item_id) DO UPDATE SET
                    version=excluded.version,policy_json=excluded.policy_json,state='pending',
                    token='',lease_until=NULL,accepted=excluded.accepted""",
                           (event.item_id, row['version'], policy.json() if policy else '{}', int(accepted), self.store.clock()))
            elif not db.execute('SELECT 1 FROM h1_inbox WHERE item_id=?', (event.item_id,)).fetchone():
                # Historical records imported from the existing store also get a durable disposition.
                db.execute("INSERT INTO h1_inbox VALUES(?,?,?,'pending','',NULL,?,?)",
                           (event.item_id, row['version'], policy.json() if policy else '{}', int(accepted), self.store.clock()))
            if cursor is not None:
                db.execute("""INSERT INTO h1_sync VALUES(?,?,'saved','',?,?) ON CONFLICT(source) DO UPDATE SET
                    cursor=excluded.cursor,state='saved',detail='',coverage=excluded.coverage,updated=excluded.updated""",
                           (event.chat_id, dumps(cursor), dumps(coverage or {'history': 'not_verified'}), self.store.clock()))
            return Admission(admission.item_id, admission.inserted, admission.changed, accepted)

    def route_one(self):
        now = self.store.clock()
        with self.store.transaction() as db:
            db.execute("UPDATE h1_inbox SET state='pending',token='' WHERE state='routing' AND lease_until<?", (now,))
            row = db.execute("SELECT * FROM h1_inbox WHERE state='pending' ORDER BY created,item_id LIMIT 1").fetchone()
            if not row:
                return None
            pending = dict(row)
            token = uuid.uuid4().hex
            db.execute("UPDATE h1_inbox SET state='routing',token=?,lease_until=? WHERE item_id=?",
                       (token, now + self.config.classification_budget_seconds + 5, row['item_id']))
            event = self.store.get_event({'item_id': row['item_id'], 'version': row['version']}, db)
        route, error = None, ''
        if pending['accepted'] and not event.is_deleted:
            route = routing.rules(event.body, passive=event.channel == 'personal_dm')
            if route is None:
                try:
                    if self.classifier is None:
                        raise ContractError('classifier_unconfigured')
                    budget = min(self.config.classification_budget_seconds,
                                 pending['created'] + self.config.dispatch_deadline_seconds - self.store.clock()
                                 - self.config.dispatch_reserve_seconds)
                    if budget <= 0:
                        raise TimeoutError('request_deadline')
                    route = routing.validate(self.classifier.classify(event, budget))
                except Exception as exc:
                    error = type(exc).__name__  # no remote body/token in error text
                    route = routing.result('unknown', 'unknown', reason='classification_error')
        with self.store.transaction() as db:
            current = db.execute('SELECT * FROM h1_inbox WHERE item_id=?', (pending['item_id'],)).fetchone()
            if current['token'] != token or current['version'] != pending['version']:
                return None  # changed while the pure classifier was running
            tid = 'task_' + key(event.item_id)[:32]
            old = db.execute('SELECT * FROM h1_tasks WHERE task_id=?', (tid,)).fetchone()
            if route is None:
                if old:
                    self._stop_for_source(db, dict(old))
                db.execute("UPDATE h1_inbox SET state='done',lease_until=NULL WHERE item_id=?", (event.item_id,))
                return {'item_id': event.item_id, 'disposition': 'collection_only'}
            if old and old['business_id']:
                # Any post-dispatch edit is a request revision, never another effect.
                self._stop_for_source(db, dict(old))
                db.execute("INSERT OR IGNORE INTO h1_revisions VALUES(?,?,?,?,?)",
                           (tid, pending['version'], dumps(event.to_dict()), 'source_changed_after_dispatch', self.store.clock()))
            else:
                self._save_routed(db, tid, event, Policy.parse(pending['policy_json']), route, error,
                                  pending['version'], pending['created'], old)
            db.execute("UPDATE h1_inbox SET state='done',lease_until=NULL WHERE item_id=?", (event.item_id,))
            return self.task(tid, db)

    def _stop_for_source(self, db, task):
        db.execute("UPDATE h1_tasks SET last_error='source_changed',verification_state='insufficient' WHERE task_id=?", (task['task_id'],))
        db.execute("UPDATE h1_dispatch SET state='source_changed' WHERE task_id=? AND state='pending'", (task['task_id'],))
        # Active executions retain their scope until an actual stopped receipt.

    def _save_routed(self, db, tid, event, policy, route, error, revision, created, old=None):
        if old:
            policy = Policy.parse(old['policy_json'])
        intent = route['intent']
        state = 'classification_error' if error else route['decision']
        if route['reason_code'] == 'passive_nonwork':
            state = 'out_of_scope'
        if state == 'matched':
            state = 'resolved'
        capability = self.config.capabilities.get(intent)
        scope = capability.execution_scope if capability else ''
        if route['secondary_intents']:
            state = 'capability_unavailable'  # no registered executor handles the whole compound request
        elif state == 'resolved' and capability and not capability.available:
            state = 'capability_unavailable'
        if state == 'resolved' and intent == 'context.supplement':
            if event.sender_id != self.config.owner_id or not policy.allow_supplement:
                state = 'authorization_required'
            elif len(event.project_ids) != 1 or event.project_ids[0] not in policy.projects:
                state = 'needs_clarification'
                route['missing_fields'] = ['project_id']
                route['clarification_question'] = '请指定补充信息所属项目。'
        deadline = old['deadline'] if old else created + self.config.dispatch_deadline_seconds
        dispatch = 'pending' if state == 'resolved' and intent != 'context.supplement' else 'none'
        if dispatch == 'pending':
            count = db.execute("SELECT count(*) FROM h1_tasks WHERE scope=? AND dispatch_state IN ('pending','dispatching','accepted','unknown')", (scope,)).fetchone()[0]
            if count >= self.config.queue_limit:
                state, dispatch = 'queue_full', 'none'
        stamps = json.loads(old['stamps']) if old else {'t_m': event.original_time, 't_i': created}
        stamps['t_r'] = self.store.clock()
        request = event.to_dict()
        values = (tid, event.item_id, revision, dumps(request), policy.json(), dumps(route), intent, state,
                  dispatch, 'queued', 'not_delivered', 'pending', scope, deadline,
                  created + self.config.execution_deadline_seconds, dumps(stamps), error, created)
        db.execute("""INSERT INTO h1_tasks(task_id,item_id,revision,request_json,policy_json,route_json,intent,
          route_state,dispatch_state,execution_state,delivery_state,verification_state,scope,deadline,
          execution_deadline,stamps,last_error,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(task_id) DO UPDATE SET revision=excluded.revision,request_json=excluded.request_json,
          policy_json=excluded.policy_json,route_json=excluded.route_json,intent=excluded.intent,
          route_state=excluded.route_state,dispatch_state=excluded.dispatch_state,scope=excluded.scope,
          stamps=excluded.stamps,last_error=excluded.last_error""", values)
        db.execute('INSERT OR REPLACE INTO h1_revisions VALUES(?,?,?,?,?)',
                   (tid, revision, dumps(request), 'routed', self.store.clock()))
        db.execute('UPDATE h1_tasks SET source_version=(SELECT version FROM gw_items WHERE item_id=?) WHERE task_id=?',
                   (event.item_id,tid))
        if dispatch == 'pending':
            db.execute("INSERT OR REPLACE INTO h1_dispatch VALUES(?,'pending','')", (tid,))
        if state == 'resolved' and intent == 'context.supplement':
            info = self.information.append(project=event.project_ids[0], nature='pending_requirement',
                body=event.body, sources=[{'item_id': event.item_id, 'version': db.execute('SELECT version FROM gw_items WHERE item_id=?',(event.item_id,)).fetchone()[0]}],
                readers=[policy.principal], audiences=[policy.reply_target], operation_id=tid, db=db)
            db.execute("UPDATE h1_tasks SET execution_state='succeeded',result_json=?,verification_state='sufficient',business_id=? WHERE task_id=?",
                       (dumps({'recorded': info['info_id'], 'minimum_visible_version': info['seq'],
                               'formal_business_changed': False}), 'op_' + key(tid,'supplement')[:32], tid))

    def update_policy(self, task_id, policy):
        policy.validate()
        with self.store.transaction() as db:
            row = self.task(task_id, db)
            old = Policy.parse(row['policy_json'])
            if policy.version <= old.version or (policy.principal, policy.reply_target) != (old.principal, old.reply_target):
                raise ContractError('policy revision cannot change business identity')
            if not set(policy.source_chats) <= set(old.source_chats) or not set(policy.projects) <= set(old.projects):
                raise ContractError('scope expansion requires a new authorization review')
            if (policy.allow_reply and not old.allow_reply) or (policy.allow_supplement and not old.allow_supplement):
                raise ContractError('policy refresh can only narrow authority')
            db.execute('UPDATE h1_tasks SET policy_json=? WHERE task_id=?', (policy.json(), task_id))

    def claim(self, *, require_cutover=False):
        now = self.store.clock()
        with self.store.transaction() as db:
            for row in db.execute("SELECT task_id FROM h1_tasks WHERE dispatch_state='pending' AND deadline<=?", (now,)).fetchall():
                db.execute("UPDATE h1_tasks SET dispatch_state='expired',last_error='not_executed_deadline' WHERE task_id=?", (row[0],))
                db.execute("UPDATE h1_dispatch SET state='expired' WHERE task_id=?", (row[0],))
            row = db.execute("""SELECT t.* FROM h1_tasks t JOIN h1_dispatch d USING(task_id)
                WHERE d.state='pending' AND t.dispatch_state='pending' AND t.deadline>?
                AND NOT EXISTS(SELECT 1 FROM h1_sessions s WHERE s.scope=t.scope AND s.state!='free')
                AND NOT EXISTS(SELECT 1 FROM h1_cutover c WHERE c.scope=t.scope AND c.state!='harness')
                AND (?=0 OR EXISTS(SELECT 1 FROM h1_cutover c WHERE c.scope=t.scope AND c.state='harness'))
                ORDER BY t.created,t.task_id LIMIT 1""", (now,int(require_cutover))).fetchone()
            if not row:
                return None
            task = dict(row)
            policy = Policy.parse(task['policy_json'])
            if policy.revoked:
                db.execute("UPDATE h1_tasks SET dispatch_state='revoked' WHERE task_id=?", (task['task_id'],))
                db.execute("UPDATE h1_dispatch SET state='revoked' WHERE task_id=?", (task['task_id'],))
                return None
            event = Event.from_dict(json.loads(task['request_json']))
            source = db.execute('SELECT version,is_deleted FROM gw_items WHERE item_id=?',(task['item_id'],)).fetchone()
            if source['is_deleted'] or source['version'] != task['source_version'] or event.chat_id not in policy.source_chats:
                self._stop_for_source(db,task)
                db.execute("UPDATE h1_tasks SET dispatch_state='source_changed' WHERE task_id=?",(task['task_id'],))
                return None
            context = self.information.snapshot(policy, db=db)
            fingerprint = business_fingerprint(text=event.body, intent=task['intent'], principal=policy.principal,
                reply_target=policy.reply_target, attachments=event.attachments, inputs={'project_ids': event.project_ids})
            if task['fingerprint'] and task['fingerprint'] != fingerprint:
                raise ContractError('same operation different business inputs')
            session = db.execute('SELECT generation FROM h1_sessions WHERE scope=?', (task['scope'],)).fetchone()
            generation = session[0] + 1 if session else 1
            attempt = uuid.uuid4().hex
            operation = task['business_id'] or 'op_' + key(task['task_id'], 'primary')[:32]
            db.execute("INSERT OR REPLACE INTO h1_sessions VALUES(?,?,?,'held')", (task['scope'], generation, task['task_id']))
            db.execute("""UPDATE h1_tasks SET dispatch_state='dispatching',business_id=?,fingerprint=?,
                generation=?,attempt=?,context_json=?,lease_until=? WHERE task_id=?""",
                       (operation, fingerprint, generation, attempt, dumps(context), now+self.config.lease_seconds, task['task_id']))
            db.execute("UPDATE h1_dispatch SET state='claimed',attempt=? WHERE task_id=?", (attempt, task['task_id']))
            return self.envelope(self.task(task['task_id'], db))

    def envelope(self, task):
        request, policy = json.loads(task['request_json']), Policy.parse(task['policy_json'])
        return {'schema_version': '1.0', 'identity': {'task_id': task['task_id'], 'request_revision': task['revision'],
                'business_operation_id': task['business_id'], 'idempotency_key': task['business_id'],
                'dispatch_attempt_id': task['attempt'], 'business_fingerprint': task['fingerprint']},
                'routing': {'intent': task['intent'], 'route_version': self.config.route_version,
                            'adapter': self.config.capabilities[task['intent']].adapter},
                'source': {k: request[k] for k in ('tenant_id','native_id','chat_id','thread_id','sender_id')},
                'payload': {'raw_text': request['body'], 'attachment_refs': request['attachments'],
                            'structured_inputs': {'project_ids': request['project_ids']}},
                'request_context': {'requester_id':policy.principal,'acting_principal':policy.principal,
                                    'authorization_ref':policy.authorization_ref},
                'policy': json.loads(policy.json()), 'context': json.loads(task['context_json'] or '{}'),
                'execution': {'scope': task['scope'], 'generation': task['generation'],
                              'accept_deadline': task['deadline'], 'completion_deadline': task['execution_deadline']},
                'output': {'reply_target': policy.reply_target,
                           'reply_binding': request['native_id'] if request['chat_id'] == policy.reply_target else None}}

    def expire(self):
        with self.store.transaction() as db:
            now = self.store.clock()
            rows = db.execute("""SELECT task_id FROM h1_tasks WHERE dispatch_state IN ('dispatching','accepted')
                AND execution_state NOT IN ('succeeded','failed','cancelled')
                AND (lease_until<? OR execution_deadline<?)""", (now, now)).fetchall()
            for row in rows:
                db.execute("UPDATE h1_tasks SET execution_state='unknown',last_error='execution_status_required' WHERE task_id=?", (row[0],))
            db.execute("UPDATE h1_effects SET state='unknown' WHERE state='sending' AND created<?", (now-self.config.lease_seconds,))
            return len(rows)  # session held; elapsed time is not proof of stopped execution

    def pending(self):
        return self.store.rows("""SELECT task_id,request_json,route_state,route_json,dispatch_state,
            execution_state,delivery_state,last_error FROM h1_tasks
            WHERE route_state!='resolved' OR execution_state='unknown' ORDER BY created""")

    def resume(self, task_id, actor, *, supplement='', intent=None, ignore=False):
        with self.store.transaction() as db:
            task = self.task(task_id, db)
            event = Event.from_dict(json.loads(task['request_json']))
            if actor not in {event.sender_id, self.config.owner_id}:
                raise ContractError('supplement actor mismatch')
            if task['business_id'] or task['execution_state'] == 'succeeded':
                raise ContractError('existing effect requires reconciliation, not restart')
            if ignore:
                db.execute("UPDATE h1_tasks SET route_state='ignored',dispatch_state='none' WHERE task_id=?", (task_id,))
                db.execute("DELETE FROM h1_dispatch WHERE task_id=?", (task_id,))
                return self.task(task_id, db)
            if task['route_state'] == 'classification_error' and intent is not None:
                raise ContractError('classification outage needs technical retry')
            raw = event.to_dict()
            raw['body'] += ('\n补充：' + supplement) if supplement else ''
            event = Event.from_dict(raw)
            route = routing.result(intent, reason='manual_selection') if intent else routing.rules(event.body)
            if route is None:
                raise ContractError('still needs routing clarification')
            routing.validate(route)
            # User choice never grants read, write or delivery permissions.
            self._save_routed(db, task_id, event, Policy.parse(task['policy_json']), route, '',
                              task['revision']+1, task['created'], task)
            return self.task(task_id, db)

    def retry_classification(self, task_id):
        with self.store.transaction() as db:
            task = self.task(task_id, db)
            if task['route_state'] != 'classification_error' or task['business_id']:
                raise ContractError('not a classification recovery')
            db.execute("UPDATE h1_inbox SET state='pending',token='' WHERE item_id=?", (task['item_id'],))
