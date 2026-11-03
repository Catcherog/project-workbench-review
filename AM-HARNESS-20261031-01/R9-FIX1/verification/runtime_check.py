from pathlib import Path
import hashlib,json,sqlite3,subprocess,time,sys
ROOT=Path(__file__).resolve().parents[3];TASK=Path(__file__).resolve().parents[1]
cfgpath=Path.home()/'.local/share/local-qwen-feishu/config.json';cfg=json.loads(cfgpath.read_text());pocpath=Path(cfg['poc_config']);poc=json.loads(pocpath.read_text())
state=Path(poc['service']['root_directory'])/'state';bridge=Path(cfg['state_directory'])
loaded=json.loads((bridge/'loaded-manifest.json').read_text())
roots={'feishu-bridge':ROOT/'local-qwen3.8/feishu-bridge','fs_agent':ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent',
    'am_harness':ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_harness','am_doc_engine':ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine',
    'am_training_window':ROOT/'am-integrated-r6/am_training_window'}
for name in ('am_conversation','am_outcome','am_response','am_style','am_reply'):roots[name]=ROOT/'am-conversation-r1/src'/name
roots['am_followup']=ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_followup'
files=[]
for key,sha in loaded['files'].items():
    prefix,rest=key.split('/',1);path=roots[prefix]/rest
    actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    files.append({'path':str(path.relative_to(ROOT)),'loaded_sha256':sha,'current_sha256':actual,'matches':sha==actual})
consumers=[]
for line in subprocess.check_output(['ps','-axo','pid=,args='],text=True).splitlines():
    parts=line.strip().split(maxsplit=1)
    if len(parts)==2 and Path(parts[1].split(' ',1)[0]).name.lower().startswith('python') and '/feishu-bridge/bridge.py --config ' in parts[1]:consumers.append(int(parts[0]))
with sqlite3.connect((state/'gateway.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    gates=db.execute("SELECT key,value FROM meta WHERE key IN ('provider_pause','resource_window_owner')").fetchall()
    lane=db.execute('SELECT state FROM am_harness_lane').fetchone()[0]
    tasks=db.execute("SELECT state,count(*) FROM tasks WHERE state IN ('running','queued','stop_unknown') GROUP BY state").fetchall()
    migration=db.execute("SELECT value FROM meta WHERE key='document-view-binding-r9-fix1'").fetchone()
status=json.loads((bridge/'connection-status.json').read_text());heartbeat=json.loads((bridge/'heartbeat-status.json').read_text())
report={'observed_at':time.time(),'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    'loaded_at':loaded['loaded_at'],'loaded_files':len(files),'source_mismatches':[f['path'] for f in files if not f['matches']],
    'consumer_count':len(consumers),'consumer_matches_loaded':consumers==[loaded['pid']],
    'connection':status.get('state',status.get('status')),'heartbeat_keys':list(heartbeat),
    'provider_pause_and_window_owner':gates,'harness_lane':lane,'active_tasks':tasks,
    'cache_migration_applied':migration==('done',),'model_coordinator_state':json.loads((state/'model-coordinator.json').read_text()).get('state'),
    'model':loaded.get('model'),'model_digest':loaded.get('model_digest'),
    'config_sha256':hashlib.sha256(cfgpath.read_bytes()).hexdigest(),'poc_config_sha256':hashlib.sha256(pocpath.read_bytes()).hexdigest(),
    'ledger_write':cfg['am_self']['ledger_write'],'identity_cache_seconds':600,'files':files,'read_only':True}
label=sys.argv[1] if len(sys.argv)>1 else 'runtime-final'
(TASK/'evidence'/f'{label}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=False))
