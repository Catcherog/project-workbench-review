"""Read-only aggregate runtime observation; never export raw user records."""
import json,sqlite3,time,sys,hashlib,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'))
from fs_agent.config import Config
private=Path.home()/'.local/share/local-qwen-feishu';cp=private/'config.json';settings=json.loads(cp.read_text());cfg=Config.load(Path(settings['poc_config']))
def ro(path):
 db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;return db
manifest=json.loads((private/'state/loaded-manifest.json').read_text());connection=json.loads((private/'state/connection-status.json').read_text());model=json.loads((cfg.root/'state/model-coordinator.json').read_text())
g=ro(cfg.db);i=ro(private/'state/information/information.sqlite3')
result={'observed_at':time.time(),'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
 'read_only':True,'connection_state':connection['state'],'loaded_at':manifest['loaded_at'],'loaded_count':len(manifest['files']),
 'model_coordinator_state':model['state'],'ledger_write':settings['am_self']['ledger_write'],'identity_seconds':settings['am_query']['identity_cache_seconds'],
 'configuration_hashes':{'bridge':hashlib.sha256(cp.read_bytes()).hexdigest(),'poc':hashlib.sha256(Path(settings['poc_config']).read_bytes()).hexdigest(),'documents':hashlib.sha256((cfg.root/'config/document-standards.json').read_bytes()).hexdigest()},
 'gateway':{t:[dict(r) for r in g.execute('SELECT state,count(*) AS n FROM '+t+' GROUP BY state')] for t in ('am_inbox','tasks','outbox','reminder_occurrences','logic_writes','ledger_write_attempts')},
 'information':{'sources':[dict(r) for r in i.execute('SELECT availability,count(*) AS n FROM sources GROUP BY availability')],
    'jobs':[dict(r) for r in i.execute('SELECT kind,state,count(*) AS n FROM jobs GROUP BY kind,state')],
    'discovery_pending':i.execute("SELECT count(*) FROM host_discovery_state WHERE key LIKE 'child_pending:%'").fetchone()[0],
    'discovery_attempted':i.execute("SELECT count(*) FROM host_discovery_state WHERE key LIKE 'child_pending:%' AND json_extract(value,'$.attempts')>0").fetchone()[0],
    'discovery_backoff':i.execute("SELECT count(*) FROM host_discovery_state WHERE key LIKE 'child_pending:%' AND json_extract(value,'$.next_retry_at')>?",(time.time(),)).fetchone()[0],
    'processed_children':i.execute("SELECT count(*) FROM host_discovery_state WHERE key LIKE 'child:%' AND json_extract(value,'$.excluded') IS NULL").fetchone()[0],
    'open_gaps':[dict(r) for r in i.execute("SELECT kind,count(*) AS n FROM gaps WHERE state='open' GROUP BY kind")]}}
result['information']['source_access_version_present']=bool(i.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_access_version'").fetchone())
g.close();i.close()
name=sys.argv[1] if len(sys.argv)>1 else 'runtime-observation.json';(OUT/name).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
