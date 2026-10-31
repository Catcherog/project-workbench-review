"""Queue synthetic-only expression probes in the original running AM worker."""
from pathlib import Path
import json,os,time,hashlib,subprocess
TASK=Path(__file__).resolve().parents[1]
private=Path.home()/'.local/share/local-qwen-feishu'
cfg=json.loads((private/'config.json').read_text())
poc=json.loads(Path(cfg['poc_config']).read_text())
root=Path(poc['service']['root_directory'])/'state/am-conversation-r2'
out=TASK/'evidence/model-pairs';out.mkdir(parents=True,exist_ok=True)
cases=['query','analysis','followup','worknote','knowledge','document','approval','sending','schedule','control','partial','unknown']
for family in cases:
 label='harness-r2-'+family+'-'+str(int(time.time()))
 path=root/'requests'/(label+'.json');path.parent.mkdir(parents=True,exist_ok=True)
 job={'operation':'response_probe','case':family,'max_seconds':110,'expires_at':time.time()+180}
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump(job,f)
 end=time.monotonic()+160;result_path=root/'results'/(label+'.json')
 while not result_path.exists() and time.monotonic()<end:
  time.sleep(.5)
 if not result_path.exists():
  print(json.dumps({'case':family,'status':'pending_or_unknown','automatic_retry':False}),flush=True);break
 result=json.loads(result_path.read_text())
 result['measurement_source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TASK.parents[1],text=True).strip()
 # The service probe has only fixed synthetic fixtures. No real message source.
 if result.get('operation')!='response_probe':raise RuntimeError('UNEXPECTED_OPERATION')
 (out/(family+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'case':family,'ok':result['ok'],'reason':result.get('telemetry',{}).get('reason'),
   'legacy_seconds':result.get('legacy',{}).get('seconds'),'response_seconds':result.get('response',{}).get('seconds'),
   'adopted':result.get('telemetry',{}).get('adopted'),'error':result.get('error')},ensure_ascii=False),flush=True)
 if not result['ok']:
  print('stopped after unclassified probe failure; no automatic retry',flush=True);break
