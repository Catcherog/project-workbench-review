"""Assemble the two fixed releases plus this minimal overlay in a new directory."""
import shutil,sys
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];base=Path(sys.argv[1]).resolve();coordinated=Path(sys.argv[2]).resolve();out=Path(sys.argv[3]).resolve()
if out.exists():raise SystemExit('Destination must not exist')
shutil.copytree(base/'source',out)
for overlay in (coordinated,HERE):
 for p in (overlay/'source').rglob('*'):
  if p.is_file():
   dest=out/p.relative_to(overlay/'source');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
folder=out/'AM-CONVERSATION-20261030-01/R1/coordination/20261031/url-metadata-fix';folder.mkdir(parents=True,exist_ok=True)
shutil.copyfile(HERE/'scripts/run_joint_checks.py',folder/'run_joint_checks.py')
print('Reconstructed:',out)
