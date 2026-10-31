import json
import sys
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

from _bootstrap import bootstrap
ROOT = bootstrap()
from am_info_sync.models import Source, Principal, Page, PermissionDenied, RetryableError
from am_info_sync.store import Store
from am_info_sync.facts import FactEngine
from am_info_sync.sync import SyncEngine
from info_sources import Discovery, record_observation

def permission_repro():
    store = Store(':memory:')
    source = Source('private-doc', 'workitem_snapshot', 'r', 'tenant', 'owner', enabled=True,
                    settings={'subject_id': 'project', 'fact_mappings': {'system_record': {
                        'value_path': ['record'], 'quote_path': ['quote']}}})
    store.register_source(source)
    obs = record_observation(source, 'record', {'status': 'private evidence'}, store.clock())
    adapter = Mock()
    adapter.fetch_page.return_value = Page((obs,), time_coverage=False)
    sync = SyncEngine(store, {'workitem_snapshot': adapter})
    sync.run_source(source.source_id)
    facts = FactEngine(store)
    facts.process(store.get_observation(obs.source_id, obs.object_id, obs.version), [])
    principal = Principal('owner', 'tenant')
    samples = []
    def sample(label):
        result = facts.query('project', principal)
        samples.append({'state': label, 'availability': store.source_status(source.source_id)['availability'],
                        'visible_fact_count': len(result['facts']),
                        'stale': [f['stale'] for f in result['facts']]})
    sample('initial_success')
    adapter.fetch_page.side_effect = PermissionDenied('access revoked')
    try: sync.run_source(source.source_id)
    except PermissionDenied: pass
    sample('permission_denied')
    adapter.fetch_page.side_effect = RetryableError('network timeout before access revalidation')
    try: sync.run_source(source.source_id)
    except RetryableError: pass
    sample('subsequent_timeout_without_success')
    store.close()
    assert [s['visible_fact_count'] for s in samples] == [1, 0, 1]
    return samples

def queue_repro():
    store = Store(':memory:')
    parent = Source('parent', 'workitem_snapshot', '100', 'tenant', 'owner', enabled=True,
                    settings={'space': 'test', 'subject_id': 'project'})
    store.register_source(parent)
    with store.transaction() as db:
        db.execute('CREATE TABLE host_discovery_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    # Avoid Discovery.configure(), which installs real adapters, while exercising
    # exactly the frozen Discovery.child/resolve_child/step methods.
    d = Discovery.__new__(Discovery)
    calls = []
    def backend(args):
        identity = args[args.index('--work-item-id') + 1]
        calls.append(identity)
        if identity == '101':
            raise PermissionDenied('one inaccessible child')
        return {'work_item_attribute': {'work_item_id': '102',
                'work_item_type': {'key': 'deliverable-type', 'name': 'deliverable'}}}
    d.h = NS(store=store, business=NS(_run=backend), service=NS(pulse=Mock()),
             _register=store.register_source, start_ms=0,
             am=NS(owner='owner', g=NS(config=NS(tenant_key='tenant'))))
    d.state('metadata:deliverable-type', {'list': [], 'pagination': {'has_more': False}})
    now = time.time()
    d.last_approvals = d.last_projects = d.last_documents = d.last_search = now
    d.child(parent, '101', 'node')
    d.child(parent, '102', 'node')
    for _ in range(3): d.step()
    with store._lock:
        pending = [r[0] for r in store.conn.execute("SELECT key FROM host_discovery_state WHERE key LIKE 'child_pending:%' ORDER BY key")]
    assert calls == ['101', '101', '101']
    assert pending == ['child_pending:101', 'child_pending:102']
    out = {'step_runs': 3, 'backend_child_calls': list(calls), 'pending_after': pending,
           'healthy_second_child_ever_attempted': '102' in calls}
    # Local control: remove only the bad head and prove child 102 is otherwise healthy.
    with store.transaction() as db:
        db.execute("DELETE FROM host_discovery_state WHERE key='child_pending:101'")
    d.step()
    out['control_after_bad_head_removed'] = store.get_source('workitem:102').source_id
    store.close()
    return out

print(json.dumps({'permission_regression': permission_repro(), 'queue_head_blocking': queue_repro()}, ensure_ascii=False, indent=2))
