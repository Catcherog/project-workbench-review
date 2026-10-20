"""Synthetic multi-turn acceptance through unchanged Gateway and the pinned real Qwen.

No Feishu sends. Each turn saves input, sources, states, actual model I/O and final prose.
"""
import json
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from fs_agent.config import Config
from fs_agent.qwen_provider import LocalQwenProvider
from fs_agent.gateway import Gateway
from fs_agent.store import Store
from fs_agent.doc_logic import load_rules

FLOWS = {
    "M01": [
        "/doc logic test 合成验收。电机A：均值判据≥16 A；处理后记录18 A以上。另记静态功耗37 mA。",
        "补充电机A：上述处理后18 A以上是均值，样本范围我查一下。",
        "补充电机A：上述均值的样本范围是A1、A2、A3，与该均值判据对应，版本和条件相同。",
        "更正电机A：静态记录的物理量应为电流，单位mA正确，数值37不变。",
    ],
    "M02": [
        "/doc logic test 合成验收。电机A：记录电流18 A；该记录的样本编号与适用判据待补。",
        "电机A样本编号是S-A。",
        "电机A样本S-A本次同条件单项电流判据≥16 A；只判断该样本的该次记录，不涉及均值或全批。",
    ],
    "M03": [
        "/doc logic test 合成验收。电机A：均值判据≥16 A；处理后记录18 A以上。",
        "电机A该记录的统计口径和样本范围都不知道，无法提供。",
        "/doc 阶段稿",
    ],
}

class LocalOnlyApi:
    def authorized(self, row): return True
    def send(self, *a): raise AssertionError("No platform sends in isolated content runs")

def main():
    out=Path(sys.argv[1]); out.mkdir(parents=True,exist_ok=True)
    actual=Config.load(Path.home()/".local/share/local-qwen-feishu/poc/config/environment.json")
    provider=LocalQwenProvider(actual)
    runtime={k:v for k,v in provider.pin().items() if k in ("provider","base_url","model","model_digest","server_version")}
    summary=[]
    for name in sys.argv[2:] or FLOWS:
        with tempfile.TemporaryDirectory(prefix="logic-fix1-") as tmp:
            root=Path(tmp)
            for p in ("state","tasks","artifacts"): (root/p).mkdir()
            cfg=replace(actual,root=root,app_id="cli_synthetic",tenant_key="tenant_synthetic",users=("ou_A","ou_B"),owner="ou_A",chats=(),document_logic=True)
            calls=[]
            class Recorder:
                def complete(self,prompt,**kwargs):
                    result=provider.complete(prompt,**kwargs)
                    calls.append({"prompt":prompt,"output":result.text,"elapsed":result.elapsed})
                    return result
            store=Store(root/"state/gateway.sqlite3")
            g=Gateway(cfg,store,LocalOnlyApi(),Recorder())
            for turn,text in enumerate(FLOWS[name],1):
                calls.clear()
                row={"app":cfg.app_id,"tenant":cfg.tenant_key,"user":"ou_A","chat":"oc_synthetic","chat_type":"p2p",
                     "event_id":f"{name}-{turn}","message_id":f"{name}-{turn}","kind":"message","body":text,"source_time":time.time()}
                store.put(row);g.receive_one()
                task=store.claim(1);g.run_task(task)
                d=g.logic.current(row)
                state=store.rows("SELECT state,error,model,elapsed FROM tasks WHERE id=?",(task["id"],))[0]
                record={"flow":name,"turn":turn,"layer":"real_Qwen_isolated_platform","input":text,"runtime":runtime,
                        "rules":load_rules()[1],"result":state,"sources":json.loads(d["sources"]),
                        "generation_metadata":json.loads(d["rules"]) if d["rules"] else None,
                        "question_states":json.loads(d["answers"]),"analysis":json.loads(d["analysis"]) if d["analysis"] else None,
                        "review":json.loads(d["review"]) if d["review"] else None,"model_io":list(calls)}
                (out/f"{name}-{turn}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2))
                if d["content"] and state["state"]=="completed": (out/f"{name}-{turn}.md").write_text(d["content"])
                item={"flow":name,"turn":turn,**state};summary.append(item);print(json.dumps(item),flush=True)
                if state["state"]!="completed": break
            g.stop();store.close()
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
