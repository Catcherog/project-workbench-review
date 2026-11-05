from pathlib import Path
import argparse,json,time,hashlib,subprocess,os
ROOT=Path(__file__).resolve().parents[3];T=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--runtime-root',type=Path,required=True);p.add_argument('--name',required=True);p.add_argument('--mode',choices=['train','evaluation'],default='train');p.add_argument('--arm',choices=['base','sft']);p.add_argument('--fit-run',type=Path);a=p.parse_args()
W=a.runtime_root.resolve();scope=ROOT/'AM-HARNESS-20261031-01/R7/private';out=scope/(a.name+'-plan');out.mkdir(mode=0o700,exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
obj=lambda v:hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
ref=lambda p:{'path':str(Path(p).absolute()),'sha256':sha(p)}
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');p.chmod(0o600);return ref(p)
old=json.loads((scope/'r8-pilot-plan-94fcf093-457/plan.json').read_text());cfg=json.loads(Path(old['config']['path']).read_text())
source=json.loads((T/'private/sft-first-batch/cases.json').read_text())
seed=json.loads((T/'private/style/candidates-final/sft.train.jsonl').read_text().splitlines()[0]);system=seed['messages'][0]['content']
for split in ('train','dev'):
 rows=[]
 for s in source:
  if s['split']!=split:continue
  prompt=[{'role':'system','content':system},{'role':'user','content':json.dumps({'task':s['question'],'facts':s['facts'],'synthetic':True},ensure_ascii=False,sort_keys=True)}]
  completion=[{'role':'assistant','content':s['response']}]
  rows.append({'id':s['id'],'prompt':prompt,'completion':completion,'provenance':{'source_kind':'assistant_reviewed_synthetic','human_approved':False,
   'split':split,'family':s['family'],'prompt_sha256':obj(prompt),'completion_sha256':obj(completion),'runtime_alignment':'experimental_direct_chat_not_production_AM'}})
 path=out/(split+'.jsonl');path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows));path.chmod(0o600);cfg[split]=ref(path)
for k in ('train_file','dev_file','train_sha256','dev_sha256','runtime_prompt_builder_sha256','style_policy_version','host_contract_version'):cfg.pop(k,None)
cfg.update(schema='am-synthetic-mlx-run/1',stage='synthetic_pilot',mode=a.mode,quality_tier='experimental_synthetic',experimental_only=True,human_approved=False,production_eligible=False,
 optimizer_betas=[.9,.999],optimizer_eps=1e-8,clip_grad_norm=1.0,system_prompt=system,
 authorization=ref(T/'private/input/synthetic-sft-authorization.json'),authorization_original=ref(T/'private/input/synthetic-sft-user-authorization.txt'),
 reviewed_cases=ref(T/'private/sft-first-batch/cases.json'),reserved_evaluation=ref(T/'private/reserved-evaluation/cases.frozen.json'),data_frozen_at_epoch=time.time())
if a.mode=='evaluation':
 assert a.arm
 cfg.update(arm=a.arm,generation={'temperature':0.0,'max_tokens':384,'seed':221})
 if a.arm=='sft':
  assert a.fit_run
  for key,name in [('fit_result','fit.json'),('reload_result','reload.json'),('adapter','adapters.safetensors'),('adapter_config','adapter_config.json')]:cfg[key]=ref(a.fit_run/name)
configref=save(out/'config.json',cfg)
paths=[str(p.relative_to(W)) for p in (W/'am-integrated-r6/am_training_window').glob('*.py')]
paths += ['local-qwen3.8/feishu-bridge/am_training_control.py','local-qwen3.8/feishu-bridge/am_resource_window.py']
for name in old['runtime_source_binding']['files_sha256']:
 paths.append(('am-conversation-r1/src/' if name.startswith('am_style/') else 'am-style-r3/')+name)
paths += ['am-style-r3/training/mlx_synthetic.py','am-style-r3/training/mlx_synthetic_runtime.py','am-style-r3/training/mlx_synthetic_contracts.py']
plan={'schema':'am-synthetic-mlx-plan/1','mode':a.mode,'manifest':old['manifest'],'config':configref,'python_interpreter':old['python_interpreter'],
 'runtime_source_binding':{'mode':'explicit_synthetic_experimental_runtime','roots':{'training':str(W/'am-style-r3'),'am_style':str(W/'am-conversation-r1/src')}},
 'source_files_sha256':{f:sha(W/f) for f in sorted(set(paths))},'run_directory':str(W/'AM-HARNESS-20261031-01/R7/private'/a.name),
 'training_authorized':True,'independent_business_acceptance_deferred':True,'original_gold_gate_unchanged':True}
plan['sha256']=obj(plan);save(out/'plan.json',plan)
env=dict(os.environ,PYTHONPATH=os.pathsep.join((str(W/'am-style-r3'),str(W/'am-conversation-r1/src'))),PYTHONDONTWRITEBYTECODE='1')
cmd=[plan['python_interpreter']['path'],'-m','training.mlx_synthetic','--plan',str(out/'plan.json')]
run=subprocess.run(cmd,env=env,cwd=W,capture_output=True,text=True)
save(out/'metadata-preflight.json',{'returncode':run.returncode,'stdout':run.stdout,'stderr':run.stderr,'model_loaded':False,'training_started':False,'command':cmd})
print(json.dumps({'plan':str(out/'plan.json'),'returncode':run.returncode,'stderr':run.stderr[-2500:],'train':32,'dev':8,'mode':a.mode,'arm':a.arm},ensure_ascii=False));raise SystemExit(run.returncode)
