"""Real Qwen via the original cross-process coordinator; synthetic ports only."""
import hashlib,json,sys,time,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-CONVERSATION-20261030-01/R1'
sys.path[:0]=[str(ROOT/'am-conversation-r1/src'),str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src')]
from fs_agent.config import Config
from fs_agent.store import Store
from fs_agent.qwen_provider import LocalQwenProvider
from fs_agent.model_coordinator import ModelCoordinator
from am_conversation.model import CoordinatorModel
from am_conversation.evaluation import run_cases
from am_conversation.prompts import PROMPT_VERSION
from am_conversation.engine import RuntimeConfig
private=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((private/'config.json').read_text());config=Config.load(Path(settings['poc_config']))
store=Store(config.db);coordinator=ModelCoordinator(LocalQwenProvider(config),store,config.root/'state');pin=coordinator.pin()
files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'am-conversation-r1/src').rglob('*.py')}
class MeasuredCoordinator:
 def __init__(self):self.calls=[]
 def complete(self,prompt,**kwargs):
  started=time.monotonic();record={'prompt_chars':len(prompt),'schema_chars':len(json.dumps(kwargs.get('json_schema')))}
  try:
   result=coordinator.complete(prompt,**kwargs);record.update(success=True,usage=result.usage,model_proposal=json.loads(result.text));return result
  except Exception as exc:record.update(success=False,error=str(exc)[:80]);raise
  finally:record['seconds']=time.monotonic()-started;self.calls.append(record)
measured=MeasuredCoordinator();cases=json.loads((ROOT/'am-conversation-r1/evaluations/scenarios.json').read_text())
label=sys.argv[1] if len(sys.argv)>1 else 'smoke';selected=set(sys.argv[2:]);cases=[c for c in cases if not selected or c['id'] in selected]
report={'task':'AM-CONVERSATION-20261030-01/R1','model':pin['model'],'model_digest':pin['model_digest'],'server_version':pin['server_version'],'prompt_version':PROMPT_VERSION,
 'started_at':time.time(),'source_base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'loaded_package_sha256':files,
 'real_model':True,'synthetic_business_only':True,'external_business_calls':0,'manual_review_completed':False,'results':[]}
out=TASK/'evidence'/('qwen-'+label+'.json')
for case in cases:
 before=len(measured.calls);start=time.monotonic()
 result=run_cases(lambda:CoordinatorModel(measured),[case],config=RuntimeConfig(prefetch_projects=True,trusted_write_replies=True))['results'][0]
 result['model_calls']=measured.calls[before:];report['results'].append(result)
 report.update(case_count=len(report['results']),automated_pass_count=sum(r['automated_checks_passed'] for r in report['results']),updated_at=time.time())
 out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'case':case['id'],'passed':result['automated_checks_passed'],'seconds':round(time.monotonic()-start,2),'calls':len(result['model_calls']),'error':result['error']},ensure_ascii=False),flush=True)
 if store.meta('provider_pause'):
  print('Original model coordinator is paused; remaining cases were not dispatched.',flush=True);break
store.close()
