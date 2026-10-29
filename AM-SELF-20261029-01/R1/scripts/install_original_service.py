"""Install this tested checkout into the existing service, preserving one consumer."""
import fcntl,json,sqlite3,subprocess,time,hashlib,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];private=Path.home()/'.local/share/local-qwen-feishu';folder=private/'validation/am-self-20261029-r1'
config_path=private/'config.json';before=json.loads(config_path.read_text());poc=json.loads(Path(before['poc_config']).read_text());pocroot=Path(poc['service']['root_directory'])
checks=[(private/'state/chat.sqlite3',"SELECT count(*) FROM inbox WHERE state IN ('processing','sending')"),
        (private/'state/group-ledger.sqlite3',"SELECT count(*) FROM ledger_inbox WHERE state IN ('processing','sending')"),
        (pocroot/'state/gateway.sqlite3',"SELECT count(*) FROM tasks WHERE state IN ('running','stop_unknown')")]
for path,sql in checks:
 db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);count=db.execute(sql).fetchone()[0];db.close()
 if count:raise RuntimeError('ORIGINAL_SERVICE_HAS_ACTIVE_OR_UNKNOWN_MODEL_WORK')
service=ROOT/'local-qwen3.8/feishu-bridge/service.sh'
subprocess.run(['/bin/zsh',str(service),'stop'],check=True,capture_output=True)
for _ in range(100):
 if subprocess.run(['launchctl','print','gui/'+str(os.getuid())+'/local.qwen.feishu'],capture_output=True).returncode:break
 time.sleep(.1)
else:raise RuntimeError('ORIGINAL_SERVICE_STILL_REGISTERED')
lock=(private/'state/instance.lock').open('a+')
for _ in range(100):
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
 except BlockingIOError:time.sleep(.1)
else:raise RuntimeError('ORIGINAL_CONSUMER_NOT_STOPPED')
try:
 for path,sql in checks:
  db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
  if db.execute(sql).fetchone()[0]:raise RuntimeError('WORK_STARTED_DURING_STOP_REQUIRES_RECONCILIATION')
  dest=folder/('install-backup-'+path.name)
  if dest.exists():raise RuntimeError('INSTALL_BACKUP_ALREADY_EXISTS')
  backup=sqlite3.connect(dest);db.backup(backup);backup.close();db.close()
 settings=json.loads((folder/'proposed-runtime-settings.json').read_text());after=json.loads(json.dumps(before))
 after['group_ledger']['disclosure']=settings['disclosure']
 after['am_self']={k:k!='ledger_write' for k in ['query','snapshots','items','scheduler','progress_collection','ledger_write','attachments','precheck']}
 after['am_self_metadata']=settings['metadata'];after['am_write_execution']={'project_refs':[],'exclusive_window_until':0}
 assert all(before[k]==after[k] for k in before if k!='group_ledger')
 assert all(before['group_ledger'][k]==after['group_ledger'][k] for k in before['group_ledger'])
 tmp=config_path.with_suffix('.am-self.tmp');tmp.write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n');tmp.chmod(0o600);tmp.replace(config_path)
finally:
 fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
subprocess.run(['/bin/zsh',str(service),'start'],check=True,capture_output=True)
summary={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'previous_consumer_stopped_and_lock_released':True,'same_original_launch_service':True,'flags':after['am_self'],'new_subscriptions_created':0,'new_group_messages_sent':0,'formal_ledger_writes':0,'installed_at':time.time(),'config_sha256':hashlib.sha256(json.dumps(after,sort_keys=True).encode()).hexdigest()}
(folder/'installation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
