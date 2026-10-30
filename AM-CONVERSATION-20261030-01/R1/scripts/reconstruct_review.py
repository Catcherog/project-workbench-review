"""Reconstruct only in a new directory; no production service starts."""
import shutil,sys
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];out=Path(sys.argv[1]).expanduser().resolve()
if out.exists():raise SystemExit('Destination must not exist')
shutil.copytree(HERE/'source',out)
task=out/'AM-CONVERSATION-20261030-01/R1';task.mkdir(parents=True)
shutil.copytree(HERE/'scripts',task/'scripts');(task/'evidence').mkdir()
shutil.copytree(HERE/'reference_am',out/'reference_am')
print('Reconstructed:',out)
