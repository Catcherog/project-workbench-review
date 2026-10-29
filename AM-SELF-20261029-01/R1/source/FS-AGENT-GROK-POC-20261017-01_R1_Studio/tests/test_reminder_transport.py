"""Exercise real SDK request builders and independent egress policy with no network."""
import copy
import json
from types import SimpleNamespace as NS
import pytest
from fs_agent.config import BoundaryError
from fs_agent.feishu import SendRejected,SendUnknown
from fs_agent.reminder_content import normalized_payload,verify_message
from fs_agent.reminder_feishu import ReminderPort

def port(tmp_path,response):
    (tmp_path/"config").mkdir()
    (tmp_path/"config/group-reminder.json").write_text(json.dumps({"outbound_group_ids":["oc_target"],"reconcile_own_attempts":False}))
    calls=[]
    def create(request):calls.append(request);return response
    cfg=NS(root=tmp_path,app_id="cli_test",bot_open_id="ou_bot",tenant_key="tenant_test")
    client=NS(im=NS(v1=NS(message=NS(create=create))))
    return ReminderPort(cfg,client),calls

def payload():
    return normalized_payload("a"*32,{"id":"ou_bot","app_id":"cli_test","name":"机器人"},
        {"id":"oc_target","name":"目标群"},[{"id":"ou_engineer","name":"甲<工>"}],'<at user_id="all">假标签</at> @all 只是正文。')

def response(code=0,status=200):
    return NS(success=lambda:code==0,code=code,data=NS(message_id="om_remote"),raw=NS(status_code=status))

def test_send_uses_frozen_chat_and_structured_at_only(tmp_path):
    p,calls=port(tmp_path,response());original=payload();p.send(original,"stable-request-key",lambda:True)
    r=calls[0]
    assert r.queries==[("receive_id_type","chat_id")]
    assert r.request_body.receive_id=="oc_target" and r.request_body.msg_type=="post" and r.request_body.uuid=="stable-request-key"
    body=json.loads(r.request_body.content)
    assert body==original["content"] and body["zh_cn"]["content"][0]==[{"tag":"at","user_id":"ou_engineer","user_name":"甲<工>"}]
    assert body["zh_cn"]["content"][1][0]["tag"]=="text"

@pytest.mark.parametrize("code,status,expected",[(230002,400,SendRejected),(230020,400,SendRejected),(230049,400,SendUnknown),(999999,500,SendUnknown),(230001,500,SendUnknown)])
def test_failure_classification_does_not_treat_being_sent_as_not_sent(tmp_path,code,status,expected):
    p,_=port(tmp_path,response(code,status))
    with pytest.raises(expected):p.send(payload(),"stable-key",lambda:True)

def test_guard_and_unconfigured_group_are_rejected_before_sdk_call(tmp_path):
    p,calls=port(tmp_path,response())
    with pytest.raises(SendRejected):p.send(payload(),"key",lambda:False)
    other=payload();other["group"]["id"]="oc_unapproved"
    with pytest.raises(SendRejected):p.send(other,"key",lambda:True)
    assert calls==[]

def test_bot_app_id_in_platform_readback_maps_to_verified_bot(tmp_path):
    p,_=port(tmp_path,response());x=payload()
    m=NS(sender=NS(id="cli_test",open_bot_id=None,sender_type="app"),message_id="om_remote",chat_id="oc_target",msg_type="post",body=NS(content=json.dumps(x["content"])),mentions=[],create_time=1_800_000_000_000,message_app_link=None,deleted=False)
    assert verify_message(x,p._message(m))
    m.sender.id="cli_wrong";assert not verify_message(x,p._message(m))

def test_unknown_without_lookup_permission_does_not_read_history(tmp_path):
    p,_=port(tmp_path,response())
    assert p.reconcile(payload(),"key",0) is None


def test_readback_mention_placeholders_resolve_and_extra_metadata_is_rejected():
    x=payload();body=copy.deepcopy(x["content"])
    body["zh_cn"]["content"][0][0]["user_id"]="_user_1"
    m={"chat_id":"oc_target","sender_id":"ou_bot","sender_type":"app","msg_type":"post","content":body,
       "mentions":[{"key":"@_user_1","id":"ou_engineer"}]}
    assert verify_message(x,m)
    m["mentions"].append({"key":"@_user_2","id":"ou_extra"})
    assert not verify_message(x,m)
