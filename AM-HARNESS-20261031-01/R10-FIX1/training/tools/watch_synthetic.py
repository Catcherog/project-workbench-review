from pathlib import Path
import argparse,json,time,shutil
T=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--record',required=True);a=p.parse_args()
v=json.loads((T/'private'/a.record).read_text());ident=v['request']['request_id'];control=Path(v['control']);run=Path(v['run_directory']);last=None;deadline=time.time()+950
while time.time()<deadline:
 view={'request_id':ident,'at':time.time()}
 for suffix in ('.journal.json','.result.json'):
  path=control/(ident+suffix)
  if path.exists():
   data=json.loads(path.read_text());view[suffix]={'state':data.get('state'),'ok':data.get('ok'),'error':data.get('error'),'error_code':data.get('error_code'),'trainer_invoked':data.get('trainer_invoked'),'window_status':data.get('window',{}).get('status')}
 if (run/'steps.json').exists():
  steps=json.loads((run/'steps.json').read_text());view['optimizer_steps']=len(steps);view['losses']=[s['loss'] for s in steps]
 if (run/'evaluation-progress.json').exists():view['evaluated_cases']=len(json.loads((run/'evaluation-progress.json').read_text()))
 sig=json.dumps({k:x for k,x in view.items() if k!='at'},sort_keys=True)
 if sig!=last:print(json.dumps(view,ensure_ascii=False),flush=True);last=sig
 if (control/(ident+'.result.json')).exists():
  dest=T/'private/control-results'/ident;dest.mkdir(parents=True,mode=0o700,exist_ok=False)
  for suffix in ('.receipt.json','.journal.json','.result.json'):
   q=control/(ident+suffix)
   if q.exists():shutil.copy2(q,dest/q.name)
  evidence=control/(ident+'.evidence')
  if evidence.exists():shutil.copytree(evidence,dest/'execution-evidence')
  break
 time.sleep(3)
else:print(json.dumps({'watch_expired':True,'request_id':ident,'no_retry':True}),flush=True)
