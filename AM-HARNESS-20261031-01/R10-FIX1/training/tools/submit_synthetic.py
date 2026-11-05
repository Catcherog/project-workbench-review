from pathlib import Path
import argparse,json,time,uuid,hashlib,os
ROOT=Path(__file__).resolve().parents[3];T=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--record',required=True);a=p.parse_args()
plan=json.loads(a.plan.read_text());cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
ident=str(uuid.uuid4());request={'operation':'train-synthetic' if plan['mode']=='train' else 'eval-synthetic','request_id':ident,'expires_at':time.time()+900,
 'plan':str(a.plan.resolve()),'plan_sha256':hashlib.sha256(a.plan.read_bytes()).hexdigest(),'run_id':Path(plan['run_directory']).name}
control=Path(cfg['state_directory'])/'training-window-r7';target=control/(ident+'.request.json')
fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:json.dump(request,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
record={'request':request,'control':str(control),'run_directory':plan['run_directory'],'request_path':str(target),'submitted_at':time.time(),'training_started':'not_yet_observed'}
p=T/'private'/a.record
with p.open('x') as f:json.dump(record,f,ensure_ascii=False,indent=2)
p.chmod(0o600);print(json.dumps({'request_id':ident,'operation':request['operation'],'run_directory':plan['run_directory']},ensure_ascii=False))
