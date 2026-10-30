"""Rebuild pinned UX1 + pinned UX2 + this FIX1; never touch an existing tree."""
import subprocess,sys,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
repo=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).expanduser().resolve()
if out.exists():raise SystemExit('Destination must not exist')
out.mkdir(parents=True)
for pin,prefix in [('1edb0d66ade949dacdf4324af848e39d515f0643','AM-SELF-20261029-01/UX1/source/'),('2f4df3ca0fcde6061dd211686b26b301fdd2d680','AM-SELF-20261029-01/UX2/source/'),('a963fbdd1e10fe93ac9bda48b45f933adf82fb57','AM-SELF-20261029-01/UX2-FIX1/source/')]:
 for line in subprocess.check_output(['git','-C',str(repo),'ls-tree','-r',pin,'--',prefix]).splitlines():
  meta,name=line.split(b'\t',1);mode,kind,sha=meta.split();relative=name.decode()[len(prefix):]
  if kind!=b'blob' or mode not in (b'100644',b'100755') or '..' in Path(relative).parts:raise SystemExit('Unexpected source entry')
  dst=out/relative;dst.parent.mkdir(exist_ok=True,parents=True)
  dst.write_bytes(subprocess.check_output(['git','-C',str(repo),'cat-file','blob',sha.decode()]));dst.chmod(int(mode,8)&0o777)
for src in (HERE/'source').rglob('*'):
 if src.is_file():
  dst=out/src.relative_to(HERE/'source');dst.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(src,dst)
task=out/'AM-SELF-20261029-01/UX3'
(task/'scripts').mkdir(parents=True,exist_ok=True);(task/'evidence').mkdir(exist_ok=True)
shutil.copyfile(HERE/'scripts/run_affected_tests.py',task/'scripts/run_affected_tests.py')
print('Reconstructed:',out)
