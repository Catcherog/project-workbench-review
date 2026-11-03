"""Explicit owner UAT stays separate from engineer identity and approval."""
import json
import pytest
from test_followup_native import native, service, am_rig, base_rig, click
from test_gateway import drain, event
from fs_agent.config import BoundaryError
from am_info_sync.ingest import record_offline


def setup_owner(n):
    n.am.information.service.offline=lambda *a,**kw:record_offline(n.reader,*a,**kw)
    person={'id':n.am.owner,'name':'本人'}
    n.g.reminders.port.people.append(person);n.members.append(person)
    n.remote['om_owner']={'message_id':'om_owner','chat_id':n.row['chat'],'sender_id':n.am.owner,
        'sender_type':'user','msg_type':'text','content':{'text':'/followup'},'deleted':False,'created_at':n.clock()}
    original=n.api.client.im.v1.message.create
    def create(request):
        response=original(request)
        if request.request_body.receive_id==n.am.owner:
            n.remote[response.data.message_id]['chat_id']=n.row['chat']
        return response
    n.api.client.im.v1.message.create=create


@pytest.mark.parametrize('kind',['conversation','collection'])
def test_native_message_routes_remain_exact_private_conversation_evidence(native,kind):
    n=native
    n.s.execute('UPDATE am_inbox SET kind=? WHERE id=?',(kind,'om_engineer'))
    target=n.f.p2p('ou_engineer_a')
    assert target['anchor_message']=='om_engineer' and target['chat']=='oc_engineer'
    n.remote['om_engineer']['sender_id']='ou_other'
    with pytest.raises(BoundaryError,match='FOLLOWUP_PRIVATE_CHAT_IDENTITY'):
        n.f.p2p('ou_engineer_a')
    assert not n.calls


def test_private_card_callbacks_do_not_become_message_anchors(native):
    n=native;n.s.execute("UPDATE am_inbox SET kind='card' WHERE id='om_engineer'")
    with pytest.raises(BoundaryError,match='FOLLOWUP_BOT_PRIVATE_CHAT_UNVERIFIED'):
        n.f.p2p('ou_engineer_a')
    assert not n.calls


@pytest.mark.parametrize('recipient,channel,flag',[
    ('owner','recipient_p2p',False),('engineer','recipient_p2p',True),
    ('owner','group',True),('owner','recipient_p2p',1),
])
def test_owner_validation_requires_explicit_narrow_request(native,recipient,channel,flag):
    n=native;user=n.am.owner if recipient=='owner' else 'ou_engineer_a'
    with pytest.raises(BoundaryError,match='FOLLOWUP_VALIDATION_TARGET'):
        n.f.validation_item(n.row,'oc_reminder',user,channel,owner_self_test=flag)
    assert len(n.s.rows('SELECT * FROM action_items'))==1 and not n.calls


def test_owner_private_validation_has_separate_identity_and_real_confirmation_gate(native):
    n=native;setup_owner(n)
    engineer=n.f.validation_item(n.row,'oc_reminder','ou_engineer_a','recipient_p2p')
    owner=n.f.validation_item(n.row,'oc_reminder',n.am.owner,'recipient_p2p',owner_self_test=True)
    assert owner['id']!=engineer['id'] and owner['project_ref']!=engineer['project_ref']
    assert json.loads(owner['assignees'])==[n.am.owner]
    assert json.loads(n.am.items.get(engineer['id'])['assignees'])==['ou_engineer_a']
    nonce=n.f.preview_card(n.row,owner['id'],'recipient_p2p',recipient=n.am.owner,body='[AM本人联调测试] 请回复本消息。')
    drain(n.g)
    assert not n.calls and not n.s.rows('SELECT * FROM followup_intents')
    card=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    click(n,card);n.am.scheduler.dispatch();click(n,card);n.am.scheduler.step()
    assert len(n.calls)==1 and n.calls[0][0]==n.am.owner
    occurrence=n.s.rows('SELECT * FROM reminder_occurrences WHERE item_id=?',(owner['id'],))[0]
    assert occurrence['state']=='sent' and occurrence['readback_state']=='verified'
    payload=event('收到',number=908,user=n.am.owner,chat=n.row['chat'])
    payload['event']['message'].update(parent_id=occurrence['message_id'],create_time=str(int(n.clock()*1000)))
    assert n.am.ingest(payload)==(True,True)
    n.am.step()
    assert n.s.rows('SELECT kind FROM followup_reply_links WHERE item_id=?',(owner['id'],))==[{'kind':'acknowledged'}]
    assert n.am.items.get(owner['id'])['state']!='closed'
    assert len(n.calls)==1
