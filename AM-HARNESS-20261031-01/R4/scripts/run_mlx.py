"""One isolated R4 mechanics run under the original lease and resource gates."""
from pathlib import Path
import argparse
import os
import subprocess

task = Path(__file__).resolve().parents[1]
root = task.parents[1]
source = task / 'worktree'
python = root / 'SFT训练/R6-FIX1_20261021_01/.venv/bin/python'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-name', required=True)
args = parser.parse_args()
if not args.run_name.startswith('mlx-mechanics-') or Path(args.run_name).name != args.run_name:
    raise ValueError('A fresh local mechanics run name is required')
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
           PYTHONPATH=os.pathsep.join(map(str, [source / 'am-conversation-r1/src', source / 'am-style-r3'])))
argv = [str(python), '-m', 'training.mlx_r4',
        '--manifest', str(task / 'private/mlx-base.json'),
        '--config', str(task / 'private/mlx-mechanics.json'),
        '--output', str(task / 'private' / args.run_name), '--execute']
with (task / 'evidence' / (args.run_name + '-execute.log')).open('xb') as log:
    result = subprocess.run(argv, cwd=source / 'am-style-r3', env=env,
                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
print('mechanics parent exit:', result.returncode, flush=True)
raise SystemExit(result.returncode)
