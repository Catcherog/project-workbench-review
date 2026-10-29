"""Read actual loaded files, process lock, model pin, and migrated database state."""
import fcntl,hashlib,json,os,sqlite3,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'))
from fs_agent.config import Config
from fs_agent.qwen_provider import LocalQwenProvider
TASK=ROOT/'AM-SELF-20261029-01/R1-FIX1';private=Path.home()/'.local/share/local-qwen-feishu'
cfg=json.loads((private/'config.json').read_text());config=Config.load(Path(cfg['poc_config']))
installed=json.loads((TASK/'evidence/installation.json').read_text())
for _ in range(60):
    manifest=json.loads((private/'state/loaded-manifest.json').read_text())
    connection=json.loads((private/'state/connection-status.json').read_text())
    if manifest['loaded_at']>=installed['installed_at']-5 and connection['state']=='connected':break
    time.sleep(.5)
else:raise RuntimeError('UPDATED_SERVICE_NOT_CONNECTED')
mismatches=[]
for key,expected in manifest['files'].items():
    prefix,rel=key.split('/',1)
    base=ROOT/('local-qwen3.8/feishu-bridge' if prefix=='feishu-bridge' else 'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent')
    if hashlib.sha256((base/rel).read_bytes()).hexdigest()!=expected:mismatches.append(key)
consumers=[]
for line in subprocess.check_output(['ps','-axo','pid=,args='],text=True).splitlines():
    parts=line.strip().split(maxsplit=1)
    if len(parts)==2 and Path(parts[1].split(' ',1)[0]).name.lower().startswith('python') and '/feishu-bridge/bridge.py --config ' in parts[1]:consumers.append(int(parts[0]))
locked=False
with (private/'state/instance.lock').open('a+') as h:
    try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:locked=True
assert not mismatches and len(consumers)==1 and consumers[0]==manifest['pid'] and locked
assert manifest['features']['ledger_write'] is False and cfg['am_self']['ledger_write'] is False
assert manifest['config_sha256']==hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest()
pin=LocalQwenProvider(config).pin()
db=sqlite3.connect('file:'+str(config.db)+'?mode=ro',uri=True)
before=json.loads((private/'validation/am-self-20261029-r1-fix1/install-backup/protected-business.json').read_text())
assert all(before[t]==[list(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in before)
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert 'decision_version' in {r[1] for r in db.execute('PRAGMA table_info(action_items)')}
assert db.execute("SELECT value FROM meta WHERE key='R1-FIX1-precheck-hash-1'").fetchone()[0]=='done'
result=dict(installed,verified_at=time.time(),current_python_consumers=len(consumers),consumer_lock_held=locked,
            loaded_files_match=True,checked_loaded_files=len(manifest['files']),connection_state=connection['state'],
            model=pin['model'],server_version=pin['server_version'],model_pin_verified=True,model_inference_calls=0,
            dependencies=manifest['dependencies'],business_rows_preserved=True,sqlite_integrity='ok',migrations_applied=True,
            new_business_counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('action_items','item_feedback','reminder_plans','reminder_occurrences','am_subscriptions','ledger_write_attempts')},
            preexisting_mount_receipts_preserved=db.execute("SELECT count(*) FROM logic_writes WHERE state='committed'").fetchone()[0])
db.close();(TASK/'evidence/runtime-verified.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
