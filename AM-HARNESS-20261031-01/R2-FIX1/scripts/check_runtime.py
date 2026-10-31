"""Read-only final runtime/source/config check; no model inference or restart."""
from pathlib import Path
import fcntl,hashlib,json,shlex,sqlite3,subprocess,time,urllib.request
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1]
private=Path.home()/'.local/share/local-qwen-feishu';raw=(private/'config.json').read_bytes();cfg=json.loads(raw);poc_raw=Path(cfg['poc_config']).read_bytes();poc=json.loads(poc_raw)
state=Path(cfg['state_directory']);loaded=json.loads((state/'loaded-manifest.json').read_text());connection=json.loads((state/'connection-status.json').read_text())
assert hashlib.sha256(raw).hexdigest()=='5ae551fb39d39b690a4dadcf10f96a3d0c753141fe60e25fc4f484b1612efe2f'
assert loaded['config_sha256']==hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest()
prefix={'feishu-bridge':'local-qwen3.8/feishu-bridge',**{n:'am-conversation-r1/src/'+n for n in ('am_conversation','am_reply','am_outcome','am_response')},**{n:'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/'+n for n in ('fs_agent','am_doc_engine','am_harness')}}
for name,digest in loaded['files'].items():
 group,rel=name.split('/',1);assert hashlib.sha256((ROOT/prefix[group]/rel).read_bytes()).hexdigest()==digest
consumers=[];servers=[]
for line in subprocess.check_output(['ps','-axo','pid=,args='],text=True).splitlines():
 parts=line.strip().split(maxsplit=1)
 if len(parts)!=2:continue
 try:args=shlex.split(parts[1])
 except ValueError:continue
 if not args:continue
 if Path(args[0]).name.lower().startswith('python') and any(x.endswith('/feishu-bridge/bridge.py') for x in args) and '--config' in args:consumers.append(int(parts[0]))
 if Path(args[0]).name=='ollama' and len(args)>1 and args[1]=='serve':servers.append(int(parts[0]))
assert consumers==[loaded['pid']] and servers==[758]
held=False
with (state/'instance.lock').open('r+') as f:
 try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN)
 except BlockingIOError:held=True
assert held and connection['state']=='connected'
assert poc['provider']['base_url']=='http://127.0.0.1:11434/v1'
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**kw):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
def get(path):
 with opener.open('http://127.0.0.1:11434'+path,timeout=5) as response:return json.load(response)
version=get('/api/version')['version'];matches=[m for m in get('/api/tags')['models'] if m['name']==poc['provider']['model']]
assert version=='0.40.5' and len(matches)==1 and matches[0]['digest']==poc['provider']['model_digest']==loaded['model_digest']
dbpath=Path(poc['service']['root_directory'])/'state/gateway.sqlite3'
with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
 lane=db.execute('SELECT state FROM am_harness_lane').fetchone()[0]
 pause=db.execute("SELECT value FROM meta WHERE key='provider_pause'").fetchone()
 integrity=db.execute('PRAGMA quick_check').fetchone()[0]
assert lane=='idle' and pause is None and integrity=='ok'
result={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'verified_at':time.time(),'loaded_at':loaded['loaded_at'],'loaded_files':len(loaded['files']),'loaded_bytes_match':True,'consumer_count':len(consumers),'original_instance_lock_held':held,'connection':connection['state'],'model':loaded['model'],'model_pin_verified':True,'model_server_version':version,'model_digest':loaded['model_digest'],'original_ollama_server_pid':servers[0],'identity_cache_seconds':cfg['am_query']['identity_cache_seconds'],'ledger_write':cfg['am_self']['ledger_write'],'harness':loaded['harness'],'lane_state':lane,'model_paused':False,'sqlite_quick_check':integrity,'configuration_sha256':hashlib.sha256(raw).hexdigest(),'poc_configuration_sha256':hashlib.sha256(poc_raw).hexdigest(),'response_mode':cfg['am_conversation'].get('response',{}).get('mode','legacy'),'rewrite_mode':cfg['am_conversation']['output_rewrite']['mode'],'goal_tracking':cfg['am_conversation'].get('runtime',{}).get('goal_tracking',False),'new_model_inference_calls':0,'new_consumers_created':0}
(TASK/'evidence/runtime-final.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
