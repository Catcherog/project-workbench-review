"""Real coordinator + SQLite; simulated message platform, no Feishu send.

Run in the original AM test environment with bridge and Studio/src on PYTHONPATH.
These are admission/readback regressions, not real platform or user acceptance.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import copy
import json
import sqlite3
import threading
from types import SimpleNamespace as NS

import pytest

from fs_agent.config import BoundaryError
from fs_agent.project_catalog import canonical, digest
from am_followup.followup import (Actor, Draft, EvidenceSnapshot, FollowupCoordinator,
                                  GateResult, SendWindow, Target)
from am_followup_text import FollowupTextUI, wants_text


class SqlStore:
    def __init__(self, path, clock):
        self.path, self.clock, self.lock = path, clock, threading.RLock()
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
          CREATE TABLE outbox(id TEXT PRIMARY KEY, body TEXT, state TEXT, message_id TEXT, created REAL, kind TEXT DEFAULT 'text');
          CREATE TABLE am_cards(nonce TEXT PRIMARY KEY,flow TEXT,object_id TEXT,version INTEGER,
            actor TEXT,chat TEXT,snapshot TEXT,hash TEXT,expires REAL,outbox_id TEXT,message_id TEXT);
          CREATE TABLE followup_bindings(preview_id TEXT PRIMARY KEY,token TEXT,invalidated INTEGER);
        ''')

    @contextmanager
    def tx(self):
        with self.lock:
            with self.conn: yield self.conn

    def rows(self, query, params=()):
        with self.lock: return [dict(x) for x in self.conn.execute(query, params)]

    def execute(self, query, params=()):
        with self.tx() as c: return c.execute(query, params)


@pytest.fixture
def rig(tmp_path):
    tick = [1780000000.0]
    clock = lambda: tick[0]
    store = SqlStore(tmp_path/'state.sqlite', clock)
    remote, adopted, allowed = {}, [], [True]
    owner, tenant, app, bot = 'ou_owner', 'tenant', 'app', 'ou_bot'
    am = NS(s=store, flags={'items':True, 'scheduler':True}, information=None,
        ledger=NS(port=NS(authorize_user=lambda user: None)),
        g=NS(config=NS(bot_open_id=bot), reminders=NS(port=NS(read=lambda mid: copy.deepcopy(remote[mid])))))
    am.scope = lambda row: canonical([row['tenant'], row['app'], row['chat'], row['user']]
        +([row['_source_meta']['thread']] if row.get('_source_meta',{}).get('thread') else []))
    am.source_meta = lambda row: row.get('_source_meta', {})
    am.query_grant = lambda row: ['owner']
    def notify(row, text=None, *, card=None, conn=None, **kwargs):
        assert card is None, 'new path must never construct an interactive card'
        out = 'out_'+str(len(store.rows('SELECT id FROM outbox')))
        target = conn or store.conn
        target.execute('INSERT INTO outbox(id,body,state,message_id,created) VALUES(?,?,?,NULL,?)', (out, text, 'pending', clock()))
        if conn is None: store.conn.commit()
        return out
    am.notify = notify
    def actor(row):
        if (row.get('app'), row.get('tenant'), row.get('user'), row.get('chat_type')) != (app, tenant, owner, 'p2p'):
            raise BoundaryError('FOLLOWUP_OWNER_SCOPE_REQUIRED')
        return Actor(tenant, owner, row['id'], datetime.fromtimestamp(clock()+600, timezone.utc))
    h = NS(am=am, s=store, owner=owner, tenant=tenant, app=app, actor=actor)
    coordinator = FollowupCoordinator(store.path, signing_key=b'x'*32, owner_ids={tenant:owner},
        evidence_gate=lambda *args: GateResult(allowed[0], 'source_changed'),
        recipient_gate=lambda *args: GateResult(True),
        clock=lambda: datetime.fromtimestamp(clock(), timezone.utc))
    h.coordinator = coordinator
    def result_text(results):
        for result in results:
            if result.result and result.result.intent_id not in adopted:
                adopted.append(result.result.intent_id)
        return '|'.join(r.error or r.result.status for r in results)
    h.approval_result_text = result_text
    def stop(row, card, action):
        assert action == 'stop'
        store.execute('UPDATE followup_bindings SET invalidated=1 WHERE preview_id=?', (card['object_id'],))
        for r in store.rows('SELECT intent_id FROM followup_intents WHERE preview_id=?', (card['object_id'],)):
            coordinator.revoke(actor(row), r['intent_id'])
        return '已取消'
    h.card_action = stop
    ui = FollowupTextUI(h)
    row = dict(id='om_request', app=app, tenant=tenant, user=owner, chat='oc_owner',
               chat_type='p2p', kind='text', body='群聊跟进 1', created=clock(), expires=clock()+86400)

    def preview(body='请确认开测时间。', *, deliver=True):
        now = datetime.fromtimestamp(clock(), timezone.utc)
        end = datetime.fromtimestamp(clock()+600, timezone.utc)
        episode = coordinator.register_episode(tenant_id=tenant, task_id='task', purpose='request_update', trigger_key='same_business_decision')
        draft = Draft('task', 'request_update', episode, body,
            Target('group', 'oc_group', ('ou_engineer',), ('ou_engineer',), 'directory-v1', end),
            EvidenceSnapshot({'source':'v1'}, {'source':'acl-v1'}, 'task-v1', ('disclosure-v1',)),
            SendWindow(now, end, (now.date().isoformat(),), allow_outside_hours=True, calendar_version='single_window'))
        p = coordinator.create_preview(actor(row), draft)
        store.execute('INSERT INTO followup_bindings VALUES(?,?,0)', (p.preview_id, p.token))
        nonce = ui.publish_action(row, object_id=p.preview_id, version=1,
            snapshot={'rows':[[p.preview_id, p.content_hash]]}, title='完整跟进预览', body='对象：工程师甲\n正文：'+body+'\n本次一条。',
            actions=[('confirm_send_once','确认发送')], flow='followup', expires=end.timestamp())
        view = store.rows('SELECT * FROM am_followup_text_actions WHERE nonce=?', (nonce,))[0]
        if deliver:
            mid = 'om_'+nonce
            store.execute("UPDATE outbox SET state='sent',message_id=? WHERE id=?", (mid, view['outbox_id']))
            store.execute('UPDATE am_cards SET message_id=? WHERE nonce=?', (mid, nonce))
            remote[mid] = dict(message_id=mid, chat_id=row['chat'], sender_id=bot, sender_type='app', msg_type='text',
                               content={'text':view['body']}, deleted=False, created_at=clock())
        return store.rows('SELECT * FROM am_cards WHERE nonce=?', (nonce,))[0], view

    def inbound(view, verb='确认发送', **changes):
        mid = 'om_approve_'+str(len(remote))
        text = verb+' '+view['code']
        message = dict(message_id=mid, chat_id=row['chat'], sender_id=owner, sender_type='user', msg_type='text',
                       content={'text':text}, deleted=False, created_at=clock())
        remote[mid] = message
        incoming = dict(row, id=mid, body=text, created=clock(), _source_meta={
            'message_type':'text', 'fingerprint_kind':'raw-content-v1', 'content_fingerprint':digest({'text':text})})
        incoming.update(changes)
        return incoming, message
    yield NS(ui=ui, h=h, am=am, s=store, row=row, preview=preview, inbound=inbound,
             remote=remote, tick=tick, allowed=allowed, adopted=adopted)
    store.conn.close()


def test_one_real_text_approval_and_repeated_message_keep_one_intent(rig):
    r=rig; card,view=r.preview()
    assert r.s.rows('SELECT * FROM followup_intents') == []
    row,_=r.inbound(view)
    assert r.ui.handle(row)[1] == 'approved'
    assert r.ui.handle(row)[1] == 'replay'
    second,_=r.inbound(view)
    assert r.ui.handle(second)[1] == 'replay'
    assert len(r.s.rows('SELECT * FROM followup_intents')) == 1
    assert len(r.adopted) == 1


@pytest.mark.parametrize('text', ['好', '好的，发吧', '确认', '确认发送 ABCD', '“确认发送 ABCDEF01”'])
def test_casual_or_quoted_text_is_not_approval(rig,text):
    rig.preview()
    assert not wants_text(text)
    assert rig.ui.handle(dict(rig.row, body=text)) == (False, None)
    assert not rig.s.rows('SELECT * FROM followup_intents')


@pytest.mark.parametrize('field,value', [('app','other'),('tenant','other'),('user','ou_other'),('chat','oc_other')])
def test_scope_change_rejects_before_admission(rig,field,value):
    _,view=rig.preview(); row,_=rig.inbound(view,**{field:value})
    with pytest.raises(BoundaryError): rig.ui.handle(row)
    assert not rig.s.rows('SELECT * FROM followup_intents')


@pytest.mark.parametrize('change', ['preview_body','inbound_body','deleted','wrong_sender','wrong_type','wrong_reply','old_time','future_time','thread'])
def test_platform_readback_changes_and_unbound_replies_never_approve(rig,change):
    r=rig; card,view=r.preview(); row,m=r.inbound(view)
    if change=='preview_body':r.remote[card['message_id']]['content']['text']+='extra'
    if change=='inbound_body':m['content']['text']='好的'
    if change=='deleted':m['deleted']=True
    if change=='wrong_sender':m['sender_id']='ou_other'
    if change=='wrong_type':m['msg_type']='post'
    if change=='wrong_reply':m['parent_id']='om_another'
    if change=='old_time':m['created_at']-=1;row['created']-=1
    if change=='future_time':m['created_at']+=100;row['created']+=100
    if change=='thread':row['_source_meta']['thread']='another_thread'
    with pytest.raises(BoundaryError):r.ui.handle(row)
    assert not r.s.rows('SELECT * FROM followup_intents')


def test_undelivered_preview_and_expired_preview_are_not_approved(rig):
    r=rig; _,view=r.preview(deliver=False); row,_=r.inbound(view)
    with pytest.raises(BoundaryError,match='NOT_DELIVERED'):r.ui.handle(row)
    _,view=r.preview(); row,_=r.inbound(view);r.tick[0]+=601
    with pytest.raises(BoundaryError,match='EXPIRED'):r.ui.handle(row)
    assert not r.s.rows('SELECT * FROM followup_intents')


def test_new_preview_invalidates_old_code_even_when_body_matches(rig):
    r=rig;_,old=r.preview();row,_=r.inbound(old)
    r.preview()
    with pytest.raises(BoundaryError,match='EXPIRED'):r.ui.handle(row)
    assert not r.s.rows('SELECT * FROM followup_intents')


def test_source_changes_use_original_coordinator_gate(rig):
    r=rig;_,view=r.preview();row,_=r.inbound(view);r.allowed[0]=False
    assert r.ui.handle(row)[1] == 'evidence_blocked'
    assert not r.s.rows('SELECT * FROM followup_intents')


def test_cancel_exact_preview_then_replay_cannot_create_send(rig):
    r=rig;_,view=r.preview();row,_=r.inbound(view,'取消发送')
    assert r.ui.handle(row)[1] == '已取消'
    approval,_=r.inbound(view)
    with pytest.raises(BoundaryError):r.ui.handle(approval)
    assert not r.s.rows('SELECT * FROM followup_intents')


def test_wrong_action_verb_cannot_adopt_or_approve_another_kind(rig):
    r=rig;_,view=r.preview();row,_=r.inbound(view,'确认采用')
    with pytest.raises(BoundaryError,match='ACTION_MISMATCH'):r.ui.handle(row)
    assert not r.s.rows('SELECT * FROM followup_intents')


def test_expired_text_bytes_are_cleaned_without_deleting_coordinator_records(rig):
    r=rig;_,view=r.preview();row,_=r.inbound(view);r.ui.handle(row)
    r.tick[0]+=601;r.ui.cleanup()
    assert r.s.rows('SELECT body FROM am_followup_text_actions')[0]['body']==''
    assert len(r.s.rows('SELECT * FROM followup_intents'))==1


def test_source_snapshot_tamper_cannot_be_hidden_by_current_platform_text(rig):
    r=rig;card,view=r.preview();row,_=r.inbound(view)
    r.s.execute("UPDATE am_cards SET snapshot='{}' WHERE nonce=?",(card['nonce'],))
    with pytest.raises(BoundaryError,match='CHANGED'):r.ui.handle(row)
    assert not r.s.rows('SELECT * FROM followup_intents')


def test_explicit_reply_to_own_preview_is_valid_and_no_extra_send_occurs(rig):
    r=rig;card,view=r.preview();row,m=r.inbound(view)
    m['parent_id']=card['message_id']
    assert r.ui.handle(row)[1]=='approved'
    assert len(r.s.rows('SELECT * FROM followup_intents'))==1


def test_reply_with_plain_explicit_confirm_is_bound_to_exact_preview(rig):
    r=rig;card,view=r.preview();row,m=r.inbound(view)
    row['body']='确认发送';m['content']={'text':'确认发送'};m['parent_id']=card['message_id']
    row['_source_meta'].update(parent=card['message_id'],content_fingerprint=digest(m['content']))
    assert r.ui.handle(row)[1]=='approved'
    assert len(r.s.rows('SELECT * FROM followup_intents'))==1


def test_plain_confirm_without_reply_binding_cannot_approve_current_preview(rig):
    r=rig;r.preview()
    with pytest.raises(BoundaryError,match='REPLY_MISMATCH'):
        r.ui.handle(dict(r.row,body='确认发送'))
    assert not r.s.rows('SELECT * FROM followup_intents')


def test_exact_platform_parent_can_bind_reply_created_thread(rig):
    r=rig;card,view=r.preview();row,m=r.inbound(view)
    row['body']='确认发送';m['content']={'text':'确认发送'};m['parent_id']=card['message_id']
    row['_source_meta'].update(parent=card['message_id'],thread='new-feishu-reply-thread',content_fingerprint=digest(m['content']))
    assert r.ui.handle(row)[1]=='approved'
    assert len(r.s.rows('SELECT * FROM followup_intents'))==1


def test_local_parent_hint_without_matching_platform_parent_never_bridges_scope(rig):
    r=rig;card,view=r.preview();row,m=r.inbound(view)
    row['body']='确认发送';m['content']={'text':'确认发送'}
    row['_source_meta'].update(parent=card['message_id'],thread='wrong-thread',content_fingerprint=digest(m['content']))
    with pytest.raises(BoundaryError):r.ui.handle(row)
    assert not r.s.rows('SELECT * FROM followup_intents')
