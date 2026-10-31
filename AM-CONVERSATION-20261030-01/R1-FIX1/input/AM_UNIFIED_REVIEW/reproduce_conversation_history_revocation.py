"""Narrow offline audit: real stores, fact revocation, projector and agent loop.

No pytest, external service, live model, transport or production configuration.
"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from _bootstrap import bootstrap
SOURCE_ROOT = bootstrap()

from am_info_sync.store import Store
from am_info_sync.runtime import InformationService
from am_info_sync.models import Source, Observation, Principal
from am_conversation.store import ConversationStore
from am_conversation.engine import ConversationAgent, RuntimeConfig
from am_conversation.types import AccessContext, ModelTurn, canonical
from am_conversation.tools import ToolRegistry
from am_conversation.capabilities import information


with tempfile.TemporaryDirectory(prefix='am-revocation-audit-') as td:
    root = Path(td)
    info_store = Store(root / 'info.sqlite3')
    service = InformationService(info_store)
    conv_store = ConversationStore(root / 'conversation.sqlite3')
    ctx = AccessContext('tenant', 'app', 'owner', 'private-chat',
                        allowed_project_ids=frozenset({'P1'}), is_owner=True)
    marker = 'AUDIT_ONLY_SOURCE_VALUE_83bd12'
    source = Source('private-doc', 'docx', 'document1', 'tenant', 'owner',
                    enabled=True, settings={'subject_id': 'P1'})
    info_store.register_source(source)
    obs = Observation(source.source_id, 'object1', 'version1', info_store.clock(), text=marker)
    info_store.record(obs)
    service.facts.process(obs, [{'source_id': source.source_id, 'object_id': obs.object_id,
        'version': obs.version, 'subject_id': 'P1', 'field': 'status',
        'value': marker, 'quote': marker, 'assertion_type': 'reported'}])

    def query(row, subject):
        result = service.query(subject, Principal(ctx.actor_id, ctx.tenant_id))
        result['version'] = canonical([[f['fact_id'], f['evidence']['version']] for f in result['facts']])
        return result

    # The unchanged trusted identity has P1 access before and after source deny.
    active = {'row': {'id': 'first', 'body': 'P1 当前资料'}}
    bridge = SimpleNamespace(authorize=lambda context, op, args: None,
        service=SimpleNamespace(information=SimpleNamespace(query=query)),
        _current=lambda context: active)
    registry = ToolRegistry()
    registry.prefetch = lambda context, text, event_id, focus: [{
        'id': 'P1', 'information': information(bridge, context,
            {'project_id': 'P1', 'limit': 3}, event_id)}]

    class ObservingModel:
        def __init__(self):
            self.prompts = []
        def complete(self, messages, tools, *, request_id=''):
            self.prompts.append(messages)
            # Deterministic stand-in demonstrates what input/output the host allows.
            previous = [m['content'] for m in messages if m['role'] == 'assistant']
            if previous:
                return ModelTurn(text=previous[-1])
            current = json.loads(messages[1]['content'].split('\n', 1)[1])
            fact = current['fresh_project_sources'][0]['information']['facts'][0]
            return ModelTurn(text='资料记录：' + fact['value'])

    model = ObservingModel()
    agent = ConversationAgent(model, conv_store, registry,
                              config=RuntimeConfig(prefetch_projects=True))
    first = agent.handle(ctx, 'first', 'P1 当前资料')
    assert marker in first.text
    assert len(service.query('P1', Principal('owner', 'tenant'))['facts']) == 1

    info_store.mark_source_error(source.source_id, 'PERMISSION_REVOKED', permission_denied=True)
    denied = query({}, 'P1')
    assert denied['facts'] == []
    active['row'] = {'id': 'second', 'body': '刚才资料再告诉我一次'}
    second = agent.handle(ctx, 'second', '刚才资料再告诉我一次')
    latest = model.prompts[-1]
    latest_current = json.loads(latest[1]['content'].split('\n', 1)[1])
    assert latest_current['fresh_project_sources'][0]['information']['facts'] == []
    assert any(marker in m['content'] for m in latest if m['role'] == 'assistant')
    assert marker in second.text
    print(json.dumps({
        'source_availability': info_store.source_status(source.source_id)['availability'],
        'current_information_fact_count': len(denied['facts']),
        'fresh_model_context_fact_count': len(latest_current['fresh_project_sources'][0]['information']['facts']),
        'old_source_value_in_model_history': True,
        'agent_accepted_reply_containing_old_source_value': marker in second.text,
        'agent_status': second.status,
        'live_model_or_transport': False}, ensure_ascii=False, indent=2))
    conv_store.close()
    info_store.close()
