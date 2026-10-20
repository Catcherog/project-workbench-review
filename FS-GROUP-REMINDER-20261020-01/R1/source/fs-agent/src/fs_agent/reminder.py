"""Owner-only immediate reminders in the existing store, worker and event consumer."""
from __future__ import annotations
import hashlib
from pathlib import Path

SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
import json
import re
import time
import uuid
from .config import BoundaryError
from .feishu import SendRejected,SendUnknown
from .message_text import normalize_message
from .provider import Result
from .store import scope_of
from .reminder_content import (VERSION,canonical,fingerprint,natural_start,prompt,parse_fields,
                               normalized_payload,preview_card,verify_message,dates,TZ)
from datetime import datetime
from .reminder_feishu import ReminderPort,MissingReminderPort

SCHEMA="""
CREATE TABLE IF NOT EXISTS reminder_drafts(
 id TEXT PRIMARY KEY, marker TEXT UNIQUE NOT NULL, scope TEXT NOT NULL, origin TEXT NOT NULL,
 created REAL NOT NULL, anchor REAL NOT NULL, expires REAL NOT NULL, revision INTEGER NOT NULL,
 state TEXT NOT NULL, turns TEXT NOT NULL, fields TEXT NOT NULL, selected TEXT NOT NULL,
 candidates TEXT NOT NULL, parsed_count INTEGER NOT NULL DEFAULT 0,
 payload TEXT, content_hash TEXT, nonce TEXT, preview_outbox TEXT, preview_message TEXT, preview_sent REAL,
 approved_hash TEXT, approval TEXT, request_key TEXT, attempts INTEGER NOT NULL DEFAULT 0,
 send_started REAL, message_id TEXT, receipt TEXT, readback_state TEXT,
 cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT
);
CREATE TABLE IF NOT EXISTS reminder_focus(scope TEXT PRIMARY KEY, draft_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reminder_jobs(task_id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reminder_notifications(outbox_id TEXT PRIMARY KEY,draft_id TEXT,revision INTEGER,kind TEXT NOT NULL);
"""
EDITABLE={"collecting","awaiting_confirmation","approved","failed_not_sent"}
HELP=("群提醒：直接说‘帮我在某群提醒某人某事’，或 /remind 加事项。"
      "先在私聊核对完整预览，确认后由原机器人发送。/remind 状态、/remind 取消、/remind 重试。"
      "首版只支持确认后立即发送；不支持定时、周期、@所有人。")
ERRORS={"REMINDER_EGRESS_NOT_CONFIGURED":"该群尚未登记为本轮提醒出站目标；已保留资料，需先核对准确群和人员。",
        "REMINDER_BOT_NOT_IN_GROUP":"原机器人不在该群，不能发送；不会自动加群或换用个人身份。",
        "REMINDER_MEMBER_LEFT_GROUP":"待 @ 的人员已不在群中，需要重新核对目标。",
        "REMINDER_TARGET_CHANGED":"群、人员显示信息或发送身份已变化，需要重新展示准确预览。",
        "REMINDER_NO_LOOKUP":"平台未返回消息 ID，且当前不能定向查询原发送记录；未查明是否发出，不能重发。",
        "REMINDER_IMMEDIATE_WINDOW_ENDED":"立即执行窗口已结束，未开始发送；可手动重试，不会延到以后悄悄发送。"}

class ReminderService:
    def __init__(self,gateway):
        self.g,self.s=gateway,gateway.store
        self.port=ReminderPort(gateway.config,gateway.api.client) if hasattr(gateway.api,"client") else MissingReminderPort()
        with self.s.lock:self.s.conn.executescript(SCHEMA)

    @property
    def enabled(self):return self.g.config.reminders_enabled

    def focused(self,row):
        r=self.s.rows("SELECT d.* FROM reminder_focus f JOIN reminder_drafts d ON d.id=f.draft_id WHERE f.scope=? AND d.expires>?",
                      (scope_of(row),self.s.clock()))
        return r[0] if r else None

    def get(self,row,ident=None):
        if row["user"]!=self.g.config.owner or row["chat_type"]!="p2p":raise BoundaryError("REMINDER_OWNER_ONLY")
        if ident:
            r=self.s.rows("SELECT * FROM reminder_drafts WHERE scope=? AND (id=? OR marker=?) AND expires>?",
                          (scope_of(row),ident,ident.removeprefix("R-"),self.s.clock()))
        else:
            f=self.focused(row)
            if f:return f
            r=self.s.rows("SELECT * FROM reminder_drafts WHERE scope=? AND expires>? ORDER BY rowid DESC LIMIT 1",
                          (scope_of(row),self.s.clock()))
        if not r:raise BoundaryError("REMINDER_NOT_FOUND_OR_EXPIRED")
        return r[0]

    def notify(self,row,text=None,*,draft=None,card=None,kind="status"):
        if draft:row=dict(row,expires=min(row["expires"],draft["expires"]))
        if row["expires"]<=self.s.clock():return None
        out=self.s.add_outbox(row,text=text,card=card,private=True)
        self.s.execute("INSERT INTO reminder_notifications VALUES(?,?,?,?)",
                       (out,draft["id"] if draft else None,draft["revision"] if draft else None,kind))
        return out

    def control(self,text):
        raw=text.strip();explicit=raw.startswith("/remind")
        if explicit:raw=raw[len("/remind"):].strip()
        choices=(("确认发送","confirm"),("取消提醒","cancel"),("提醒状态","status"))
        if explicit:choices+=( ("取消","cancel"),("状态","status"),("重试","retry"),("预览","preview"),("现在","now"),("选择","choose"),("修改","modify") )
        if raw in ("改为现在提醒","改为现在发送","改成现在提醒"):return {"action":"now"}
        for word,action in choices:
            if raw==word or raw.startswith(word+" "):
                rest=raw[len(word):].strip();match=re.fullmatch(r"(?:R-)?([a-f0-9]{16}|[a-f0-9]{32})(?:\s+v(\d+))?",rest)
                result={"action":action}
                if match:
                    result["id"]=match[1]
                    if match[2]:result["revision"]=int(match[2])
                elif action=="choose" and rest.isdigit():result["choice"]=int(rest)
                elif rest:return None
                return result
        if self.enabled and raw=="取消" and not explicit:return {"action":"cancel"}
        return None

    def wants(self,row,text):
        if not self.enabled:return False
        if text.startswith(("/doc","/progress","/chat","/menu","/retry","/resend","/new")):
            return False
        return natural_start(text) or text.strip().startswith(("/remind","确认发送","提醒状态","取消提醒")) or bool(self.focused(row))

    def suspend_focus(self,row):
        self.s.execute("DELETE FROM reminder_focus WHERE scope=?",(scope_of(row),))

    def ingest(self,payload):
        """Only validate platform identity, bind a control and persist. No network."""
        if not self.enabled:return False
        try:
            h,e=payload["header"],payload["event"]
            c=self.g.config
            if h["app_id"]!=c.app_id or h["tenant_key"]!=c.tenant_key:return False
            row={"app":c.app_id,"tenant":c.tenant_key,"event_id":h["event_id"],"chat_type":"p2p"}
            if h["event_type"]=="im.message.receive_v1":
                sender,m=e["sender"],e["message"]
                if sender["sender_type"]!="user" or sender.get("tenant_key")!=c.tenant_key or sender["sender_id"]["open_id"]!=c.owner or m["chat_type"]!="p2p":return False
                stamp=int(m["create_time"])/1000
                if stamp>self.s.clock()+60 or stamp+86400<=self.s.clock():return False
                text=normalize_message(m,bot_open_id=c.bot_open_id,max_chars=2000).text.strip()
                row.update(user=c.owner,chat=m["chat_id"],message_id=m["message_id"],source_time=stamp,
                           kind="reminder",body=text,source_message=m.get("parent_id") or m.get("root_id"))
                action=self.control(text)
            elif h["event_type"]=="card.action.trigger":
                v=e["action"]["value"]
                if e["operator"]["open_id"]!=c.owner or v.get("flow")!="reminder":return False
                row.update(user=c.owner,chat=e["context"]["open_chat_id"],message_id=None,
                           source_time=self.s.clock(),kind="reminder_action",source_message=e["context"]["open_message_id"])
                action={k:v[k] for k in ("action","id","revision","hash","nonce")}
                if action["action"] not in ("confirm","cancel","modify"):return False
            else:return False
            if action:
                row["kind"]="reminder_action"
                # Bind plain confirmation now, not after an intervening edit/model run.
                try:
                    d=self.get(row,action.get("id"))
                    if "revision" not in action:
                        pending=self.s.rows("SELECT id FROM reminder_drafts WHERE scope=? AND state='awaiting_confirmation' AND expires>?",
                                            (scope_of(row),self.s.clock()))
                        if action["action"]=="confirm" and d["state"]=="awaiting_confirmation":
                            focus=self.focused(row)
                            exact_reply=row.get("source_message")==d["preview_message"] and bool(d["preview_message"])
                            if (len(pending)!=1 or not d["preview_sent"] or self.s.clock()-d["preview_sent"]>600
                                    or row["source_time"]<d["preview_sent"]
                                    or not exact_reply and (not focus or focus["id"]!=d["id"])):
                                action["ambiguous"]=True
                        action["revision"]=d["revision"]
                    action.setdefault("id",d["id"])
                    if row.get("source_message") and row["source_message"]!=d["preview_message"]:action["ambiguous"]=True
                except BoundaryError:
                    if h["event_type"]=="card.action.trigger":return False
                    action["missing"]=True
                if h["event_type"]=="card.action.trigger" and action.get("ambiguous"):return False
                row["body"]=canonical(action)
            return self.s.put(row,on_insert=self.observe)
        except (KeyError,ValueError,TypeError):return False

    def observe(self,conn,row,expires):
        action=json.loads(row["body"]) if row["kind"]=="reminder_action" else None
        d=conn.execute("SELECT d.* FROM reminder_focus f JOIN reminder_drafts d ON d.id=f.draft_id WHERE f.scope=? AND d.expires>?",
                       (scope_of(row),self.s.clock())).fetchone()
        if action and action.get("id"):
            d=conn.execute("SELECT * FROM reminder_drafts WHERE scope=? AND (id=? OR marker=?) AND expires>?",
                           (scope_of(row),action["id"],action["id"].removeprefix("R-"),self.s.clock())).fetchone()
        if not d:return
        if action:
            valid=(not action.get("missing") and not action.get("ambiguous") and action.get("revision")==d["revision"]
                   and ("nonce" not in action or action["nonce"]==d["nonce"] and action.get("hash")==d["content_hash"] and row.get("source_message")==d["preview_message"]))
            if valid and action["action"]=="modify" and d["state"] in EDITABLE:
                conn.execute("UPDATE reminder_drafts SET state='collecting',revision=revision+1,approved_hash=NULL,approval=NULL,preview_message=NULL WHERE id=?",(d["id"],))
                action.update(revision=d["revision"]+1,preinvalidated=True)
                # This trusted field is written after platform validation; it is
                # never accepted from the incoming card value.
                conn.execute("UPDATE inbox SET body=? WHERE app=? AND tenant=? AND event_id=?",(canonical(action),row["app"],row["tenant"],row["event_id"]))
            if valid and action["action"]=="cancel":
                if d["state"] in EDITABLE:
                    conn.execute("UPDATE reminder_drafts SET state='cancelled',approved_hash=NULL,approval=NULL,cancel_requested=1 WHERE id=?",(d["id"],))
                elif d["state"] in ("sending","unknown","sent"):
                    conn.execute("UPDATE reminder_drafts SET cancel_requested=1 WHERE id=?",(d["id"],))
            return
        if natural_start(row["body"]):return
        if d["state"] in EDITABLE:
            conn.execute("UPDATE reminder_drafts SET revision=revision+1,state='collecting',payload=NULL,content_hash=NULL,approved_hash=NULL,approval=NULL,preview_message=NULL WHERE id=?",(d["id"],))

    def create(self,row,text):
        ident=uuid.uuid4().hex
        origin={k:row[k] for k in ("app","tenant","user","chat","chat_type","expires")}
        origin["origin_message_id"]=row["message_id"]
        self.s.execute("INSERT INTO reminder_drafts(id,marker,scope,origin,created,anchor,expires,revision,state,turns,fields,selected,candidates) VALUES(?,?,?,?,?,?,?,1,'collecting',?,'{}','{}','{}')",
            (ident,ident[:16],scope_of(row),canonical(origin),self.s.clock(),min(self.s.clock(),row["expires"]-86400),row["expires"],canonical([text])))
        self.s.execute("INSERT INTO reminder_focus VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET draft_id=excluded.draft_id",(scope_of(row),ident))
        return self.get(row,ident)

    def release(self,d):
        self.s.execute("DELETE FROM reminder_focus WHERE scope=? AND draft_id=?",(d["scope"],d["id"]))
        origin=json.loads(d["origin"])
        if not self.s.selection(origin)["route"]:
            self.s.execute("UPDATE bridge_mode SET mode='chat' WHERE scope=?",(d["scope"],))

    def queue(self,row,d):
        row=dict(row,expires=min(row["expires"],d["expires"]))
        task=self.s.enqueue(row,"remind",acknowledgement=False)
        self.s.execute("INSERT INTO reminder_jobs VALUES(?,?,?)",(task,d["id"],d["revision"]))
        self.notify(row,"已收到提醒资料，正在核对；完整预览确认前不会向群发送。",draft=d)

    def status(self,d):
        if d["state"]=="sent":
            p=json.loads(d["payload"]);r=json.loads(d["receipt"] or "{}")
            text=f"已由 {p['bot']['name']} 发送到 {p['group']['name']}，@ "+"、".join(x["name"] for x in p["people"])
            text+="。\n消息 ID："+str(d["message_id"])+"\n"+("已读回核对发送者、群、完整正文和提及人员。" if d["readback_state"]=="verified" else "已发送，回读待核实；不会再次群发送。")
            if r.get("sent_at"):
                text+="\n"+("发送时间：" if d["readback_state"]=="verified" else "成功回执时间：")+datetime.fromtimestamp(r["sent_at"],TZ).strftime("%Y-%m-%d %H:%M:%S")+"（北京时间）"
            if r.get("link"):text+="\n查看消息："+r["link"]
            if d["cancel_requested"]:text+="\n取消发生在发送执行后；原群消息保留，没有撤回。"
            return text+"\n这只代表机器人已发送，不代表工程师已读或完成。"
        labels={"collecting":"待补充或核对资料","awaiting_confirmation":"待确认完整预览","approved":"已确认待执行",
                "sending":"发送中；取消只能提出请求，不能保证拦住已发出的网络请求","unknown":"结果待核实；不会盲目重发",
                "failed_not_sent":"明确未发，可在原有效期内 /remind 重试","cancelled":"已取消，旧确认不再有效","expired":"已过期，不能发送"}
        if d["state"]=="failed_not_sent" and not d["approved_hash"]:labels["failed_not_sent"]="明确未发，需要修改或重新预览"
        return f"提醒 R-{d['marker']} / v{d['revision']}："+labels.get(d["state"],d["state"])+("。"+ERRORS.get(d["error"],d["error"]) if d["error"] else "")

    def handle(self,row):
        if not self.enabled:raise BoundaryError("REMINDER_DISABLED")
        if row["kind"]=="reminder_action":return self.handle_action(row,json.loads(row["body"]))
        text=row["body"].strip();d=self.focused(row)
        if natural_start(text):
            text=text.removeprefix("/remind").strip()
            explicit_new=text.startswith("新建 ")
            if not explicit_new:
                for previous in self.s.rows("SELECT * FROM reminder_drafts WHERE scope=? AND state IN ('sending','unknown') AND expires>?",(scope_of(row),self.s.clock())):
                    prior=json.loads(previous["turns"])
                    if prior and prior[0]==text:
                        self.notify(row,"这条提醒已有发送结果待核实，重复原请求不会建立第二次发送。\n"+self.status(previous),draft=previous)
                        return
            d=self.create(row,text)
        elif not d:
            self.notify(row,HELP);return
        else:
            if d["state"] not in EDITABLE:self.notify(row,self.status(d),draft=d);return
            turns=json.loads(d["turns"])
            if text in turns:self.notify(row,"这份补充已记录，不重复生成。",draft=d);return
            if sum(map(len,turns))+len(text)>6000:raise BoundaryError("REMINDER_INPUT_LIMIT")
            turns.append(text)
            self.s.execute("UPDATE reminder_drafts SET turns=?,state='collecting',approved_hash=NULL,approval=NULL WHERE id=?",(canonical(turns),d["id"]))
            d=self.get(row,d["id"])
        self.queue(row,d)

    def handle_action(self,row,a):
        if a.get("missing"):self.notify(row,"没有找到仍有效的提醒。"+HELP);return
        d=self.get(row,a.get("id"))
        if a.get("ambiguous"):
            self.notify(row,"不能确定你确认的是哪一版。请点击准确预览中的确认按钮，或回复‘确认发送 R-编号 v版本’。");return
        if a.get("revision")!=d["revision"] or ("nonce" in a and not a.get("preinvalidated") and (a["nonce"]!=d["nonce"] or a.get("hash")!=d["content_hash"] or row.get("source_message")!=d["preview_message"])):
            self.notify(row,"这条预览已失效，请使用最新完整预览。",draft=d);return
        action=a["action"]
        if action=="confirm":
            if self.s.meta("reminder_pause"):
                self.notify(row,"提醒发送暂时暂停，需先核实上一次异常；普通聊天和文档助手仍可用。",draft=d);return
            if d["state"]!="awaiting_confirmation":self.notify(row,self.status(d),draft=d);return
            if not d["preview_message"] or not d["payload"] or fingerprint(json.loads(d["payload"]))!=d["content_hash"]:
                raise BoundaryError("REMINDER_PREVIEW_NOT_DELIVERED")
            delivered=self.s.rows("SELECT body,message_id,state FROM outbox WHERE id=?",(d["preview_outbox"],))
            if (not delivered or delivered[0]["state"]!="sent" or delivered[0]["message_id"]!=d["preview_message"]
                    or json.loads(delivered[0]["body"])["elements"][1]["actions"][0]["value"]["hash"]!=d["content_hash"]):
                raise BoundaryError("REMINDER_PREVIEW_CHANGED")
            approved={"user":row["user"],"event_id":row["event_id"],"time":self.s.clock(),"version":d["revision"],"hash":d["content_hash"]}
            self.s.execute("UPDATE reminder_drafts SET state='approved',approved_hash=content_hash,approval=? WHERE id=? AND revision=? AND state='awaiting_confirmation' AND expires>?",
                           (canonical(approved),d["id"],d["revision"],self.s.clock()))
            self.notify(row,self.status(self.get(row,d["id"])),draft=d);return
        if action=="cancel":
            self.notify(row,self.status(d),draft=d);self.release(d);return
        if action=="status":
            if d["state"] in ("unknown","sent"):self.reconcile_one(d)
            self.notify(row,self.status(self.get(row,d["id"])),draft=d);return
        if action=="retry":
            if d["state"]!="failed_not_sent" or not d["approved_hash"] or d["approved_hash"]!=d["content_hash"]:
                self.notify(row,self.status(d),draft=d);return
            approval=json.loads(d["approval"]);approval["retry_requested_at"]=self.s.clock()
            self.s.execute("UPDATE reminder_drafts SET state='approved',approval=?,error=NULL WHERE id=? AND state='failed_not_sent' AND expires>?",(canonical(approval),d["id"],self.s.clock()))
            self.notify(row,"已按原批准的准确目标和正文记录重试；沿用原请求键。",draft=d);return
        if action=="modify":
            if d["state"] not in EDITABLE:self.notify(row,self.status(d),draft=d);return
            if not a.get("preinvalidated"):
                self.s.execute("UPDATE reminder_drafts SET state='collecting',revision=revision+1,approved_hash=NULL,approval=NULL,preview_message=NULL WHERE id=?",(d["id"],))
            self.s.execute("INSERT INTO reminder_focus VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET draft_id=excluded.draft_id",(d["scope"],d["id"]))
            self.notify(row,"请直接发送修改内容；会生成新预览，旧确认无效。",draft=d);return
        if action in ("now","preview","choose"):
            if d["state"] not in EDITABLE:self.notify(row,self.status(d),draft=d);return
            fields=json.loads(d["fields"]);selected=json.loads(d["selected"])
            if action=="now":fields["delivery_mode"]="immediate"
            if action=="choose":
                options=json.loads(d["candidates"]).get("options",[]);i=a.get("choice",0)-1
                if not 0<=i<len(options):self.notify(row,"请按当前候选列表回复 /remind 选择 序号。",draft=d);return
                choice=options[i]
                if choice["field"]=="group":selected={"group_id":choice["value"]["id"]}
                else:selected.setdefault("people",{})[choice["query"]]=choice["value"]["id"]
            self.s.execute("UPDATE reminder_drafts SET fields=?,selected=?,revision=revision+1,state='collecting',approved_hash=NULL,approval=NULL WHERE id=?",(canonical(fields),canonical(selected),d["id"]))
            self.s.execute("INSERT INTO reminder_focus VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET draft_id=excluded.draft_id",(d["scope"],d["id"]))
            self.queue(row,self.get(row,d["id"]))

    def resolve(self,fields,selected):
        missing=[];options=[]
        if not fields.get("group_query"):missing.append("请提供准确群名或群链接。")
        if not fields.get("people_queries"):missing.append("请指定需要 @ 的工程师；不会改成 @ 所有人。")
        elif any(q.strip() in {"大家","所有人","全体","全员","全部工程师","@all","all"} for q in fields["people_queries"]):
            missing.append("请把泛称或全员对象补充为具体工程师名单；已指名的信息会保留，首版不发送 @ 所有人。")
        if not fields.get("body"):missing.append("请补充要提醒的事项正文。")
        if fields.get("delivery_mode")!="immediate":missing.append("首版尚不支持未来或定时发送。草稿已保留；如要改为现在提醒，请回复‘改为现在提醒’。")
        if missing:return None,missing,options
        if not self.port.policy()["outbound_group_ids"]:
            return None,["已记录群和人员查询。当前尚未登记本轮真实出站群，待核对准确目标后形成预览；不会向群发送探测消息。"],options
        if selected.get("group_id"):groups=[self.port.group(selected["group_id"])]
        else:groups=self.port.groups(fields["group_query"])
        if not groups:return None,["未在本轮提醒出站范围内找到该群，请核对准确群名或链接。"],options
        if len(groups)!=1:
            options=[{"field":"group","value":g} for g in groups]
            return None,["群名存在多个候选，请选择准确群。"],options
        group=groups[0];members=self.port.members(group["id"]);people=[]
        for query in fields["people_queries"]:
            chosen=selected.get("people",{}).get(query)
            exact=[m for m in members if m["id"]==chosen] if chosen else [m for m in members if m["id"]==query or m["name"]==query]
            if len(exact)==1:people.append(exact[0]);continue
            fuzzy=exact or [m for m in members if query in m["name"] or re.sub(r"工程师$|工$","",query) in m["name"]]
            if not fuzzy:missing.append("该群内未找到‘"+query+"’，请提供可准确识别的成员名称。");continue
            options.extend({"field":"person","query":query,"value":m} for m in fuzzy)
        if options:missing.append("请确认人员候选，不能凭同名或简称猜测。")
        if missing:return None,missing,options
        return {"group":group,"people":people,"bot":self.port.bot()},[],[]

    def generate(self,task,started):
        jobs=self.s.rows("SELECT * FROM reminder_jobs WHERE task_id=?",(task["id"],))
        if not jobs:return False
        job=jobs[0];d=self.get(task,job["draft_id"])
        if not self.enabled or d["revision"]!=job["revision"] or d["state"]!="collecting":raise BoundaryError("REMINDER_SUPERSEDED")
        turns=json.loads(d["turns"]);fields=json.loads(d["fields"]);selected=json.loads(d["selected"]);result=None
        if not any(turns):
            fields={"intent":"reminder","group_query":None,"people_queries":[],"body":None,"delivery_mode":"immediate"}
            d=dict(d,parsed_count=len(turns))
        if d["parsed_count"]>=len(turns):
            self.s.execute("UPDATE tasks SET model='python:reminder-resolution' WHERE id=?",(task["id"],))
        if d["parsed_count"]<len(turns):
            result=self.g.provider.complete(prompt(turns,fields,d["anchor"]),run_id=task["run_id"],timeout=min(120,d["expires"]-self.s.clock()),on_start=started)
            updated=parse_fields(result.text,turns,fields,d["anchor"])
            if updated["intent"]=="unrelated":
                self.s.execute("UPDATE reminder_drafts SET turns=? WHERE id=?",(canonical(turns[:d["parsed_count"]]),d["id"]))
                self.notify(task,"这条内容没有改变提醒。可补充提醒资料，或 /chat 返回普通聊天。",draft=d)
                self.finish_job(task,result);return True
            if updated.get("group_query")!=fields.get("group_query"):selected={}
            elif updated.get("people_queries")!=fields.get("people_queries"):selected.pop("people",None)
            fields=updated
        try:target,missing,options=self.resolve(fields,selected)
        except BoundaryError as exc:target,missing,options=None,[ERRORS.get(str(exc),"目标核对未完成："+str(exc))],[]
        fresh=self.get(task,d["id"])
        if fresh["revision"]!=job["revision"] or fresh["state"]!="collecting":raise BoundaryError("REMINDER_SUPERSEDED")
        if not target:
            self.s.execute("UPDATE reminder_drafts SET fields=?,selected=?,parsed_count=?,candidates=? WHERE id=? AND revision=?",
                (canonical(fields),canonical(selected),len(turns),canonical({"options":options}),d["id"],d["revision"]))
            message="\n".join(missing)
            for i,option in enumerate(options,1):message+=f"\n{i}. "+option.get("query","")+" → "+option["value"]["name"]+"（"+option["value"]["id"][-8:]+"）"
            if options:message+="\n回复 /remind 选择 序号；一次选择一个候选。"
            self.notify(task,message,draft=d)
        else:
            selected={"group_id":target["group"]["id"],"people":{q:p["id"] for q,p in zip(fields["people_queries"],target["people"])}}
            payload=normalized_payload(d["id"],target["bot"],target["group"],target["people"],fields["body"])
            digest=fingerprint(payload);nonce=uuid.uuid4().hex
            with self.s.tx() as conn:
                n=conn.execute("UPDATE reminder_drafts SET state='awaiting_confirmation',fields=?,selected=?,parsed_count=?,candidates='{}',payload=?,content_hash=?,nonce=?,preview_message=NULL,preview_sent=NULL,request_key=?,attempts=0,error=NULL WHERE id=? AND revision=? AND state='collecting' AND expires>?",
                    (canonical(fields),canonical(selected),len(turns),canonical(payload),digest,nonce,uuid.uuid4().hex,d["id"],d["revision"],self.s.clock())).rowcount
                if not n:raise BoundaryError("REMINDER_SUPERSEDED")
            card=preview_card(d["id"],d["revision"],payload,digest,nonce,d["expires"])
            out=self.notify(task,draft=d,card=card,kind="preview")
            self.s.execute("UPDATE reminder_drafts SET preview_outbox=? WHERE id=? AND revision=?",(out,d["id"],d["revision"]))
        self.finish_job(task,result or Result("","python:reminder-resolution",0));return True

    def finish_job(self,task,result):
        self.s.execute("UPDATE tasks SET state='completed',model=?,elapsed=?,pgid=NULL,process_identity=NULL WHERE id=? AND state='running'",
                       (result.model,result.elapsed,task["id"]))

    def valid_notification(self,row):
        notices=self.s.rows("SELECT * FROM reminder_notifications WHERE outbox_id=?",(row["id"],))
        if not notices:return None
        n=notices[0]
        if not self.enabled:return False
        if n["kind"]!="preview":return True
        return bool(self.s.rows("SELECT 1 FROM reminder_drafts WHERE id=? AND revision=? AND state='awaiting_confirmation' AND expires>?",
                               (n["draft_id"],n["revision"],self.s.clock())))

    def delivered(self,conn,row,message_id):
        conn.execute("UPDATE reminder_drafts SET preview_message=?,preview_sent=? WHERE preview_outbox=? AND state='awaiting_confirmation'",(message_id,self.s.clock(),row["id"]))

    def _internal(self,ident):
        return self.s.rows("SELECT * FROM reminder_drafts WHERE id=?",(ident,))[0]

    def dispatch_one(self):
        if not self.enabled or self.s.meta("reminder_pause"):return False
        rows=self.s.rows("SELECT * FROM reminder_drafts WHERE state='approved' AND expires>? ORDER BY created LIMIT 1",(self.s.clock(),))
        if not rows:return False
        d=rows[0];origin=json.loads(d["origin"]);payload=json.loads(d["payload"])
        try:
            approval=json.loads(d["approval"] or "{}")
            if self.s.clock()-approval.get("retry_requested_at",approval.get("time",0))>60:
                raise BoundaryError("REMINDER_IMMEDIATE_WINDOW_ENDED")
            if not self.g.authorized(origin) or d["approved_hash"]!=d["content_hash"] or fingerprint(payload)!=d["content_hash"]:
                raise BoundaryError("REMINDER_APPROVAL_INVALID")
            self.port.refresh(payload)
        except Exception as exc:
            code=str(exc) if isinstance(exc,BoundaryError) else "REMINDER_PREFLIGHT_UNAVAILABLE"
            invalid=code in ("REMINDER_TARGET_CHANGED","REMINDER_MEMBER_LEFT_GROUP","REMINDER_APPROVAL_INVALID")
            self.s.execute("UPDATE reminder_drafts SET state='failed_not_sent',error=?,approved_hash=CASE WHEN ? THEN NULL ELSE approved_hash END WHERE id=? AND state='approved'",(code,int(invalid),d["id"]))
            self.notify(origin,self.status(self._internal(d["id"])),draft=d);self.release(d);return True
        if not self.s.execute("UPDATE reminder_drafts SET state='sending',attempts=attempts+1,send_started=?,error=NULL WHERE id=? AND revision=? AND state='approved' AND approved_hash=content_hash AND expires>? AND cancel_requested=0",
                              (self.s.clock(),d["id"],d["revision"],self.s.clock())):return True
        def guard():
            return self.enabled and self.g.authorized(origin) and bool(self.s.rows("SELECT 1 FROM reminder_drafts WHERE id=? AND revision=? AND state='sending' AND expires>? AND cancel_requested=0",
                                                    (d["id"],d["revision"],self.s.clock())))
        try:
            receipt=self.port.send(payload,d["request_key"],guard)
            if not receipt.get("message_id"):raise SendUnknown("REMINDER_RECEIPT_MISSING")
            self.s.execute("UPDATE reminder_drafts SET state='sent',message_id=?,receipt=?,readback_state='pending' WHERE id=? AND state='sending'",
                           (receipt["message_id"],canonical(receipt),d["id"]))
            self.reconcile_one(self._internal(d["id"]))
        except SendRejected as exc:
            self.s.execute("UPDATE reminder_drafts SET state=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'failed_not_sent' END,error=? WHERE id=? AND state='sending'",(str(exc),d["id"]))
        except Exception:
            self.s.execute("UPDATE reminder_drafts SET state='unknown',readback_state='pending',error='REMINDER_SEND_UNKNOWN' WHERE id=? AND state='sending'",(d["id"],))
            self.reconcile_one(self._internal(d["id"]))
        latest=self._internal(d["id"]);self.notify(origin,self.status(latest),draft=latest);self.release(latest)
        return True

    def reconcile_one(self,d):
        if d["state"] not in ("unknown","sent") or not d["payload"] or d["expires"]<=self.s.clock():return
        try:
            payload=json.loads(d["payload"])
            message=self.port.reconcile(payload,d["request_key"],d["send_started"],d["message_id"])
            if not message or not verify_message(payload,message):
                if not d["message_id"] and not self.port.policy()["reconcile_own_attempts"]:
                    self.s.execute("UPDATE reminder_drafts SET error='REMINDER_NO_LOOKUP' WHERE id=?",(d["id"],))
                return
            receipt=json.loads(d["receipt"] or "{}")
            receipt.update(message_id=message["message_id"],sent_at=message["created_at"],link=message.get("link"))
            self.s.execute("UPDATE reminder_drafts SET state='sent',message_id=?,receipt=?,readback_state='verified',error=NULL WHERE id=? AND state IN ('sent','unknown')",
                           (message["message_id"],canonical(receipt),d["id"]))
        except Exception:
            self.s.execute("UPDATE reminder_drafts SET readback_state='pending' WHERE id=?",(d["id"],))

    def operational_status(self):
        from .reminder_content import SOURCE_SHA256 as content_sha
        from .reminder_feishu import SOURCE_SHA256 as port_sha
        value={"enabled":self.enabled,"version":VERSION,"source_sha256":{
            "reminder.py":SOURCE_SHA256,"reminder_content.py":content_sha,"reminder_feishu.py":port_sha},
            "states":self.s.rows("SELECT state,count(*) AS count FROM reminder_drafts GROUP BY state"),
            "pause":self.s.meta("reminder_pause")}
        try:value["outbound_groups"]=len(self.port.policy()["outbound_group_ids"])
        except Exception:value["policy_error"]="REMINDER_POLICY_INVALID"
        return value

    def recover(self):
        self.s.execute("UPDATE reminder_drafts SET state='unknown',readback_state='pending',error='REMINDER_RESTART_SEND_UNKNOWN' WHERE state='sending'")
        if self.enabled:
            for d in self.s.rows("SELECT * FROM reminder_drafts WHERE state IN ('unknown','sent') AND readback_state='pending' AND expires>?",(self.s.clock(),)):
                self.reconcile_one(d)
                origin=json.loads(d["origin"])
                self.notify(origin,self.status(self._internal(d["id"])),draft=d)


    def cleanup(self):
        now=self.s.clock()
        self.s.execute("DELETE FROM reminder_focus WHERE draft_id IN (SELECT id FROM reminder_drafts WHERE expires<=?)",(now,))
        self.s.execute("UPDATE reminder_drafts SET state='expired',turns='[]',fields='{}',selected='{}',candidates='{}',payload=NULL,content_hash=NULL,nonce=NULL,approved_hash=NULL,approval=NULL,receipt=NULL WHERE expires<=?",(now,))
