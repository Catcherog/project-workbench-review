"""Read-only wait for a current source/model window; no provider retry or pause change."""
from pathlib import Path
import json,sqlite3,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[3];private=Path.home()/'.local/share/local-qwen-feishu';cfg=json.loads((private/'config.json').read_text());pc=json.loads(Path(cfg['poc_config']).read_text());state=Path(pc['service']['root_directory'])/'state';info=Path(cfg['state_directory'])/'information/information.sqlite3'
start=time.monotonic();stable=None;last=None
while time.monotonic()-start<90:
    with sqlite3.connect(info.resolve().as_uri()+'?mode=ro',uri=True) as db:revision=db.execute('SELECT revision FROM source_access_version WHERE singleton=1').fetchone()[0]
    status=json.loads((state/'model-coordinator.json').read_text())['state']
    if revision!=last or status in ('running','stop_unknown'):
        stable=None;last=revision
    elif stable is None:stable=time.monotonic()
    elif time.monotonic()-stable>=15:break
    time.sleep(.5)
else:raise RuntimeError('STABLE_SOURCE_WINDOW_NOT_OBSERVED')
print(json.dumps({'stable_source_window_seconds':15,'model_idle_before_submission':True}),flush=True)
subprocess.run([sys.executable,str(Path(__file__).with_name('live_checks.py')),*sys.argv[1:]],cwd=ROOT,check=True)
