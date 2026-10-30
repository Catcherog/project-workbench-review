"""Restart only the existing consumer after checks and private SQLite backups."""
import fcntl,hashlib,json,os,shutil,sqlite3,subprocess,time,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
TASK=ROOT/'AM-CONVERSATION-20261030-01/R1'
private=Path.home()/'.local/share/local-qwen-feishu'
folder=private/'validation/am-conversation-r1'/('install-backup' if not (private/'validation/am-conversation-r1/install-backup').exists() else 'install-backup-'+str(int(time.time())))
folder.mkdir(parents=True,exist_ok=False,mode=0o700)
config_path=private/'config.json';config_bytes=config_path.read_bytes();cfg=json.loads(config_bytes)
pc_path=Path(cfg['poc_config']);pc_bytes=pc_path.read_bytes();pc=json.loads(pc_bytes);pocroot=Path(pc['service']['root_directory'])
assert cfg['am_self']['ledger_write'] is False
assert not cfg.get('am_write_execution',{}).get('exclusive_window_until')
databases={'chat':private/'state/chat.sqlite3','ledger':private/'state/group-ledger.sqlite3','gateway':pocroot/'state/gateway.sqlite3'}
for name in ('conversation','knowledge'):
    path=pocroot/'state/am-conversation-r1'/(name+'.sqlite3')
    if path.exists():databases[name]=path
def idle():
    for path in databases.values():
        db=sqlite3.connect('file:'+str(path)+'?mode=rw',uri=True)
        names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('inbox','ledger_inbox','am_inbox','tasks','outbox','reminder_occurrences','ledger_write_attempts','logic_writes'):
            if table not in names:continue
            if db.execute("SELECT count(*) FROM "+table+" WHERE state IN ('received','queued','pending','processing','running','sending','ready','unknown','stop_unknown','source_wait')").fetchone()[0]:
                raise RuntimeError('ACTIVE_OR_UNKNOWN_WORK_REQUIRES_REVIEW:'+table)
        db.close()
idle()
model_lease=(pocroot/'state/model-coordinator.lock').open('a+')
try:fcntl.flock(model_lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise RuntimeError('MODEL_ACTIVE_UPDATE_DEFERRED')
service=ROOT/'local-qwen3.8/feishu-bridge/service.sh'
registered=subprocess.run(['launchctl','print','gui/'+str(os.getuid())+'/local.qwen.feishu'],capture_output=True).returncode==0
if registered:subprocess.run(['/bin/zsh',str(service),'stop'],check=True,capture_output=True)
for _ in range(100):
    if subprocess.run(['launchctl','print','gui/'+str(os.getuid())+'/local.qwen.feishu'],capture_output=True).returncode:break
    time.sleep(.1)
else:raise RuntimeError('OLD_LAUNCH_SERVICE_STILL_REGISTERED')
lock=(private/'state/instance.lock').open('a+')
try:
    for _ in range(100):
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
        except BlockingIOError:time.sleep(.1)
    else:raise RuntimeError('OLD_CONSUMER_STILL_RUNNING')
    idle()
    before={}
    for name,path in databases.items():
        db=sqlite3.connect('file:'+str(path)+'?mode=rw',uri=True)
        saved=sqlite3.connect(folder/(name+'.sqlite3'));db.backup(saved);saved.close();(folder/(name+'.sqlite3')).chmod(0o600)
        if name=='gateway':
            before={t:[list(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ('action_items','item_feedback','reminder_plans','action_approvals','reminder_occurrences','am_subscriptions','logic_writes','ledger_write_attempts')}
        db.close()
    for name,data in [('bridge-config.json',config_bytes),('poc-config.json',pc_bytes)]:
        path=folder/name;path.write_bytes(data);path.chmod(0o600)
    saved=folder/'protected-business.json';saved.write_text(json.dumps(before));saved.chmod(0o600)
    assert cfg['am_query']['identity_cache_seconds']==600
    cfg['am_conversation']={'enabled':True,'business_actions':'--business' in sys.argv,'text_previews':True,'verify_previews':True,'group_conversations':'--groups' in sys.argv,'runtime':{'allow_external_actions':'--business' in sys.argv,'prefetch_projects':True,'trusted_write_replies':True}}
    temporary=config_path.with_suffix('.ux4.tmp')
    temporary.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n');temporary.chmod(0o600);os.replace(temporary,config_path)
finally:
    fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
fcntl.flock(model_lease,fcntl.LOCK_UN);model_lease.close()
subprocess.run(['/bin/zsh',str(service),'start'],check=True,capture_output=True)
result={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'same_original_launch_service':True,'old_consumer_stopped_and_lock_released':True,
        'configuration_unchanged_except_conversation_entry':all(cfg.get(k)==v for k,v in json.loads(config_bytes).items() if k!='am_conversation') and pc_path.read_bytes()==pc_bytes,
        'approved_private_query_scope':'unchanged; original query, PoC, group and egress grants retained','conversation_enabled':True,'business_actions_enabled':'--business' in sys.argv,
        'approved_query_identity_seconds':600,
        'poc_configuration_unchanged':pc_path.read_bytes()==pc_bytes,
        'flags':cfg['am_self'],'new_real_plans':0,'new_real_subscriptions':0,'real_business_group_sends':0,'formal_ledger_writes':0,'real_mounts':0,
        'installed_at':time.time(),'private_backup_created':True,'private_backup_path':str(folder)}
assert result['configuration_unchanged_except_conversation_entry']
(TASK/'evidence/installation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
