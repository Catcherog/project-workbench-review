"""Synthetic content acceptance through the production LogicService and pinned Qwen."""
import json, tempfile, time, sys
from dataclasses import replace
from pathlib import Path
from fs_agent.config import Config
from fs_agent.qwen_provider import LocalQwenProvider
from fs_agent.store import Store
from fs_agent.gateway import Gateway
from fs_agent.doc_logic import load_rules, digest

CASES = {
"C01": ("test", "样机 S-A：主轴跳动 0.026→0.013 mm，输入端 0.007→0.010 mm，总噪声 55.1→51.4 dB，限值 ≤59 dB；约 3 Hz 声音幅度调制仍可辨。原稿称“各项改善、异响解决”。"),
"C02": ("test", "返件平均 11.5 A，历史平均 15.2 A，均值判据 ≥16 A；处理后仅写“18 A 以上”。扭矩 1.1 N·m，清洗后 1.4 N·m，跑合再清洗后 ≥2.8 N·m，判据 ≥2.8 N·m；另记“静态功耗 37 mA”。"),
"C03": ("8d", "已记录更换支架并重插线缆；同一样机本次连续运行 12 分钟未见中断。原稿称支架是唯一根因。"),
"C04": ("8d", "三个独立小节：一次重校后恢复；测试板外部导线跨接后通信恢复；人为构造校验不一致复现报警，恢复参数后消失。均无历史形成记录。"),
"C05": ("8d", "同一事件 V1 待补证、V2 提交专业审核，均无已批准记录。V2 图 A 正常、图 B 异常、图 C 本地复现，正文误把异常引为图 A。此输入只有图题信息，没有图片像素。"),
"C06": ("8d", "已有观察：本次发现接点接触异常。两层有依据的原因：记录显示接点接触电阻偏高造成压降，压降使供电不足；两层各有对应测量记录。后续历史未知，模板强制五层；用户说先形成阶段报告。另有记录提及验证完成，但对应附件暂不可读。"),
"C07": ("test", "合成样本 S-Z、V2，在室温静置条件下，电流实测 18 A；本次单项判据 ≥16 A，判据明确适用本样本。记录为同一次单项测量，无均值或全批结论。")
}
class LocalOnlyApi:
    def authorized(self, row): return True
    def send(self, *a): raise AssertionError("No Feishu sends from content validation")
def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    actual = Config.load(Path.home()/".local/share/local-qwen-feishu/poc/config/environment.json")
    provider = LocalQwenProvider(actual)
    fingerprint = provider.pin()
    fingerprint = {k:fingerprint[k] for k in ("provider","base_url","model","model_digest","server_version")}
    statuses = []
    selected = sys.argv[2:] or list(CASES)
    for index,key in enumerate(selected):
        kind,text = CASES[key]
        with tempfile.TemporaryDirectory(prefix="logic-acceptance-") as temp:
            root = Path(temp)
            for directory in ("state","tasks","artifacts"): (root/directory).mkdir()
            cfg=replace(actual, root=root, app_id="cli_synthetic",tenant_key="tenant_synthetic",
                        users=("ou_A","ou_B"),owner="ou_A",chats=(),document_logic=True)
            outputs=[]
            class Recorder:
                def complete(self,*a,**kw):
                    result=provider.complete(*a,**kw);outputs.append(result.text);return result
            store=Store(root/"state/gateway.sqlite3"); gateway=Gateway(cfg,store,LocalOnlyApi(),Recorder())
            now = time.time()
            row={"app":cfg.app_id,"tenant":cfg.tenant_key,"user":"ou_A","chat":"oc_synthetic","chat_type":"p2p",
                 "event_id":key,"message_id":key,"kind":"message","body":"/doc logic "+kind+" "+text,
                 "source_time":now}
            store.put(row); gateway.receive_one()
            d=gateway.logic.current(row)
            if key=="C06":
                store.execute("UPDATE logic_drafts SET stage=1 WHERE id=?",(d["id"],))
            task=store.claim(1); gateway.run_task(task)
            d=gateway.logic.current(row)
            state=store.rows("SELECT state,error,model,elapsed FROM tasks WHERE id=?",(task["id"],))[0]
            record={"case":key,"synthetic":True,"input":text,"document_type":kind,"runtime":fingerprint,
                    "rules":load_rules()[1],"result":state,
                    "question_states":json.loads(d["answers"]),"generation_metadata":json.loads(d["rules"]) if d["rules"] else None,
                    "analysis":json.loads(d["analysis"]) if d["analysis"] else None,
                    "semantic_review":json.loads(d["review"]) if d["review"] else None, "synthetic_model_outputs":outputs}
            (out/(key+".json")).write_text(json.dumps(record,ensure_ascii=False,indent=2))
            if d["content"]: (out/(key+".md")).write_text(d["content"])
            statuses.append({"case":key,**state}); print(json.dumps(statuses[-1]),flush=True)
            gateway.stop(); store.close()
    (out/"run-summary.json").write_text(json.dumps(statuses,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
