import json
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock

from _bootstrap import bootstrap
ROOT = bootstrap()
from am_info_sync.models import Observation, Principal, Page
from am_info_sync.store import Store
from am_info_sync.runtime import InformationService
from am_info_sync.catalog import EntityCatalog
from info_sources import Discovery

store = Store(':memory:')
catalog = EntityCatalog(store)
catalog.register('A', 'Project A')
catalog.register('B', 'Project B')
extract_calls = []
def extractor(obs):
    subjects = catalog.context_for(obs)['allowed_subject_ids']
    extract_calls.append(subjects)
    # Models receive the actual limited subject list; create only allowed facts.
    return [{'source_id': obs.source_id, 'object_id': obs.object_id, 'version': obs.version,
             'subject_id': subject, 'field': 'progress', 'value': subject + ' ready',
             'quote': subject + ' ready', 'assertion_type': 'reported'} for subject in subjects]
adapter = Mock()
service = InformationService(store, {'docx': adapter}, extractor)
d = Discovery.__new__(Discovery)
d.h = NS(store=store, catalog=catalog, _register=store.register_source, start_ms=0,
         am=NS(owner='owner', g=NS(config=NS(tenant_key='tenant'))))
d.user = Mock()
d.user.call.return_value = {'token': 'samefile', 'type': 'docx', 'title': 'Shared Project File'}
with store.transaction() as db:
    db.execute('CREATE TABLE host_discovery_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
url = 'https://example.feishu.cn/docx/samefile'
d.register_document(url, ['A'])
obs = Observation('docx:samefile', 'body', 'v1', store.clock(), text='A ready; B ready')
adapter.fetch_page.return_value = Page((obs,), time_coverage=False)
service.sync_engine.run_source(obs.source_id)
first = service.analyze_once()
d.register_document(url, ['B'])
service.sync_engine.run_source(obs.source_id)
second = service.analyze_once()
result = service.query('B', Principal('owner','tenant'))
out = {'current_subject_scope': catalog.context_for(obs)['allowed_subject_ids'],
       'extractor_subject_scopes_seen': extract_calls,
       'first_analyze_status': first['status'], 'second_analyze_result': second,
       'project_B_fact_count': len(result['facts']),
       'project_B_processing_pending': result['coverage']['processing_pending'],
       'project_B_needs_refresh_or_review': result['coverage']['needs_refresh_or_review']}
assert out['current_subject_scope'] == ['A','B']
assert out['extractor_subject_scopes_seen'] == [['A']]
assert out['project_B_fact_count'] == 0
assert second is None
print(json.dumps(out, ensure_ascii=False, indent=2))
store.close()
