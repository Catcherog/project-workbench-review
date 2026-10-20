"""Four synthetic turns via the existing authorized user -> bot p2p entry.

Only selected synthetic message IDs are read back. Private IDs/receipts remain in
input/; the public evidence contains synthetic prose, states and byte hashes only.
"""
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from fs_agent.config import Config

b=Path(__file__).resolve().parent
run=sys.argv[1]
private=b/"input"/run; private.mkdir(mode=0o700,exist_ok=True)
public=b/"evidence"/run;public.mkdir(parents=True,exist_ok=True)
cfg=Config.load(Path.home()/".local/share/local-qwen-feishu/poc/config/environment.json")
target=json.loads((b/"input/live-target.json").read_text())
db=sqlite3.connect("file:"+str(cfg.root/"state/gateway.sqlite3")+"?mode=ro",uri=True)
db.row_factory=sqlite3.Row

def dump(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
def cli(args):
    r=subprocess.run(["lark-cli","--profile",target["profile"],*args],capture_output=True,text=True,timeout=45)
    value=json.loads(r.stdout)
    if r.returncode or not value.get("ok"): raise RuntimeError("CLI_CALL_FAILED:"+str(value.get("error",{})))
    return value

def messages(ids):
    return cli(["im","+messages-mget","--as","user","--message-ids",",".join(ids),"--no-reactions","--json"])

def send(text,label):
    path=private/(label+"-send.json")
    if path.exists(): return json.loads(path.read_text())["data"]["message_id"]
    data=cli(["im","+messages-send","--as","user","--chat-id",target["chat_id"],"--text",text,
              "--idempotency-key",uuid.uuid4().hex,"--json"])
    dump(path,data)
    return data["data"]["message_id"]

turns=[
    "/doc logic test 合成验收。电机A：均值判据≥16 A；处理后记录18 A以上。另记静态功耗37 mA。",
    "补充电机A：上述处理后18 A以上是均值，样本范围我查一下。",
    "补充电机A：上述均值的样本范围是A1、A2、A3，与该均值判据对应，版本和条件相同。",
    "更正电机A：静态记录的物理量应为电流，单位mA正确，数值37不变。",
]

if not list(private.glob("*-send.json")):
    assert not db.execute("SELECT 1 FROM tasks WHERE state IN ('queued','running','stop_unknown')").fetchall()
    assert not db.execute("SELECT 1 FROM logic_drafts WHERE expires>? AND state!='cancelled'",(time.time(),)).fetchall(), "ACTIVE_DRAFT"

for turn,text in enumerate(turns,1):
    result_path=public/f"turn-{turn}.json"
    if result_path.exists(): continue
    mid=send(text,f"turn-{turn}")
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        inbox=db.execute("SELECT * FROM inbox WHERE message_id=?",(mid,)).fetchone()
        if inbox:
            assert inbox["user"]==cfg.owner and inbox["chat"]==target["chat_id"] and inbox["chat_type"]=="p2p"
            task=db.execute("SELECT * FROM tasks WHERE seq=? ORDER BY created DESC LIMIT 1",(inbox["seq"],)).fetchone()
            if task and task["state"] not in ("queued","running"):
                if task["state"]!="completed":
                    dump(private/f"turn-{turn}-failure.json",dict(task))
                    raise RuntimeError("ENTRY_TASK_"+task["state"]+":"+str(task["error"]))
                outbox=db.execute("SELECT * FROM outbox WHERE task_id=?",(task["id"],)).fetchall()
                if outbox and all(o["state"]=="sent" for o in outbox) and any(o["kind"]=="file" for o in outbox):break
        time.sleep(2)
    else: raise RuntimeError("ENTRY_OR_DELIVERY_TIMEOUT")
    d=db.execute("SELECT d.* FROM logic_drafts d JOIN logic_jobs j ON j.draft_id=d.id WHERE j.task_id=?",(task["id"],)).fetchone()
    ledger=json.loads(d["answers"]);analysis=json.loads(d["analysis"])
    meta=json.loads(d["rules"])
    assert meta["version"]=="doc-logic-r1.2"
    for key,filename in (("implementation_sha256","doc_logic.py"),("workflow_sha256","logic_service.py"),("question_state_sha256","question_state.py")):
        assert meta[key]==hashlib.sha256((b.parents[1]/"src/fs_agent"/filename).read_bytes()).hexdigest(), "RUNTIME_SOURCE_MISMATCH"
    readback=messages([mid]+[o["message_id"] for o in outbox])
    dump(private/f"turn-{turn}-messages.json",readback)
    got={m["message_id"]:m for m in readback["data"]["messages"]}
    assert mid in got and all(o["message_id"] in got for o in outbox)
    assert all(m["chat_id"]==target["chat_id"] for m in got.values())
    assert got[mid]["sender"]["id"]==cfg.owner
    for o in outbox:
        assert got[o["message_id"]]["sender"]["id"] in (cfg.app_id,cfg.bot_open_id)
    file_row=next(o for o in outbox if o["kind"]=="file")
    file_message=got[file_row["message_id"]]
    # The high-level mget renders file content as display text. Use the raw
    # read endpoint for this already verified message's structured file key.
    raw_file=cli(["api","GET","/open-apis/im/v1/messages/"+file_row["message_id"],"--as","user","--json"])
    dump(private/f"turn-{turn}-file-raw.json",raw_file)
    raw_message=raw_file["data"]["items"][0]
    assert raw_message["message_id"]==file_row["message_id"] and raw_message["chat_id"]==target["chat_id"]
    file_key=json.loads(raw_message["body"]["content"])["file_key"]
    download=private/f"turn-{turn}.md"
    receipt=cli(["im","+messages-resources-download","--as","user","--message-id",file_row["message_id"],
                 "--file-key",file_key,"--type","file","--output",str(download),"--json"])
    dump(private/f"turn-{turn}-download.json",receipt)
    binary=download.read_bytes()
    assert binary==d["content"].encode(), "PLATFORM_BYTES_DIFFER"
    (public/f"turn-{turn}.md").write_bytes(binary)
    states={q["gap"]:q["status"] for q in ledger.values()}
    expected=[{"statistic_scope":"unanswered","quantity_unit":"unanswered"},
              {"statistic_scope":"partial","quantity_unit":"unanswered"},
              {"statistic_scope":"resolved","quantity_unit":"unanswered"},
              {"statistic_scope":"resolved","quantity_unit":"resolved"}][turn-1]
    assert states==expected,(states,expected)
    if turn==2: assert not any("是否为均值" in q["ask"] for q in analysis["questions"])
    if turn==3: assert len(analysis["questions"])==1 and analysis["questions"][0]["gap"]=="quantity_unit"
    if turn==4: assert not analysis["questions"] and not analysis["gaps"]
    sources=json.loads(d["sources"])
    for s in sources:s.pop("origin",None)
    platform_text=[]
    for o in outbox:
        if o["kind"]=="text":
            # Only the synthetic response body; strip internal execution IDs.
            platform_text.append(o["body"].replace(task["id"],"<synthetic-task>"))
    dump(result_path,{"layer":"real_Feishu_entry_and_platform_readback","input":text,"turn":turn,
        "runtime":{"model":cfg.api_model,"digest":cfg.api_model_digest},"sources":sources,
        "question_states":ledger,"analysis":analysis,"review":json.loads(d["review"]),"rules":json.loads(d["rules"]),
        "task":{"state":task["state"],"elapsed":task["elapsed"]},"expected_states":expected,"actual_states":states,
        "platform":{"input_readback":True,"original_user_and_bot_verified":True,"read_objects":len(got),
                    "file_bytes":len(binary),"file_sha256":hashlib.sha256(binary).hexdigest(),"exact_bytes_equal":True,
                    "text_responses":platform_text},"business_write":False})
    print(json.dumps({"turn":turn,"states":states,"platform_bytes_equal":True},ensure_ascii=False),flush=True)

for label,text in (("finish","/doc 放弃"),("chat","/chat")):
    mid=send(text,label)
    for _ in range(30):
        r=db.execute("SELECT state FROM inbox WHERE message_id=?",(mid,)).fetchone()
        if r and r["state"]=="handled":break
        time.sleep(1)
    else: raise RuntimeError("CLEANUP_COMMAND_NOT_PROCESSED")
dump(public/"completion.json",{"turns":4,"draft_ended":True,"returned_to_chat":True,"no_mount":True,
     "GPT_reaudit":"待执行","user_acceptance":"待执行"})
print("original entry complete; synthetic draft ended",flush=True)
