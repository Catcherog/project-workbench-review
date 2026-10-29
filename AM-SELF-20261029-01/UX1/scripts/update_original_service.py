"""Restart only the existing consumer after checks and private SQLite backups."""
import fcntl,hashlib,json,os,shutil,sqlite3,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
TASK=ROOT/'AM-SELF-20261029-01/UX1'
private=Path.home()/'.local/share/local-qwen-feishu'
folder=private/'validation/am-self-20261029-ux1/install-backup'
folder.mkdir(parents=True,exist_ok=False,mode=0o700)
config_path=private/'config.json';config_bytes=config_path.read_bytes();cfg=json.loads(config_bytes)
pc_path=Path(cfg['poc_config']);pc_bytes=pc_path.read_bytes();pc=json.loads(pc_bytes);pocroot=Path(pc['service']['root_directory'])
assert cfg['am_self']['ledger_write'] is False
assert not cfg.get('am_write_execution',{}).get('exclusive_window_until')
databases={'chat':private/'state/chat.sqlite3','ledger':private/'state/group-ledger.sqlite3','gateway':pocroot/'state/gateway.sqlite3'}
def idle():
    for path in databases.values():
        db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
        names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('inbox','ledger_inbox','am_inbox','tasks','outbox','reminder_occurrences','ledger_write_attempts','logic_writes'):
            if table not in names:continue
            if db.execute("SELECT count(*) FROM "+table+" WHERE state IN ('received','queued','pending','processing','running','sending','ready','unknown','stop_unknown')").fetchone()[0]:
                raise RuntimeError('ACTIVE_OR_UNKNOWN_WORK_REQUIRES_REVIEW:'+table)
        db.close()
idle()
service=ROOT/'local-qwen3.8/feishu-bridge/service.sh'
subprocess.run(['/bin/zsh',str(service),'stop'],check=True,capture_output=True)
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
        db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
        saved=sqlite3.connect(folder/(name+'.sqlite3'));db.backup(saved);saved.close();(folder/(name+'.sqlite3')).chmod(0o600)
        if name=='gateway':
            before={t:[list(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ('item_feedback','reminder_plans','action_approvals','reminder_occurrences','am_subscriptions','logic_writes','ledger_write_attempts')}
        db.close()
    for name,data in [('bridge-config.json',config_bytes),('poc-config.json',pc_bytes)]:
        path=folder/name;path.write_bytes(data);path.chmod(0o600)
    saved=folder/'protected-business.json';saved.write_text(json.dumps(before));saved.chmod(0o600)
finally:
    fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
subprocess.run(['/bin/zsh',str(service),'start'],check=True,capture_output=True)
result={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'same_original_launch_service':True,'old_consumer_stopped_and_lock_released':True,
        'configuration_unchanged':config_path.read_bytes()==config_bytes and pc_path.read_bytes()==pc_bytes,
        'flags':cfg['am_self'],'new_real_plans':0,'new_real_subscriptions':0,'real_group_sends':0,'formal_ledger_writes':0,'real_mounts':0,
        'installed_at':time.time(),'private_backup_created':True}
assert result['configuration_unchanged']
(TASK/'evidence/installation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
