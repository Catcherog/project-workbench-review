"""Explicit, guarded recovery of THIS model-only validation timeout.

Never stop/restart/unload Ollama, never declare an unknown model output successful,
never replay a business action. Only an already UNLOADED backend is accepted.
"""
from pathlib import Path
import json,os,re,shlex,subprocess,sqlite3,fcntl,time,hashlib,shutil,urllib.request
ROOT=Path('/workspace/am');TASK=Path(__file__).resolve().parents[1]
EXPECTED='25b6879a0a53bf7004bc9fbb451c021ea7d909ef';NEW='7a61ab3d80e77b5a711bce0710fa8fdd2e02193b'
RUN='b5b768c007b34349a2176ac485c48ab1';LABEL='r2fix1-de39a5e93f714892a3ada1312969fb2d'
private=Path.home()/'.local/share/local-qwen-feishu';raw=(private/'config.json').read_bytes();cfg=json.loads(raw);poc_raw=Path(cfg['poc_config']).read_bytes();poc=json.loads(poc_raw)
runtime=Path(poc['service']['root_directory']);state=runtime/'state';bridge_state=Path(cfg['state_directory']);dbpath=state/'gateway.sqlite3'
py=ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/.venv/bin/python';service=ROOT/'local-qwen3.8/feishu-bridge/service.sh'
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
assert git('rev-parse','HEAD')==EXPECTED
assert subprocess.run(['git','diff','--quiet','HEAD'],cwd=ROOT).returncode==0
subprocess.run(['git','merge-base','--is-ancestor',EXPECTED,NEW],cwd=ROOT,check=True)
assert cfg['am_self']['ledger_write'] is False and cfg['am_query']['identity_cache_seconds']==600
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
assert poc['provider']['base_url']=='http://127.0.0.1:11434/v1'
def get(path):
 with opener.open('http://127.0.0.1:11434'+path,timeout=5) as response:return json.load(response)
def processes():
 result=[]
 for line in subprocess.check_output(['ps','-axo','pid=,ppid=,args='],text=True).splitlines():
  parts=line.strip().split(maxsplit=2)
  if len(parts)!=3:continue
  try:args=shlex.split(parts[2])
  except ValueError:continue
  if args:result.append((int(parts[0]),int(parts[1]),args))
 return result
def consumers():return [p for p,_,a in processes() if Path(a[0]).name.lower().startswith('python') and any(x.endswith('/feishu-bridge/bridge.py') for x in a) and '--config' in a]
def prove_stopped():
 models=get('/api/ps')['models'];assert models==[],'BACKEND_NOT_UNLOADED'
 rows=processes();servers=[p for p,_,a in rows if Path(a[0]).name=='ollama' and len(a)>1 and a[1]=='serve']
 runners=[p for p,_,a in rows if Path(a[0]).name=='llama-server' or Path(a[0]).name=='ollama' and len(a)>1 and a[1]=='runner']
 assert servers==[758] and not runners,'ORIGINAL_MODEL_PROCESS_STATE_CHANGED'
 assert get('/api/version')['version']=='0.40.5'
 tags=get('/api/tags')['models'];matches=[m for m in tags if m['name']==poc['provider']['model']]
 assert len(matches)==1 and matches[0]['digest']==poc['provider']['model_digest']
 return {'checked_at':time.time(),'loaded_models':0,'runner_count':0,'original_ollama_server_pid':758,'model_pin_matches':True}
def quiet():
 with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
  assert db.execute("SELECT value FROM meta WHERE key='provider_pause'").fetchone()[0] in ('STOP_UNKNOWN','ORPHAN_STOP_UNKNOWN')
  for sql in ("SELECT COUNT(*) FROM tasks WHERE state IN ('running','stop_unknown')","SELECT COUNT(*) FROM am_harness_runs WHERE state IN ('queued','running')","SELECT COUNT(*) FROM am_inbox WHERE state IN ('processing','harness_admitting')","SELECT COUNT(*) FROM outbox WHERE state IN ('sending','pending') AND expires>strftime('%s','now')"):
   assert db.execute(sql).fetchone()[0]==0,'BUSINESS_WORK_IN_FLIGHT'
  assert db.execute('SELECT state FROM am_harness_lane').fetchone()[0]=='idle'
 requests=state/'am-conversation-r2/requests';results=state/'am-conversation-r2/results'
 assert not list(requests.glob('*.json'))
 assert all((results/(p.stem+'.json')).exists() for p in requests.glob('*.claimed'))
lease=(state/'model-coordinator.lock').open('a+');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
coordinator=state/'model-coordinator.json';original=coordinator.read_bytes();old=json.loads(original)
assert old['state']=='stop_unknown' and old['run_id']==RUN
job=json.loads((state/'am-conversation-r2/results'/(LABEL+'.json')).read_text())
assert job['operation']=='task_model_probe' and job['error']=='STOP_UNKNOWN' and job['external_business_calls']==0
assert abs(job['completed_at']-old['finished'])<1
current_manifest=json.loads((bridge_state/'loaded-manifest.json').read_text())
assert consumers()==[current_manifest['pid']]
assert hashlib.sha256(raw).hexdigest()=='5ae551fb39d39b690a4dadcf10f96a3d0c753141fe60e25fc4f484b1612efe2f'
unknown=runtime/'tasks'/RUN;assert not unknown.is_symlink()
assert json.loads((unknown/'process.json').read_text())['state']=='stopped'
assert json.loads((unknown/'api-state.json').read_text())['state']=='in_flight'
quiet();samples=[prove_stopped()];time.sleep(2);samples.append(prove_stopped())
archive=private/'validation/am-harness-r2-fix1'/('reconcile-'+RUN)/('attempt-'+str(time.time_ns()));archive.mkdir(parents=True,mode=0o700,exist_ok=False)
proof={'model_run_id':RUN,'validation_label':LABEL,'model_only':True,'original_result':'unknown','new_result':'unknown_not_replayed',
 'reason':'original HTTP worker stopped; pinned backend automatically unloaded; no inference process remains','samples':samples,
 'qwen_or_ollama_restart':False,'model_unload_command':False,'business_action_replay':False,'source_before':EXPECTED,'source_after':NEW}
proof_bytes=(json.dumps(proof,sort_keys=True,ensure_ascii=False)+'\n').encode();proof_hash=hashlib.sha256(proof_bytes).hexdigest()
(archive/'proof.json').write_bytes(proof_bytes);(archive/'coordinator.before.json').write_bytes(original)
subprocess.run(['/bin/zsh',str(service),'stop'],check=True,capture_output=True)
moved=False;resumed=False
try:
 deadline=time.monotonic()+25
 while consumers() and time.monotonic()<deadline:time.sleep(.2)
 assert not consumers();quiet();prove_stopped()
 assert coordinator.read_bytes()==original and (private/'config.json').read_bytes()==raw and Path(cfg['poc_config']).read_bytes()==poc_raw
 with (bridge_state/'instance.lock').open('a+') as bridge_lock:
  fcntl.flock(bridge_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  with sqlite3.connect(dbpath) as source,sqlite3.connect(archive/'gateway.before.sqlite3') as backup:source.backup(backup)
  unknown.rename(archive/'original-api-unknown');moved=True
  marker={'state':'reconciled_stopped','run_id':RUN,'finished':time.time(),'original_output_status':'unknown','recovery_proof_sha256':proof_hash}
  temporary=coordinator.with_suffix('.recovery.tmp');temporary.write_text(json.dumps(marker));temporary.replace(coordinator)
  result=subprocess.run([str(py),'-m','fs_agent.cli','resume','--config',cfg['poc_config']],capture_output=True,text=True)
  (archive/'resume-result.json').write_text(json.dumps({'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}))
  assert result.returncode==0, 'ORIGINAL_RESUME_CLI_FAILED'
  assert json.loads(result.stdout)['resumed'] is True;resumed=True
  assert git('rev-parse','HEAD')==EXPECTED
  subprocess.run(['git','merge','--ff-only',NEW],cwd=ROOT,check=True,capture_output=True)
except BaseException:
 if not resumed:
  coordinator.write_bytes(original)
  if moved:(archive/'original-api-unknown').rename(unknown)
 raise
finally:
 subprocess.run(['/bin/zsh',str(service),'start'],check=True,capture_output=True)
lease.close()
proof.update(restored_by_original_resume_cli=resumed,configuration_bytes_unchanged=(private/'config.json').read_bytes()==raw,
 original_poc_configuration_unchanged=Path(cfg['poc_config']).read_bytes()==poc_raw,proof_sha256=proof_hash)
for p in archive.iterdir():
 if p.is_file():p.chmod(0o600)
(TASK/'evidence/model-stop-reconciliation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:proof[k] for k in ('restored_by_original_resume_cli','new_result','qwen_or_ollama_restart','configuration_bytes_unchanged','source_after')}))
