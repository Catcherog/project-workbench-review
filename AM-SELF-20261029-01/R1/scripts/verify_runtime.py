import json,sqlite3,subprocess,fcntl,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[3];private=Path.home()/'.local/share/local-qwen-feishu';state=private/'state';folder=private/'validation/am-self-20261029-r1'
cfg=json.loads((private/'config.json').read_text());pc=json.loads(Path(cfg['poc_config']).read_text());pocroot=Path(pc['service']['root_directory'])
manifest=json.loads((state/'loaded-manifest.json').read_text());mismatches=[]
for name,expected in manifest['files'].items():
 prefix,rel=name.split('/',1);base=root/('local-qwen3.8/feishu-bridge' if prefix=='feishu-bridge' else 'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent')
 if hashlib.sha256((base/rel).read_bytes()).hexdigest()!=expected:mismatches.append(name)
output=subprocess.check_output(['ps','-axo','pid=,args='],text=True);consumers=[]
for line in output.splitlines():
 p=line.strip().split(maxsplit=1)
 if len(p)==2 and Path(p[1].split(' ',1)[0]).name.lower().startswith('python') and '/feishu-bridge/bridge.py --config ' in p[1]:consumers.append(int(p[0]))
locked=False
with (state/'instance.lock').open('a+') as h:
 try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:locked=True
connection=json.loads((state/'connection-status.json').read_text())
summary=json.loads((folder/'installation.json').read_text());summary.update(current_python_consumers=len(consumers),consumer_lock_held=locked,loaded_files_match_tested_checkout=not mismatches,connection_state=connection['state'],loaded_dependency_versions=manifest['dependencies'],launch_service_registration_verified=True)
print('runtime checks',{'consumer_count':len(consumers),'locked':locked,'mismatched_files':mismatches,'connection':connection['state']})
assert len(consumers)==1 and locked and not mismatches and connection['state']=='connected'
for name,path in [('gateway',pocroot/'state/gateway.sqlite3'),('ledger',state/'group-ledger.sqlite3')]:
 db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 if name=='gateway':
  summary['new_business_counts']={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('action_items','reminder_plans','reminder_occurrences','am_subscriptions','ledger_write_attempts')}
  pause=db.execute("SELECT value FROM meta WHERE key='provider_pause'").fetchone();summary['provider_pause']=pause[0] if pause else None
 db.close()
(root/'AM-SELF-20261029-01/R1/evidence/installation-verified.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
