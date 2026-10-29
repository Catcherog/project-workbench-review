"""Reconstruct fixed UX1 source plus UX2 overlay; never modifies a live service."""
import subprocess,sys,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
REPO=HERE.parents[1]
PIN='1edb0d66ade949dacdf4324af848e39d515f0643'
PREFIX='AM-SELF-20261029-01/UX1/source/'
out=Path(sys.argv[1]).expanduser().resolve()
if out.exists():raise SystemExit('Destination must not exist')
out.mkdir(parents=True)
for line in subprocess.check_output(['git','ls-tree','-r',PIN,'--',PREFIX],cwd=REPO).splitlines():
 meta,name=line.split(b'\t',1);mode,kind,sha=meta.split();name=name.decode()
 if kind!=b'blob' or mode not in (b'100644',b'100755'):raise SystemExit('Unexpected baseline entry')
 relative=name[len(PREFIX):];target=out/relative
 if '..' in Path(relative).parts:raise SystemExit('Invalid baseline path')
 target.parent.mkdir(exist_ok=True,parents=True)
 target.write_bytes(subprocess.check_output(['git','cat-file','blob',sha.decode()],cwd=REPO));target.chmod(int(mode,8)&0o777)
for source in (HERE/'source').rglob('*'):
 if source.is_file():
  target=out/source.relative_to(HERE/'source');target.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(source,target)
print('Reconstructed source:',out)
