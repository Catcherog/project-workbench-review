"""Check or restore only this release's program files. Never restore business data."""
from pathlib import Path
import argparse,json,hashlib,shutil,socket,datetime
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',required=True);p.add_argument('--runtime-manifest',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
r=json.loads(Path(a.receipt).read_text());target=Path(r['target']);backup=Path(r['backup']);runtime=json.loads(Path(a.runtime_manifest).read_text())
for item in r['changes']:
 rel=Path(item['path']);assert not rel.is_absolute() and '..' not in rel.parts
 assert sha(target/rel)==item['after'],'Current program was edited after installation: '+str(rel)
 if item['before'] is not None:assert sha(backup/'source-before'/rel)==item['before'],'Old program backup mismatch'
for rel,value in runtime.items():assert sha(target/'dist-local'/rel)==value,'Current runtime was rebuilt after installation: '+rel
assert (backup/'runtime-before/dist-local').is_dir()
print(json.dumps({'programFiles':len(r['changes']),'runtimeFiles':len(runtime),'backupReady':True,'businessDataWillBeRestored':False,'mode':'apply' if a.apply else 'check-only'}))
if not a.apply:raise SystemExit(0)
with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',5173))!=0,'Close the daily app before program rollback'
retained=backup/('program-before-rollback-'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S'));retained.mkdir(exist_ok=False)
for item in r['changes']:
 rel=Path(item['path']);dest=target/rel;saved=retained/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,saved)
 if item['before'] is None:dest.unlink()
 else:shutil.copy2(backup/'source-before'/rel,dest)
(target/'dist-local').rename(retained/'dist-local')
shutil.copytree(backup/'runtime-before/dist-local',target/'dist-local')
print('Program restored; business database, attachments, settings and browser storage were not replaced.')
