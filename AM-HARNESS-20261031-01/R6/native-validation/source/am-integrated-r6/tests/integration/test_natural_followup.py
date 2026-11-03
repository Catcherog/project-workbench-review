"""Natural followup uses existing state; language never grants send authority."""
import json
from types import SimpleNamespace as NS
import pytest

from test_followup_native import native, service, am_rig, base_rig
from test_followup_text_host import incoming
from test_gateway import drain
from am_conversation.followup_tools import NativeFollowupTools
from am_conversation.tools import ToolRegistry
from am_conversation.types import AccessContext, ConversationError


def tools(n):
    row=dict(n.row,kind='conversation',body='他回复了吗？')
    ctx=AccessContext(n.row['tenant'],n.row['app'],n.row['user'],n.row['chat'],
        allowed_project_ids=frozenset([n.item['project_ref']]),is_owner=True,content_expires_at=n.row['expires'])
    b=NS(service=n.am,s=n.s,registry=ToolRegistry(),authorize=lambda *a:None,_current=lambda c:{'row':row})
    t=NativeFollowupTools(b);t.register()
    return t,b,ctx,row


def test_conversation_tools_cannot_approve_or_send(native):
    n=native;t,b,ctx,row=tools(n)
    assert set(b.registry._tools)=={'read_followup_status','read_followup_feedback','prepare_followup_message'}
    result=t.status(ctx,{'item_id':n.item['id']},row['id'])
    assert result['delivery_verified'] is False and not n.calls
    assert t.current(row['id'])
    n.am.items.change(n.am.owner,'pause-after-reading',n.item['id'],n.item['version'],'pause')
    assert t.current(row['id']) is False


def test_natural_quoted_confirmation_uses_single_original_send(native):
    n=native;nonce=n.f.preview_text(n.row,n.item['id'],'recipient_p2p');drain(n.g)
    card=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    out=n.s.rows('SELECT * FROM outbox WHERE id=?',(card['outbox_id'],))[0]
    assert '确认发送 ' not in out['body'] and '按这个发' in out['body']
    row=incoming(n,'可以，发给他吧',2201,parent=card['message_id'],thread='natural-quote-thread')
    n.am.step(row);n.am.scheduler.dispatch();n.am.scheduler.dispatch()
    assert len(n.calls)==1
    assert n.s.rows('SELECT state,readback_state FROM reminder_occurrences')==[{'state':'sent','readback_state':'verified'}]
    t,b,ctx,question=tools(n)
    assert t.status(ctx,{'item_id':n.item['id']},question['id'])['delivery']['state']=='verified'


def test_unquoted_natural_confirmation_cannot_approve(native):
    n=native;n.f.preview_text(n.row,n.item['id']);drain(n.g)
    n.am.step(incoming(n,'按这个发',2202))
    assert not n.s.rows('SELECT * FROM followup_intents') and not n.calls


def test_ambiguous_pronoun_does_not_pick_an_item(native):
    n=native;t,b,ctx,row=tools(n)
    with pytest.raises(ConversationError,match='REFERENCE_AMBIGUOUS'):t.status(ctx,{},row['id'])
    n.f.text_ui._remember(row,[n.item['id']])
    assert t.status(ctx,{},row['id'])['description']==n.item['description']


def test_new_feedback_invalidates_pending_natural_answer(native):
    n=native;t,b,ctx,row=tools(n)
    t.status(ctx,{'item_id':n.item['id']},row['id'])
    n.s.execute('INSERT INTO followup_reply_links VALUES(?,?,?,?,?,?)',
        ('later-reply',n.item['id'],'future-occurrence','ou_engineer_a','reported_update',n.clock()))
    assert not t.current(row['id'])


def test_original_conversation_registers_native_followup_tools(native):
    from am_conversation.legacy import LegacyConversationBridge
    n=native
    b=LegacyConversationBridge(n.am,{'enabled':True})
    try:
        row=dict(n.row,kind='conversation',body='最近哪些事情需要我跟进？')
        with b.request_context(row) as ctx:
            result=b._followups(ctx,{},row['id'])
            assert n.item['id'] in [x['id'] for x in result['items']]
            assert b.native_followup_tools.current(row['id'])
            assert 'prepare_followup_message' in b.registry._tools
    finally:b.close()
