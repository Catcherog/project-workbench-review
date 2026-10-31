"""Install Harness FIX1 on the current R2 service; preserve all configuration bytes.

Explicit operator action only. No baseline copying, second consumer, provider
restart, authorization widening, database rollback or pause clearing.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime-root',type=Path,required=True)
parser.add_argument('--expected-commit',required=True)
parser.add_argument('--source-commit',required=True)
args=parser.parse_args();root=args.runtime_root.resolve()
if not all(__import__('re').fullmatch('[a-f0-9]{40}', value) for value in (args.expected_commit,args.source_commit)):
    raise ValueError('EXACT_SOURCE_COMMIT_REQUIRED')
private=Path.home()/'.local/share/local-qwen-feishu'
config_path=private/'config.json';raw=config_path.read_bytes();cfg=json.loads(raw)
poc_raw=Path(cfg['poc_config']).read_bytes();poc=json.loads(poc_raw)
state=Path(poc['service']['root_directory'])/'state';dbpath=state/'gateway.sqlite3'
bridge_state=Path(cfg['state_directory'])
service=root/'local-qwen3.8/feishu-bridge/service.sh'
def git(*arguments):return subprocess.check_output(['git',*arguments],cwd=root,text=True).strip()
if git('rev-parse','HEAD')!=args.expected_commit:raise RuntimeError('CONCURRENT_SOURCE_HEAD_CHANGED')
if subprocess.run(['git','diff','--quiet'],cwd=root).returncode or subprocess.run(['git','diff','--cached','--quiet'],cwd=root).returncode:
    raise RuntimeError('CONCURRENT_TRACKED_MODIFICATIONS')
if cfg['am_self']['ledger_write'] is not False:raise RuntimeError('LEDGER_WRITE_NOT_DISABLED')
subprocess.run(['git','cat-file','-e',args.source_commit+':am-conversation-r1/src/am_conversation/rewrite_host.py'],cwd=root,check=True,capture_output=True)
subprocess.run(['git','merge-base','--is-ancestor',args.expected_commit,args.source_commit],cwd=root,check=True,capture_output=True)
def consumers():
    found=[]
    for line in subprocess.check_output(['ps','-axo','pid=,args='],text=True).splitlines():
        parts=line.strip().split(maxsplit=1)
        if len(parts)==2 and Path(parts[1].split(' ',1)[0]).name.lower().startswith('python') and '/feishu-bridge/bridge.py --config ' in parts[1]:found.append(int(parts[0]))
    return found
def idle():
    validation=state/'am-conversation-r2'
    if list((validation/'requests').glob('*.json')):
        raise RuntimeError('R2_VALIDATION_PENDING')
    if any(not (validation/'results'/(p.stem+'.json')).exists() for p in (validation/'requests').glob('*.claimed')):
        raise RuntimeError('R2_VALIDATION_IN_FLIGHT')
    with sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True) as db:
        for sql in ("SELECT count(*) FROM tasks WHERE state='running'",
                    "SELECT count(*) FROM am_inbox WHERE state IN ('processing','harness_admitting')",
                    "SELECT count(*) FROM outbox WHERE state IN ('sending','pending') AND expires>strftime('%s','now')"):
            if db.execute(sql).fetchone()[0]:raise RuntimeError('SERVICE_WORK_IN_FLIGHT')
        if db.execute("SELECT value FROM meta WHERE key='provider_pause'").fetchone():raise RuntimeError('PROVIDER_PAUSE_REQUIRES_RECONCILIATION')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='am_harness_lane'").fetchone():
            if db.execute('SELECT state FROM am_harness_lane').fetchone()[0]!='idle':raise RuntimeError('HARNESS_LANE_NOT_IDLE')
            if db.execute("SELECT count(*) FROM am_harness_runs WHERE state IN ('queued','running')").fetchone()[0]:raise RuntimeError('HARNESS_WORK_PENDING')
    with sqlite3.connect('file:'+str(bridge_state/'chat.sqlite3')+'?mode=ro',uri=True) as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'inbox' in tables:
            columns={r[1] for r in db.execute('PRAGMA table_info(inbox)')}
            if 'state' in columns and db.execute("SELECT count(*) FROM inbox WHERE state IN ('processing','sending')").fetchone()[0]:raise RuntimeError('ORDINARY_CHAT_IN_FLIGHT')
    model=state/'model-coordinator.json'
    if model.exists() and json.loads(model.read_text()).get('state') in ('running','stop_unknown'):
        raise RuntimeError('MODEL_EXECUTION_NOT_RESOLVED')
# Hold the existing cross-process model lease before stopping the bridge.
# A read-only idle sample alone races with the information background worker.
model_lease=(state/'model-coordinator.lock').open('a+')
fcntl.flock(model_lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
idle()
if len(consumers())!=1:raise RuntimeError('ORIGINAL_CONSUMER_NOT_UNIQUE')
backup=private/'validation/am-harness-r1-fix1'/('install-'+str(int(time.time())))
backup.mkdir(parents=True,mode=0o700)
subprocess.run(['/bin/zsh',str(service),'stop'],check=True,capture_output=True)
try:
    deadline=time.monotonic()+25
    while consumers() and time.monotonic()<deadline:time.sleep(.2)
    if consumers():raise RuntimeError('OLD_CONSUMER_HAS_NOT_STOPPED')
    idle()
    if config_path.read_bytes()!=raw or Path(cfg['poc_config']).read_bytes()!=poc_raw:
        raise RuntimeError('CONCURRENT_CONFIGURATION_CHANGED')
    with (bridge_state/'instance.lock').open('a+') as bridge_lock,(state/'instance.lock').open('a+') as gateway_lock:
        for lock in (bridge_lock,gateway_lock):fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        (backup/'config.before.json').write_bytes(raw);(backup/'config.before.json').chmod(0o600)
        for source,name in ((dbpath,'gateway.sqlite3'),(bridge_state/'chat.sqlite3','chat.sqlite3')):
            with sqlite3.connect(source) as source_db,sqlite3.connect(backup/name) as target_db:source_db.backup(target_db)
            (backup/name).chmod(0o600)
        if git('rev-parse','HEAD')!=args.expected_commit:raise RuntimeError('CONCURRENT_SOURCE_HEAD_CHANGED')
        if args.source_commit!=args.expected_commit:
            subprocess.run(['git','merge','--ff-only',args.source_commit],cwd=root,check=True,capture_output=True)
        if config_path.read_bytes()!=raw or Path(cfg['poc_config']).read_bytes()!=poc_raw:
            raise RuntimeError('CONCURRENT_CONFIGURATION_CHANGED')
finally:
    # Only the original launchd service is restarted; no Qwen/Ollama commands.
    subprocess.run(['/bin/zsh',str(service),'start'],check=True,capture_output=True)
summary={'configuration_bytes_unchanged':config_path.read_bytes()==raw,'scope':'owner_private_only','source_commit':git('rev-parse','HEAD'),'previous_commit':args.expected_commit,
         'installed_at':time.time(),'original_poc_config_unchanged':Path(cfg['poc_config']).read_bytes()==poc_raw,
         'previous_settings_hash':hashlib.sha256(raw).hexdigest(),'protected_settings_unchanged':True,
         'ledger_write':False,'backup_created_privately':True}
(backup/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary))
