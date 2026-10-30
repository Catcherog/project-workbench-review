"""Synthetic project-memory token measurements through the existing model gate."""
import json,sys,time,uuid,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from fs_agent.config import Config
from fs_agent.store import Store
from fs_agent.qwen_provider import LocalQwenProvider
from fs_agent.model_coordinator import ModelCoordinator
from project_memory import extraction_prompt,EXTRACTION_SCHEMA,PROFILES
private=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((private/'config.json').read_text());cfg=Config.load(Path(settings['poc_config']))
s=Store(cfg.db);provider=ModelCoordinator(LocalQwenProvider(cfg),s,cfg.root/'state');pin=provider.pin()
cases=[
 ('development_full','development',[{'id':'e'+str(i),'source_time':i,'observed_time':i+1,'text':'需求A样机预计11月5日完成，需先完成硬件选型；尚未完成测试或验收。负责人AR1测试甲。'} for i in range(12)]),
 ('development_incremental','development',[{'id':'new1','source_time':13,'observed_time':14,'text':'需求A样机改为预计11月8日完成，需先完成硬件选型；尚未完成测试或验收。原11月5日为预计，变更尚待批准。'}]),
 ('certification','certification',[{'id':'c1','source_time':1,'observed_time':2,'text':'认证A仅收到草本证书，正式证书未签发；升级量产项目B另行验证。不能据此放行量产。'}]),
 ('quality','quality',[{'id':'q1','source_time':1,'observed_time':2,'text':'质量A：20-100型号版本待确认，供应商喷丸报告为评估输入。公司验证未结束，旧工艺产能继续保留。'}]),
]
results=[];out=ROOT/'AM-SELF-20261029-01/UX4/evidence/qwen-memory-tokens.json'
for name,profile,sources in cases:
 ctx={'project':'SYNTHETIC-'+name,'focus':PROFILES[profile],'sources':sources,'reviewed_reports':[],'pending':[]}
 prompt=extraction_prompt(ctx);start=time.monotonic()
 record={'case':name,'synthetic':True,'prompt_chars':len(prompt),'source_count':len(sources)}
 try:
  result=provider.complete(prompt,run_id=uuid.uuid4().hex,native_chat=True,json_schema=EXTRACTION_SCHEMA,max_tokens=1400,timeout=120)
  value=json.loads(result.text);valid=all(x['source_id'] in {a['id'] for a in sources} and any(x['source_id']==a['id'] and x['quote'] and x['quote'] in a['text'] for a in sources) for x in value['candidates'])
  record.update(success=True,usage=result.usage,evidence_quotes_valid=valid,candidate_count=len(value['candidates']),result=value)
 except Exception as exc:
  record.update(success=False,error=str(exc)[:80])
 record['wall_seconds']=round(time.monotonic()-start,3);results.append(record)
 report={'model':pin['model'],'server_version':pin['server_version'],'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'sample_kind':'real Qwen inference over synthetic business evidence; not production load or Codex token pricing','samples':results,'original_model_gate_reused':True,'new_feishu_consumers':0,'model_switched':False}
 out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in record.items() if k!='result'},ensure_ascii=False),flush=True)
 if s.meta('provider_pause'):break
s.close()
