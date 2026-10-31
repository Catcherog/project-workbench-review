"""Overlay fixed review inputs into a new isolated directory, never production."""
import shutil,sys
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
base,unified,url_fix,out=[Path(x).resolve() for x in sys.argv[1:]]
if out.exists():raise SystemExit('Destination must not exist')
shutil.copytree(base/'source',out)
for overlay in (unified,url_fix,HERE):
 for p in (overlay/'source').rglob('*'):
  if p.is_file():
   dst=out/p.relative_to(overlay/'source');dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
folder=out/'AM-CONVERSATION-20261030-01/R1-FIX1';folder.mkdir(parents=True,exist_ok=True)
shutil.copy2(HERE/'scripts/run_joint_checks.py',folder/'run_joint_checks.py')
print('Reconstructed:',out)
