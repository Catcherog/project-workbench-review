"""Owner navigation and data-free recovery with original AM runtime classes.

SQLite and routing are real; the platform in native is simulated. These checks
do not establish the cause or the recovery of the observed production failure.
"""
import json
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from test_followup_native import native, service, am_rig, base_rig, click
from test_followup_owner_validation import setup_owner
from test_gateway import event, drain
from fs_agent.config import BoundaryError


def conversation():
    def unexpected(*args, **kwargs):
        raise AssertionError('Exact owner navigation must not enter conversation')
    return NS(wants=lambda text: True, group_conversations=True,
              cleanup=lambda: None, process=unexpected)


@pytest.mark.parametrize('text', ['我的跟进', '我的跟进？', '我的跟进?', '我的跟进。'])
def test_exact_owner_entry_uses_original_view_without_model_or_source_refresh(native, monkeypatch, text):
    n=native;n.am.conversation=conversation();rendered=[];authorized=[]
    original=n.am.ledger.port.authorize_user
    def authorize(user):
        authorized.append(user)
        return original(user)
    def unexpected(*args, **kwargs):
        raise AssertionError('The local work view must not refresh project sources')
    monkeypatch.setattr(n.am.ledger.port,'authorize_user',authorize)
    monkeypatch.setattr(n.am,'projects',unexpected)
    monkeypatch.setattr(n.am,'query_projects',unexpected)
    monkeypatch.setattr(n.am,'ux_work',lambda row:rendered.append(dict(row)))
    incoming=event(text,number=1001,user=n.am.owner,chat=n.row['chat'])
    assert n.am.ingest(incoming)==(True,True)
    ident=incoming['event']['message']['message_id']
    assert n.s.rows('SELECT kind FROM am_inbox WHERE id=?',(ident,))[0]['kind']=='text'
    n.am.step()
    assert n.s.rows('SELECT state,error FROM am_inbox WHERE id=?',(ident,))==[{'state':'done','error':None}]
    assert len(rendered)==1 and rendered[0]['_readonly_request'] is True
    assert rendered[0]['_view_kind']=='navigation'
    assert n.am.owner in authorized
    assert not n.calls and not n.s.rows('SELECT * FROM followup_intents')


def test_exact_entry_does_not_expand_non_owner_navigation(native, monkeypatch):
    n=native;n.am.conversation=conversation()
    incoming=event('我的跟进',number=1002,user='ou_engineer_a',chat='oc_engineer')
    assert n.am.ingest(incoming)==(True,True)
    ident=incoming['event']['message']['message_id']
    assert n.s.rows('SELECT kind FROM am_inbox WHERE id=?',(ident,))[0]['kind']=='conversation'
    with pytest.raises(BoundaryError,match='OWNER_ONLY'):
        n.am.handle(dict(n.row,user='ou_engineer_a',body='我的跟进'))
    assert not n.calls


@pytest.mark.parametrize('thread_key',['parent_id','root_id'])
def test_unmatched_threaded_input_keeps_conversation_route(native,thread_key):
    n=native;n.am.conversation=conversation()
    incoming=event('我的跟进',number=1003,user=n.am.owner,chat=n.row['chat'])
    incoming['event']['message'][thread_key]='om_unrelated'
    assert n.am.ingest(incoming)==(True,True)
    ident=incoming['event']['message']['message_id']
    assert n.s.rows('SELECT kind FROM am_inbox WHERE id=?',(ident,))[0]['kind']=='conversation'


def test_active_collection_keeps_its_input(native,monkeypatch):
    n=native;n.am.conversation=conversation()
    monkeypatch.setattr(n.am,'ux_collection_at_receipt',lambda row:{'token':'active-collection'})
    incoming=event('我的跟进',number=1004,user=n.am.owner,chat=n.row['chat'])
    assert n.am.ingest(incoming)==(True,True)
    ident=incoming['event']['message']['message_id']
    assert n.s.rows('SELECT kind FROM am_inbox WHERE id=?',(ident,))[0]['kind']=='collection'
    assert json.loads(n.s.rows('SELECT context FROM am_ux_receipts WHERE id=?',(ident,))[0]['context'])=={'token':'active-collection'}


def test_exact_entry_respects_items_flag(native):
    n=native;n.am.flags['items']=False
    with pytest.raises(BoundaryError,match='ITEMS_NOT_ENABLED'):
        n.am.handle(dict(n.row,body='我的跟进'))
    assert not n.calls


def test_exact_threaded_owner_reply_is_not_swallowed_by_navigation(native):
    n=native;setup_owner(n)
    item=n.f.validation_item(n.row,'oc_reminder',n.am.owner,'recipient_p2p',owner_self_test=True)
    nonce=n.f.preview_card(n.row,item['id'],'recipient_p2p',recipient=n.am.owner,body='[合成导航检查] 请回复本消息。')
    drain(n.g)
    card=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    click(n,card);n.am.scheduler.dispatch()
    occurrence=n.s.rows('SELECT * FROM reminder_occurrences WHERE item_id=?',(item['id'],))[0]
    incoming=event('我的跟进',number=1005,user=n.am.owner,chat=n.row['chat'])
    incoming['event']['message'].update(parent_id=occurrence['message_id'],create_time=str(int(n.clock()*1000)))
    assert n.am.ingest(incoming)==(True,True)
    ident=incoming['event']['message']['message_id']
    assert n.s.rows('SELECT kind FROM am_inbox WHERE id=?',(ident,))[0]['kind']=='followup_reply'
    n.am.step()
    assert n.s.rows('SELECT kind FROM followup_reply_links WHERE message_id=?',(ident,))==[{'kind':'reported_update'}]
    assert len(n.calls)==1 and n.am.items.get(item['id'])['state']=='waiting'


def test_stale_source_result_stays_rejected_but_static_recovery_can_render(native):
    n=native
    row=dict(n.row,_source_access_version='old-epoch',_query_read=True,_query_grant=['*'],
             _snapshot_version='old-snapshot',_snapshot_meta={'private':'do-not-copy'},
             _interaction='old-interaction',_view_version=5,_immutable_output=True,
             _business_event='sensitive-approval')
    before=len(n.s.rows('SELECT * FROM outbox'))
    with pytest.raises(BoundaryError,match='SOURCE_ACCESS_CHANGED'):
        n.am.notify(row,text='private-source-value')
    assert len(n.s.rows('SELECT * FROM outbox'))==before
    n.am.ux_error(row,'SOURCE_ACCESS_CHANGED')
    out=n.s.rows('SELECT * FROM outbox ORDER BY rowid DESC LIMIT 1')[0]
    snapshot=json.loads(n.s.rows('SELECT snapshot FROM am_cards WHERE outbox_id=?',(out['id'],))[0]['snapshot'])
    assert set(a['page'] for a in snapshot['actions'].values())=={'work','projects'}
    assert snapshot['fields'] is None and not snapshot['envelope']['facts']
    assert 'do-not-copy' not in out['body'] and 'private-source-value' not in out['body']
    assert 'old-snapshot' not in json.dumps(snapshot) and 'sensitive-approval' not in json.dumps(snapshot)
    assert n.am.query_delivery_authorized(out) is True
    assert out['expires']<=row['expires']
    assert row['_source_access_version']=='old-epoch'
    assert not n.s.rows('SELECT * FROM followup_intents') and not n.calls
    # The same stale result still fails after the recovery view was created.
    with pytest.raises(BoundaryError,match='SOURCE_ACCESS_CHANGED'):
        n.am.notify(row,text='private-source-value')


def _claim(n,text,item=None,fact_ids=None):
    item=item or n.item
    refs=n.f.sources.resolve(item['project_ref'],fact_ids) if fact_ids else n.f.sources.defaults(item['project_ref'])
    n.f.bind(n.row,item['id'],refs=refs)
    n.f.record_claim(n.row,item['id'],'blocker',text,[r['fact_id'] for r in refs])


def test_dashboard_does_not_relabel_pre_revocation_content_with_new_epoch(native,monkeypatch):
    n=native;_claim(n,'protected-before-revocation')
    original=n.am.ux_page
    def revoke_after_projection(row,title,text,actions,**kwargs):
        assert not n.reader.conn.in_transaction
        assert not n.s.conn.in_transaction
        assert 'protected-before-revocation' in text
        n.reader.register_source(replace(n.source,enabled=False))
        return original(row,title,text,actions,**kwargs)
    monkeypatch.setattr(n.am,'ux_page',revoke_after_projection)
    with pytest.raises(BoundaryError,match='SOURCE_ACCESS_CHANGED'):
        n.f.dashboard(n.row)
    assert all('protected-before-revocation' not in r['body'] for r in n.s.rows('SELECT body FROM outbox'))
    assert not n.calls


def test_dashboard_delivery_rechecks_epoch_and_uses_raw_expiry(native):
    n=native;_claim(n,'retention-bound-progress')
    deadline=n.clock()+45
    with n.reader.transaction() as db:
        db.execute('UPDATE observations SET raw_expires_at_ms=? WHERE source_id=?',
                   (int(deadline*1000),n.source.source_id))
    n.f.dashboard(n.row)
    out=n.s.rows('SELECT * FROM outbox ORDER BY rowid DESC LIMIT 1')[0]
    assert out['expires']<=deadline
    assert n.am.query_delivery_authorized(out) is True
    n.reader.register_source(replace(n.source,enabled=False))
    assert n.am.query_delivery_authorized(out) is False
    assert not n.calls


def test_dashboard_one_revoked_source_does_not_hide_unrelated_progress(native,monkeypatch):
    n=native;_claim(n,'revoked-progress')
    source=replace(n.source,source_id='other-current-source',remote_id='other-current-remote')
    n.reader.register_source(source)
    obs=replace(n.obs,source_id=source.source_id,object_id='other-current-object')
    n.reader.record(obs);processed=n.facts.process(obs,[])
    item=n.am.items.create(n.am.owner,'other-dashboard-item',project_ref=n.item['project_ref'],
        description='独立事项',requirements='查看依据',assignees=['ou_engineer_a'],source=json.loads(n.item['source']))
    _claim(n,'still-readable-progress',item,processed['fact_ids'])
    n.reader.register_source(replace(n.source,enabled=False))
    rendered=[]
    monkeypatch.setattr(n.am,'ux_page',lambda row,title,text,actions:rendered.append((dict(row),text)))
    n.f.dashboard(n.row)
    assert len(rendered)==1
    assert 'revoked-progress' not in rendered[0][1]
    assert 'still-readable-progress' in rendered[0][1]
    assert '依据已变化' in rendered[0][1]
    assert not n.calls

