"""Read-only verification of original consumer, loaded bytes, gates and model pin."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--runtime-root',type=Path,required=True)
p.add_argument('--expected-commit',required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();root=a.runtime_root.resolve()
sys.path.insert(0,str(root/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'))
from fs_agent.config import Config
from fs_agent.qwen_provider import LocalQwenProvider
private=Path.home()/'.local/share/local-qwen-feishu'
settings=json.loads((private/'config.json').read_text());cfg=Config.load(Path(settings['poc_config']))
state=Path(settings['state_directory'])
manifest=json.loads((state/'loaded-manifest.json').read_text())
connection=json.loads((state/'connection-status.json').read_text())
prefixes={'feishu-bridge':root/'local-qwen3.8/feishu-bridge',
          'am_conversation':root/'am-conversation-r1/src/am_conversation',
          'am_reply':root/'am-conversation-r1/src/am_reply',
          'am_outcome':root/'am-conversation-r1/src/am_outcome',
          'am_response':root/'am-conversation-r1/src/am_response',
          **{name:root/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'/name for name in ('fs_agent','am_doc_engine','am_harness')}}
mismatches=[]
for name,expected in manifest['files'].items():
    prefix,relative=name.split('/',1)
    if hashlib.sha256((prefixes[prefix]/relative).read_bytes()).hexdigest()!=expected:mismatches.append(name)
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
if commit!=a.expected_commit or mismatches:raise RuntimeError('RUNTIME_SOURCE_MISMATCH')
if connection['state']!='connected':raise RuntimeError('ORIGINAL_SERVICE_NOT_CONNECTED')
if manifest['config_sha256']!=hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest():raise RuntimeError('RUNTIME_CONFIG_MISMATCH')
consumers=[]
for line in subprocess.check_output(['ps','-axo','pid=,args='],text=True).splitlines():
    parts=line.strip().split(maxsplit=1)
    if len(parts)==2 and Path(parts[1].split(' ',1)[0]).name.lower().startswith('python') and '/feishu-bridge/bridge.py --config ' in parts[1]:consumers.append(int(parts[0]))
if len(consumers)!=1 or consumers[0]!=manifest['pid']:raise RuntimeError('CONSUMER_COUNT_MISMATCH')
with (state/'instance.lock').open('a+') as lock:
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:locked=True
    else:raise RuntimeError('ORIGINAL_LOCK_NOT_HELD')
pin=LocalQwenProvider(cfg).pin()
db=sqlite3.connect('file:'+str(cfg.db)+'?mode=ro',uri=True)
if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('DATABASE_INTEGRITY_FAILED')
if db.execute("SELECT value FROM meta WHERE key='provider_pause'").fetchone():raise RuntimeError('MODEL_PAUSED')
assert settings['am_self']['ledger_write'] is False
assert settings['am_query']['identity_cache_seconds']==600
lane=None
if settings.get('am_harness',{}).get('durable_queue_enabled'):
    lane=db.execute('SELECT state FROM am_harness_lane').fetchone()[0]
    status=json.loads((cfg.root/'state/am-harness-r1/status.json').read_text())
    assert status['strict_bound'] is True
    assert any(k.startswith('am_harness/') for k in manifest['files'])
result={'source_commit':commit,'verified_at':time.time(),'loaded_at':manifest['loaded_at'],
        'loaded_files':len(manifest['files']),'loaded_bytes_match':True,'consumer_count':1,
        'original_instance_lock_held':locked,'connection':'connected','model':pin['model'],
        'model_pin_verified':True,'model_server_version':pin['server_version'],
        'model_digest':manifest['model_digest'],'identity_cache_seconds':600,'ledger_write':False,
        'harness':settings.get('am_harness',{}),'lane_state':lane,'model_paused':False,
        'sqlite_integrity':'ok','new_model_inference_calls':0,'new_consumers_created':0}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
