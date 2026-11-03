"""R01-R10: isolated actor, model and platform fixtures; never sends to real people."""
import copy
import json
import threading
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import pytest
from fs_agent.config import BoundaryError
from fs_agent.embedded import EmbeddedPoC
from fs_agent.feishu import SendRejected,SendUnknown
from fs_agent.provider import Result
from fs_agent.reminder_content import (natural_start,dates,parse_fields,normalized_payload,semantic_content,verify_message)
from test_gateway import rig as base_rig,event,drain

TEXT="帮我在合成研发群提醒工程师甲和工程师乙，今天17点前提交接口测试结果，完成后把链接发到群里。"
FIELDS={"intent":"reminder","group_query":"合成研发群","people_queries":["工程师甲","工程师乙"],
        "body":"今天17点前提交接口测试结果，完成后把链接发到群里。","delivery_mode":"immediate"}

class Port:
    def __init__(self,clock):
        self.clock=clock;self.sent=[];self.remote={};self.error=None;self.find=True;self.read_error=False;self.before=None;self.barrier=None
        self.group_info={"id":"oc_reminder","name":"合成研发群","tenant":"tenant_test","bot_member":True,"posting_policy":"all_members","mode":"group"}
        self.people=[{"id":"ou_engineer_a","name":"工程师甲"},{"id":"ou_engineer_b","name":"工程师乙"}]
        self.bot_info={"id":"ou_bot","app_id":"cli_test","name":"合成机器人"}
        self.group_list=[self.group_info];self.allowed_ids=["oc_reminder"]
    def policy(self):return {"outbound_group_ids":self.allowed_ids,"reconcile_own_attempts":True}
    def group(self,ident):
        if ident not in self.allowed_ids:raise BoundaryError("REMINDER_EGRESS_NOT_CONFIGURED")
        return copy.deepcopy(next(g for g in self.group_list if g["id"]==ident))
    def groups(self,hint):return [copy.deepcopy(g) for g in self.group_list if hint in (g["name"],g["id"])]
    def members(self,group):return copy.deepcopy(self.people)
    def bot(self):return copy.deepcopy(self.bot_info)
    def refresh(self,payload):
        if self.barrier:self.barrier.wait(3)
        if self.before:self.before()
        if payload["bot"]!=self.bot_info or payload["group"]!=self.group(payload["group"]["id"]):raise BoundaryError("REMINDER_TARGET_CHANGED")
        if any(p not in self.people for p in payload["people"]):raise BoundaryError("REMINDER_MEMBER_LEFT_GROUP")
    def send(self,payload,key,guard):
        if not guard():raise SendRejected("REMINDER_SEND_GUARD")
        if isinstance(self.error,SendRejected):raise self.error
        self.sent.append((copy.deepcopy(payload),key))
        self.remote[key]={"message_id":"om_remote_"+str(len(self.sent)),"chat_id":payload["group"]["id"],
                          "sender_id":"ou_bot","sender_type":"app","msg_type":"post","content":copy.deepcopy(payload["content"]),
                          "created_at":self.clock(),"link":"https://synthetic.invalid/message"}
        if self.error:raise self.error
        return {"message_id":self.remote[key]["message_id"],"sent_at":self.clock()}
    def reconcile(self,payload,key,started,message_id=None):
        if self.read_error:raise RuntimeError("readback unavailable")
        return copy.deepcopy(self.remote.get(key)) if self.find else None

@pytest.fixture
def rig(base_rig):
    g,s,api,p,c=base_rig;g.config=replace(g.config,reminders_enabled=True,document_logic=True,chats=())
    g.reminders.port=Port(c)
    return g,s,api,p,c,EmbeddedPoC(g)

def receive(rig,text,number,**kwargs):
    g,s,api,p,c,embedded=rig;payload=event(text,number=number,**kwargs)
    payload["event"]["message"]["create_time"]=str(int(c()*1000))
    assert embedded.ingest(payload)==(True,True)
    g.receive_one()
    return s.rows("SELECT * FROM inbox ORDER BY seq DESC LIMIT 1")[0]

def generate(rig,fields=FIELDS):
    g,s,api,p,c,embedded=rig
    def complete(text,**kwargs):
        p.prompts.append(text);return Result(json.dumps(fields,ensure_ascii=False),"isolated-qwen-fixture",.01)
    p.complete=complete
    task=s.claim(1);assert task;g.run_task(task)
    assert s.rows("SELECT state,error FROM tasks WHERE id=?",(task["id"],))[0]=={"state":"completed","error":None}
    drain(g)
    return g.reminders.get(task)

def prepare(rig,text=TEXT,number=1,fields=FIELDS):
    row=receive(rig,text,number);d=generate(rig,fields)
    return row,d

def card(rig,d,action="confirm",number=2,user="ou_a",chat="oc_dm"):
    g,s,api,p,c,embedded=rig
    payload={"header":{"app_id":"cli_test","tenant_key":"tenant_test","event_id":"card"+str(number),"event_type":"card.action.trigger"},
        "event":{"operator":{"open_id":user},"context":{"open_chat_id":chat,"open_message_id":d["preview_message"]},
            "action":{"value":{"flow":"reminder","action":action,"id":d["id"],"revision":d["revision"],"hash":d["content_hash"],"nonce":d["nonce"]}}}}
    accepted=embedded.ingest(payload)
    if accepted[1]:g.receive_one()
    return accepted

@pytest.mark.parametrize("text",[TEXT,"/remind "+TEXT])
def test_R01_natural_and_command_preview_without_group_send(rig,text):
    g,s,api,p,c,e=rig;row,d=prepare(rig,text)
    assert d["state"]=="awaiting_confirmation" and d["preview_message"]
    assert len(p.prompts)==1 and not g.reminders.port.sent
    preview=next(json.loads(x["body"]) for x in api.sent if x["kind"]=="interactive")
    full=preview["elements"][0]["text"]["content"]
    assert "合成机器人" in full and "合成研发群" in full and "工程师甲" in full and "工程师乙" in full
    assert dates(FIELDS["body"],d["anchor"]) in full and d["marker"] in full
    assert all(x["chat_type"]=="p2p" and x["user"]=="ou_a" for x in api.sent)
    assert not s.rows("SELECT * FROM context")

@pytest.mark.parametrize("field",["group_query","people_queries","body"])
def test_R02_missing_fields_only_are_requested(rig,field):
    f=copy.deepcopy(FIELDS);f[field]=[] if field=="people_queries" else None
    row,d=prepare(rig,fields=f)
    assert d["state"]=="collecting" and not d["preview_message"]
    assert not rig[0].reminders.port.sent
    assert "截止" not in rig[2].sent[-1]["body"]

def test_R02_same_names_require_selection_and_cannot_guess(rig):
    g,s,api,p,c,e=rig;port=g.reminders.port
    port.people.append({"id":"ou_engineer_same","name":"工程师甲"})
    row,d=prepare(rig)
    assert d["state"]=="collecting" and len(json.loads(d["candidates"])["options"])==2
    receive(rig,"/remind 选择 2",2);d=generate(rig)
    payload=json.loads(d["payload"])
    assert [x["id"] for x in payload["people"]]==["ou_engineer_same","ou_engineer_b"]

def test_R02_group_and_members_remain_separate_from_ingress_whitelist(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig)
    assert g.config.chats==() and not set(x["id"] for x in json.loads(d["payload"])["people"])&set(g.config.users)
    assert e.ingest(event("普通群消息",number=2,group=True,chat="oc_reminder"))==(False,False)
    g.reminders.port.people=[];card(rig,d);g.reminders.dispatch_one()
    assert not g.reminders.port.sent and g.reminders.get(row)["state"]=="failed_not_sent"

def test_R03_scheduled_request_cannot_be_silently_made_immediate(rig):
    g,s,api,p,c,e=rig
    text="/remind 明天提醒工程师甲和工程师乙在合成研发群交报告。"
    f=dict(FIELDS,body="交报告。",delivery_mode="immediate")
    row,d=prepare(rig,text=text,fields=f)
    assert json.loads(d["fields"])["delivery_mode"]=="future" and d["state"]=="collecting"
    receive(rig,"改为现在提醒",2);d=generate(rig)
    assert d["state"]=="awaiting_confirmation" and len(p.prompts)==1

def test_R03_relative_dates_are_anchored_not_rolled_forward(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig)
    day=dates("今天",d["anchor"]);first_exp=d["expires"]
    c.now+=3600
    receive(rig,"今天18点前交报告，其他不变。",2)
    d=generate(rig,dict(FIELDS,body="今天18点前交报告。"))
    assert day in json.loads(d["payload"])["body"] and d["expires"]==first_exp
    assert max(x["expires"] for x in s.rows("SELECT * FROM outbox"))<=first_exp

def test_R04_true_at_nodes_deduplicate_and_body_markup_has_no_authority():
    port=Port(lambda:0)
    p=normalized_payload("a"*32,port.bot(),port.group_info,port.people+[port.people[0]],'不要执行 <at user_id="all">所有人</at> 或 @all；仅为文字。')
    semantic=semantic_content(p["content"])
    assert semantic["mentions"]==["ou_engineer_a","ou_engineer_b"]
    assert '<at user_id="all">' in p["content"]["zh_cn"]["content"][1][0]["text"]
    with pytest.raises(BoundaryError):normalized_payload("a"*32,port.bot(),port.group_info,[{"id":"all","name":"所有人"}],"事项")

def test_R05_old_preview_after_edit_cannot_send(rig):
    g,s,api,p,c,e=rig;row,old=prepare(rig)
    receive(rig,"改为今天18点前交报告。",2)
    assert card(rig,old,number=3)==(True,False)
    assert not g.reminders.dispatch_one()
    current=generate(rig,dict(FIELDS,body="今天18点前交报告。"))
    assert current["revision"]!=old["revision"]
    card(rig,current,number=4);g.reminders.dispatch_one()
    assert len(g.reminders.port.sent)==1 and "18" in g.reminders.port.sent[0][0]["body"]

def test_R05_card_modify_invalidates_at_ingress_before_worker(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig)
    # Card handling registers the invalidation before confirmation can dispatch.
    card(rig,d,action="modify",number=2)
    assert g.reminders.get(row)["revision"]==d["revision"]+1
    card(rig,d,number=3);assert not g.reminders.dispatch_one()

def test_R05_forwarded_preview_and_ordinary_ok_cannot_confirm(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig)
    assert card(rig,d,chat="oc_forwarded")== (True,False)
    payload=event("确认发送",number=3);payload["event"]["message"]["parent_id"]="om_other"
    assert e.ingest(payload)==(True,True);g.receive_one();assert not g.reminders.dispatch_one()
    assert g.reminders.control("好的") is None

def test_R06_repeated_confirmation_and_restart_do_not_resend(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig)
    assert card(rig,d)==(True,True);assert g.reminders.dispatch_one()
    assert card(rig,d)==(True,False)
    card(rig,d,number=3);assert not g.reminders.dispatch_one()
    g.reminders.recover();card(rig,d,number=4);assert not g.reminders.dispatch_one()
    assert len(g.reminders.port.sent)==1 and g.reminders.get(row)["readback_state"]=="verified"

def test_R06_concurrent_claimers_get_one_send_right(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    port=g.reminders.port;port.barrier=threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results=list(workers.map(lambda _:g.reminders.dispatch_one(),range(2)))
    assert len(port.sent)==1

def test_R06_new_identical_reminder_is_a_different_business_message(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d);g.reminders.dispatch_one()
    row,d2=prepare(rig,number=3);card(rig,d2,number=4);g.reminders.dispatch_one()
    assert d2["id"]!=d["id"] and len(g.reminders.port.sent)==2
    assert g.reminders.port.sent[0][1]!=g.reminders.port.sent[1][1]

def test_R07_definite_failure_manual_retry_reuses_approval_and_key(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    port=g.reminders.port;port.error=SendRejected("SYNTHETIC_PERMISSION_REJECT")
    g.reminders.dispatch_one();failed=g.reminders.get(row)
    assert failed["state"]=="failed_not_sent" and failed["attempts"]==1
    assert not g.reminders.dispatch_one()
    port.error=None;receive(rig,"/remind 重试 R-"+d["marker"],3);g.reminders.dispatch_one()
    done=g.reminders.get(row)
    assert done["state"]=="sent" and done["attempts"]==2 and done["request_key"]==d["request_key"]

def test_R07_remote_sent_lost_reply_is_unknown_until_reconciled(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    port=g.reminders.port;port.error=SendUnknown("lost reply");port.find=False
    g.reminders.dispatch_one();assert g.reminders.get(row)["state"]=="unknown"
    receive(rig,"/remind 重试 R-"+d["marker"],3);card(rig,d,number=4)
    assert not g.reminders.dispatch_one() and len(port.sent)==1
    port.find=True;receive(rig,"/remind 状态 R-"+d["marker"],5)
    assert g.reminders.get(row)["state"]=="sent" and len(port.sent)==1

def test_R07_send_in_progress_on_restart_is_never_queued_again(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    s.execute("UPDATE reminder_drafts SET state='sending',send_started=? WHERE id=?",(c(),d["id"]))
    g.reminders.recover()
    assert g.reminders.get(row)["state"]=="unknown" and not g.reminders.dispatch_one()

def test_R07_readback_or_private_receipt_failure_cannot_resend_group(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    port=g.reminders.port;port.read_error=True;g.reminders.dispatch_one()
    assert g.reminders.get(row)["state"]=="sent" and g.reminders.get(row)["readback_state"]=="pending"
    api.error=SendUnknown("private receipt lost");drain(g)
    receive(rig,"/remind 重试 R-"+d["marker"],3);assert not g.reminders.dispatch_one()
    assert len(port.sent)==1

def test_R08_cancel_before_claim_and_inflight_cancel_are_different(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    g.reminders.port.before=lambda:receive(rig,"/remind 取消 R-"+d["marker"],3)
    g.reminders.dispatch_one();assert not g.reminders.port.sent and g.reminders.get(row)["state"]=="cancelled"
    g.reminders.port.before=None;row,d=prepare(rig,number=4);card(rig,d,number=5)
    original=g.reminders.port.send
    def sending(payload,key,guard):
        receipt=original(payload,key,guard)
        receive(rig,"/remind 取消 R-"+d["marker"],6)
        return receipt
    g.reminders.port.send=sending;g.reminders.dispatch_one()
    assert g.reminders.get(row)["state"]=="sent" and g.reminders.get(row)["cancel_requested"]==1

def test_R08_expiry_rejects_old_confirmation_and_erases_body(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);c.now=d["expires"]+1;g.cleanup()
    assert card(rig,d)==(True,False)
    assert not g.reminders.dispatch_one()
    expired=s.rows("SELECT * FROM reminder_drafts")[0]
    assert expired["state"]=="expired" and expired["payload"] is None and expired["turns"]=="[]"

def test_R09_existing_doc_and_ordinary_context_are_not_modified(rig):
    g,s,api,p,c,e=rig
    assert e.ingest(event("/doc logic test 合成原文记录。"))==(True,True);g.receive_one()
    row=s.rows("SELECT * FROM inbox ORDER BY seq DESC LIMIT 1")[0];before=g.logic.current(row)
    # Do not run the unrelated document job in this isolated test.
    s.execute("UPDATE tasks SET state='completed'")
    receive(rig,TEXT,2);d=generate(rig);card(rig,d,number=3);g.reminders.dispatch_one()
    after=g.logic.current(row)
    assert before==after and s.selection(row)["route"]=="doc"
    assert not s.rows("SELECT * FROM context") and not g.reminders.focused(row)

def test_R09_quote_is_material_not_a_new_reminder(rig):
    for text in ('> 帮我在某群提醒工程师甲交报告','原文：请在群里提醒工程师甲','```\n帮我在某群提醒工程师甲\n```'):
        assert not natural_start(text)

def test_R09_non_owner_and_group_cannot_start_or_approve(rig):
    g,s,api,p,c,e=rig
    assert e.ingest(event(TEXT,user="ou_b"))==(True,False)
    assert e.ingest(event("/remind "+TEXT,group=True,chat="oc_reminder"))==(True,False)
    assert not s.rows("SELECT * FROM reminder_drafts")
    row,d=prepare(rig,number=2)
    assert card(rig,d,user="ou_b",number=3)==(True,False) and not g.reminders.dispatch_one()

def test_R10_disabled_switch_blocks_dispatch_and_preserves_old_scopes(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    g.config=replace(g.config,reminders_enabled=False)
    assert not g.reminders.dispatch_one() and g.config.chats==() and g.config.users==("ou_a","ou_b")

def test_old_resend_cannot_trigger_reminder_group_delivery(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig)
    task=s.rows("SELECT * FROM tasks")[0]
    s.resend(row,task["id"]);drain(g)
    assert not g.reminders.port.sent and d["state"]=="awaiting_confirmation"

def test_readback_rejects_extra_mentions_changed_body_and_wrong_sender():
    port=Port(lambda:0);payload=normalized_payload("a"*32,port.bot(),port.group_info,port.people,"内容")
    port.send(payload,"key",lambda:True);m=port.remote["key"]
    assert verify_message(payload,m)
    changed=copy.deepcopy(m);changed["content"]["zh_cn"]["content"][0].append({"tag":"at","user_id":"ou_other"})
    assert not verify_message(payload,changed)
    assert not verify_message(payload,{**m,"sender_id":"ou_human"})
    changed=copy.deepcopy(m);changed["content"]["zh_cn"]["content"][1][0]["text"]="不同正文"
    assert not verify_message(payload,changed)


def test_plain_confirmation_is_allowed_only_for_one_delivered_current_preview(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig)
    receive(rig,"确认发送",2);assert g.reminders.get(row)["state"]=="approved"
    g.reminders.dispatch_one();assert len(g.reminders.port.sent)==1
    row,d=prepare(rig,number=3);row,d2=prepare(rig,number=4)
    receive(rig,"确认发送",5);assert not g.reminders.dispatch_one()


def test_text_confirmation_compares_the_delivered_snapshot_not_just_current_hash(rig):
    from fs_agent.reminder_content import fingerprint,canonical
    g,s,api,p,c,e=rig;row,d=prepare(rig)
    changed=json.loads(d["payload"]);changed["body"]="未预览的变化"
    s.execute("UPDATE reminder_drafts SET payload=?,content_hash=? WHERE id=?",(canonical(changed),fingerprint(changed),d["id"]))
    receive(rig,"确认发送 R-"+d["marker"]+" v1",2)
    assert not g.reminders.dispatch_one() and not g.reminders.port.sent


def test_old_approved_work_is_not_quietly_sent_later(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    c.now+=61;g.reminders.dispatch_one()
    assert not g.reminders.port.sent and g.reminders.get(row)["state"]=="failed_not_sent"
    receive(rig,"/remind 重试 R-"+d["marker"],3);g.reminders.dispatch_one()
    assert len(g.reminders.port.sent)==0  # Retry cannot extend the original approval window. and g.reminders.get(row)["expires"]==d["expires"]


def test_changed_bot_requires_new_preview_and_has_no_valid_old_approval(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    g.reminders.port.bot_info["name"]="新显示名"
    g.reminders.dispatch_one();current=g.reminders.get(row)
    assert current["state"]=="failed_not_sent" and current["approved_hash"] is None
    receive(rig,"/remind 重试 R-"+d["marker"],3);assert not g.reminders.dispatch_one()
    receive(rig,"/remind 预览 R-"+d["marker"],4);current=generate(rig)
    assert current["state"]=="awaiting_confirmation" and current["content_hash"]!=d["content_hash"]


def test_date_normalization_keeps_a_readable_separator():
    assert " 17点" in dates("今天17点前交报告",1_800_000_000)
    assert " 下午" in dates("明天下午交报告",1_800_000_000)


def test_repeating_an_unknown_original_request_does_not_silently_create_a_retry(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    g.reminders.port.error=SendUnknown("lost reply");g.reminders.port.find=False;g.reminders.dispatch_one()
    receive(rig,TEXT,3)
    assert len(s.rows("SELECT * FROM reminder_drafts"))==1 and not g.reminders.dispatch_one()
    receive(rig,"/remind 新建 "+TEXT,4)
    assert len(s.rows("SELECT * FROM reminder_drafts"))==2
    assert len(g.reminders.port.sent)==1


def test_expiry_during_network_send_preserves_outcome_without_suspending_other_routes(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig);card(rig,d)
    original=g.reminders.port.send
    def delayed(payload,key,guard):
        receipt=original(payload,key,guard);c.now=d["expires"]+1;return receipt
    g.reminders.port.send=delayed
    assert g.reminders.dispatch_one()
    actual=s.rows("SELECT state,message_id FROM reminder_drafts WHERE id=?",(d["id"],))[0]
    assert actual["state"]=="sent" and actual["message_id"] and not e.suspended


@pytest.mark.parametrize("text",["明天提醒一下", "提醒大家尽快处理", "提醒工程师甲今天16点前交报告"])
def test_natural_missing_target_and_future_requests_still_enter_reminder_clarification(text):
    assert natural_start(text)


def test_business_content_timing_after_remind_verb_does_not_schedule_delivery():
    from fs_agent.reminder_content import scheduled_request
    assert not scheduled_request("帮我在合成研发群提醒工程师甲：明天提醒工程师乙交报告。")
    assert scheduled_request("今天16点提醒工程师甲交报告")


def test_R02_everyone_is_a_missing_named_target_not_a_group_member_query(rig):
    g,s,api,p,c,e=rig
    def trap(*a):raise AssertionError("no member lookup needed for unsupported everyone")
    g.reminders.port.members=trap
    row,d=prepare(rig,text="帮我在合成研发群提醒大家尽快处理。",fields=dict(FIELDS,people_queries=["大家"],body="尽快处理。"))
    assert d["state"]=="collecting" and "具体工程师名单" in api.sent[-1]["body"]


def test_R05_delayed_plain_confirmation_cannot_bind_a_newer_preview(rig):
    g,s,api,p,c,e=rig;row,first=prepare(rig);old_time=c()
    c.now+=2;receive(rig,"改为今天18点前交报告。",2);latest=generate(rig,dict(FIELDS,body="今天18点前交报告。"))
    late=event("确认发送",number=3);late["event"]["message"]["create_time"]=str(int(old_time*1000))
    assert e.ingest(late)==(True,True);g.receive_one()
    assert g.reminders.get(row)["state"]=="awaiting_confirmation" and not g.reminders.dispatch_one()


def test_R05_plain_confirmation_after_switching_to_doc_requires_exact_reference(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig)
    assert e.ingest(event("/doc",number=2))==(True,True);g.receive_one()
    receive(rig,"确认发送",3);assert not g.reminders.dispatch_one()
    receive(rig,"确认发送 R-"+d["marker"]+" v1",4);assert g.reminders.dispatch_one()


def test_R06_repeated_plain_confirmation_returns_the_original_result(rig):
    g,s,api,p,c,e=rig;row,d=prepare(rig)
    receive(rig,"确认发送",2);g.reminders.dispatch_one()
    receive(rig,"确认发送",3);drain(g)
    assert not g.reminders.dispatch_one() and len(g.reminders.port.sent)==1
    assert "om_remote_1" in api.sent[-1]["body"]
