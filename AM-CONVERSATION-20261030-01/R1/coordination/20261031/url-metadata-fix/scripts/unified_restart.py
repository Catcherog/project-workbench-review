"""One coordinated restart of the existing consumer; preserve all configuration."""
import fcntl,hashlib,json,os,sqlite3,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[5];OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'))
from fs_agent.config import Config
from fs_agent.qwen_provider import LocalQwenProvider
private=Path.home()/'.local/share/local-qwen-feishu';cp=private/'config.json';cfgbytes=cp.read_bytes();settings=json.loads(cfgbytes);pc=Path(settings['poc_config']);pcbytes=pc.read_bytes();cfg=Config.load(pc)
release=json.loads((OUT/'release-source.json').read_text())
def source_matches():
 for name,value in release['files'].items():
  assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value,'SOURCE_CHANGED:'+name
source_matches()
assert settings['am_self']['ledger_write'] is False and settings['am_query']['identity_cache_seconds']==600
assert not settings.get('am_write_execution',{}).get('exclusive_window_until')
doc=cfg.root/'config/document-standards.json';docbytes=doc.read_bytes()
dbfiles={'chat':private/'state/chat.sqlite3','ledger':private/'state/group-ledger.sqlite3','gateway':cfg.db,'information':private/'state/information/information.sqlite3','conversation':cfg.root/'state/am-conversation-r1/conversation.sqlite3','knowledge':cfg.root/'state/am-conversation-r1/knowledge.sqlite3'}
protected=('action_items','item_feedback','reminder_plans','action_approvals','reminder_occurrences','am_subscriptions','logic_writes','ledger_write_attempts','amdoc_native_documents','amdoc_native_writes')
def inspect():
 db=sqlite3.connect(cfg.db)
 try:
  assert not db.execute("SELECT value FROM meta WHERE key='provider_pause'").fetchone(),'MODEL_PAUSED'
  for table in ('am_inbox','tasks','outbox','reminder_occurrences','logic_writes','ledger_write_attempts'):
   assert not db.execute('SELECT 1 FROM '+table+" WHERE state IN ('processing','running','sending','unknown','stop_unknown','source_wait') LIMIT 1").fetchone(),'ACTIVE_OR_UNKNOWN:'+table
  names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  return {t:{'count':len(rows),'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()} for t in protected if t in names for rows in [[list(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')]]}
 finally:db.close()
model=(cfg.root/'state/model-coordinator.lock').open('a+');fcntl.flock(model,fcntl.LOCK_EX|fcntl.LOCK_NB)
state=json.loads((cfg.root/'state/model-coordinator.json').read_text());assert state['state'] not in ('running','stop_unknown')
inspect();service=ROOT/'local-qwen3.8/feishu-bridge/service.sh';started=time.time();stopped=False;lock=None
backup=private/'validation/am-url-metadata-fix-20261031-01'/str(int(started));backup.mkdir(parents=True,mode=0o700)
try:
 subprocess.run(['/bin/zsh',str(service),'stop'],check=True,capture_output=True);stopped=True
 lock=(private/'state/instance.lock').open('a+')
 for _ in range(180):
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
  except BlockingIOError:time.sleep(.25)
 else:raise RuntimeError('OLD_CONSUMER_STILL_RUNNING')
 source_matches();assert cp.read_bytes()==cfgbytes and pc.read_bytes()==pcbytes and doc.read_bytes()==docbytes
 before=inspect()
 for name,path in dbfiles.items():
  if not path.exists():continue
  db=sqlite3.connect(path);saved=sqlite3.connect(backup/(name+'.sqlite3'));db.backup(saved);saved.close();db.close();(backup/(name+'.sqlite3')).chmod(0o600)
 (backup/'config-before.json').write_bytes(cfgbytes);(backup/'config-before.json').chmod(0o600)
finally:
 if lock:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
 fcntl.flock(model,fcntl.LOCK_UN);model.close()
 if stopped:subprocess.run(['/bin/zsh',str(service),'start'],check=True,capture_output=True)
for _ in range(180):
 manifest=json.loads((private/'state/loaded-manifest.json').read_text());connection=json.loads((private/'state/connection-status.json').read_text())
 if manifest['loaded_at']>=started and connection['state']=='connected':break
 time.sleep(.25)
else:raise RuntimeError('UPDATED_SERVICE_NOT_CONNECTED')
prefixes={'feishu-bridge':'local-qwen3.8/feishu-bridge','fs_agent':'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent','am_doc_engine':'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine','am_conversation':'am-conversation-r1/src/am_conversation'}
for name,h in manifest['files'].items():
 prefix,rel=name.split('/',1);assert hashlib.sha256((ROOT/prefixes[prefix]/rel).read_bytes()).hexdigest()==h,name
source_matches();assert cp.read_bytes()==cfgbytes and pc.read_bytes()==pcbytes and doc.read_bytes()==docbytes
assert inspect()==before,'BUSINESS_STATE_CHANGED_DURING_UPDATE'
consumers=[]
for line in subprocess.check_output(['ps','-axo','pid=,args='],text=True).splitlines():
 parts=line.strip().split(maxsplit=1)
 if len(parts)==2 and Path(parts[1].split(' ',1)[0]).name.lower().startswith('python') and '/feishu-bridge/bridge.py --config ' in parts[1]:consumers.append(int(parts[0]))
assert consumers==[manifest['pid']]
with (private/'state/instance.lock').open('a+') as h:
 try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB);raise RuntimeError('CONSUMER_LOCK_NOT_HELD')
 except BlockingIOError:pass
pin=LocalQwenProvider(cfg).pin()
result={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'updated_at':time.time(),'original_consumer_count':1,'consumer_lock_held':True,'connection_state':connection['state'],'loaded_file_count':len(manifest['files']),'loaded_sources_match':True,'configuration_bytes_unchanged':True,'protected_business_state_unchanged':True,'model':pin['model'],'model_digest':pin['model_digest'],'server_version':pin['server_version'],'model_inference_calls':0,'shared_model_restarted':False,'identity_seconds':600,'ledger_write':False,'conversation_enabled':settings['am_conversation']['enabled'],'information_enabled':settings['am_information']['enabled'],'document_standards_enabled':json.loads(docbytes)['enabled'],'private_backup_created':True}
# Deployment verified: raw temporary database copies are no longer needed.
removed=0
for f in backup.glob('*.sqlite3'):f.unlink();removed+=1
result['temporary_database_backups_removed']=removed
(OUT/'runtime-after.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
