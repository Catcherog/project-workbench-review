"""Real pinned Qwen with isolated directory/platform doubles. No group or DM sends."""
import json
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/"tests"))
from test_gateway import OfflineApi,event,drain
from test_reminder import Port
from fs_agent.config import Config
from fs_agent.qwen_provider import LocalQwenProvider
from fs_agent.gateway import Gateway
from fs_agent.store import Store
from fs_agent.embedded import EmbeddedPoC
from fs_agent.reminder_content import VERSION,fingerprint

CASES={
 "Q01":["帮我在合成研发群提醒工程师甲和工程师乙，今天17点前提交接口测试结果，完成后把链接发到群里。", "改为今天18点前提交，其他内容保持。"],
 "Q02":["提醒工程师甲提交接口测试结果。", "群是合成研发群。"],
 "Q03":["今天16点提醒工程师甲在合成研发群交报告。", "改为现在提醒"],
}

def main():
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    actual=Config.load(Path.home()/".local/share/local-qwen-feishu/poc/config/environment.json")
    provider=LocalQwenProvider(actual);pin=provider.pin()
    runtime={k:pin[k] for k in ("provider","base_url","model","model_digest","server_version")}
    summaries=[]
    for name in sys.argv[2:] or CASES:
        with tempfile.TemporaryDirectory(prefix="reminder-validate-") as tmp:
            root=Path(tmp)
            for path in ("state","tasks","artifacts"):(root/path).mkdir()
            cfg=replace(actual,root=root,app_id="cli_test",tenant_key="tenant_test",users=("ou_a","ou_b"),owner="ou_a",bot_open_id="ou_bot",chats=(),reminders_enabled=True)
            io=[]
            class Recorder:
                def complete(self,prompt,**kwargs):
                    r=provider.complete(prompt,**kwargs);io.append({"prompt":prompt,"output":r.text,"elapsed":r.elapsed});return r
            s=Store(root/"state/gateway.sqlite3");api=OfflineApi();g=Gateway(cfg,s,api,Recorder());g.reminders.port=Port(time.time);embedded=EmbeddedPoC(g)
            for turn,text in enumerate(CASES[name],1):
                io.clear();api.sent.clear();e=event(text,number=turn);e["event"]["message"]["create_time"]=str(int(time.time()*1000))
                assert embedded.ingest(e)==(True,True);g.receive_one();task=s.claim(1);assert task;g.run_task(task);drain(g)
                d=g.reminders.get(task);state=s.rows("SELECT state,error,model,elapsed FROM tasks WHERE id=?",(task["id"],))[0]
                record={"case":name,"turn":turn,"layer":"real_Qwen_with_isolated_platform","input":text,"runtime":runtime,"rule_version":VERSION,
                    "source_fingerprints":{f.name:fingerprint(f.read_text()) for f in (Path(__file__).parents[1]/"src/fs_agent").glob("reminder*.py")},
                    "result":state,"reminder_state":d["state"],"revision":d["revision"],"fields":json.loads(d["fields"]),
                    "payload":json.loads(d["payload"]) if d["payload"] else None,"private_outputs":[{"kind":x["kind"],"body":x["body"]} for x in api.sent],
                    "model_io":list(io),"group_sends":len(g.reminders.port.sent),"context_rows":len(s.rows("SELECT * FROM context"))}
                (out/f"{name}-{turn}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2))
                summary={"case":name,"turn":turn,"result":state,"reminder_state":d["state"]};summaries.append(summary);print(json.dumps(summary),flush=True)
                if state["state"]!="completed":break
            g.stop();s.close()
    (out/"summary.json").write_text(json.dumps(summaries,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
