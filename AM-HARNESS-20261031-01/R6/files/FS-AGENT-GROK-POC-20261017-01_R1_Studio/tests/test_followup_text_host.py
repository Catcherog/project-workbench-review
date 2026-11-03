"""New text path through original AM ingress, SQLite, coordinator and scheduler.

All platform reads/sends are simulated by the established native fixture.
These are not real Feishu or human acceptance results.
"""
import json
from types import SimpleNamespace as NS

import pytest

from test_followup_native import native, service, am_rig, base_rig
from test_gateway import event, drain
from fs_agent.config import BoundaryError


def incoming(n,text,number,*,parent=None,thread=None,user=None,chat=None):
    e=event(text,number=number,user=user or n.am.owner,chat=chat or n.row['chat'])
    e['event']['message']['create_time']=str(int(n.clock()*1000))
    if parent:e['event']['message']['parent_id']=parent
    if thread:e['event']['message']['thread_id']=thread
    assert n.am.ingest(e)==(True,True)
    ident=e['event']['message']['message_id']
    return n.s.rows('SELECT * FROM am_inbox WHERE id=?',(ident,))[0]


def test_plain_navigation_outbox_has_no_small_card_and_no_model(native):
    n=native
    n.am.conversation=NS(wants=lambda text:True,cleanup=lambda:None,
        delivery_source_authorized=lambda row:True,
        process=lambda row:(_ for _ in ()).throw(AssertionError('navigation called model')))
    row=incoming(n,'我的跟进',2001)
    assert row['kind']=='text'
    n.am.step(row)
    out=n.s.rows('SELECT * FROM outbox ORDER BY rowid DESC LIMIT 1')[0]
    assert out['kind']=='text' and '查看跟进 1' in out['body']
    assert not n.s.rows("SELECT * FROM am_cards WHERE flow='ux'")
    assert n.am.query_delivery_authorized(out) is True
    assert not n.calls


def test_reply_confirmation_in_new_thread_uses_same_original_single_sender(native):
    n=native;nonce=n.f.preview_text(n.row,n.item['id'],'recipient_p2p');drain(n.g)
    c=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    out=n.s.rows('SELECT * FROM outbox WHERE id=?',(c['outbox_id'],))[0]
    assert out['kind']=='text' and not n.calls
    row=incoming(n,'确认发送',2002,parent=c['message_id'],thread='fresh-feishu-thread')
    assert row['kind']=='text'
    n.am.step(row)
    assert n.s.rows('SELECT state,error FROM am_inbox WHERE id=?',(row['id'],))==[{'state':'done','error':None}]
    assert len(n.s.rows('SELECT * FROM followup_intents'))==1
    assert len(n.s.rows('SELECT * FROM reminder_occurrences'))==1
    n.am.scheduler.dispatch();n.am.scheduler.dispatch()
    assert len(n.calls)==1
    occurrence=n.s.rows('SELECT * FROM reminder_occurrences')[0]
    assert (occurrence['state'],occurrence['readback_state'])==('sent','verified')
    reply=incoming(n,'收到',2003,parent=occurrence['message_id'],user='ou_engineer_a',chat='oc_engineer')
    assert reply['kind']=='followup_reply'
    n.am.step(reply)
    assert n.s.rows('SELECT kind FROM followup_reply_links')==[{'kind':'acknowledged'}]
    assert n.am.items.get(n.item['id'])['state']=='waiting'
    assert len(n.calls)==1


def test_text_preview_cannot_be_approved_as_a_card_callback(native):
    n=native;nonce=n.f.preview_text(n.row,n.item['id']);drain(n.g)
    c=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    forged=dict(n.row,kind='card',body=json.dumps({'value':{'nonce':nonce,'action':'confirm_send_once'},'source_message':c['message_id']}))
    with pytest.raises(BoundaryError,match='ORIGINAL_MESSAGE_REQUIRED'):n.am.validate_card(forged)
    assert not n.s.rows('SELECT * FROM followup_intents') and not n.calls


def test_training_window_parks_model_message_but_serves_followup_navigation(native):
    n=native
    n.am.conversation=NS(wants=lambda text:True,cleanup=lambda:None,
        process=lambda row:(_ for _ in ()).throw(AssertionError('maintenance called model')))
    blocked=incoming(n,'帮我分析一段材料',2004)
    allowed=incoming(n,'我的跟进',2005)
    n.s.execute("INSERT OR REPLACE INTO meta VALUES('resource_window_owner','controlled-training-window')")
    n.am.step()
    assert n.s.rows('SELECT state FROM am_inbox WHERE id=?',(blocked['id'],))==[{'state':'received'}]
    assert n.s.rows('SELECT state FROM am_inbox WHERE id=?',(allowed['id'],))==[{'state':'done'}]
    assert n.s.rows('SELECT kind FROM outbox ORDER BY rowid DESC LIMIT 1')[0]['kind']=='text'
    n.s.execute("UPDATE am_inbox SET state='processing' WHERE id=?",(blocked['id'],))
    assert n.am.step(blocked,claimed=True) is False
    assert n.s.rows('SELECT state,error FROM am_inbox WHERE id=?',(blocked['id'],))==[{'state':'received','error':None}]
    assert not n.calls
