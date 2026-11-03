"""Observe native R5 CLI control flow; forbid an unexpected trainer during rejection tests."""
from pathlib import Path
import json, os, runpy, sys

TASK = Path(__file__).resolve().parents[1]
label, *arguments = sys.argv[1:]
events = []
def audit(event, args):
    if event != 'subprocess.Popen': return
    argv = list(args[1])
    trainer = 'training.mlx_r4' in argv and '--execute' in argv
    events.append({'trainer': trainer, 'metadata_probe': '-c' in argv,
                   'executable_name': Path(str(argv[0])).name})
    if trainer:
        raise AssertionError('UNEXPECTED_TRAINER_ATTEMPT_IN_MISSING_HOLDOUT_CHECK')
sys.addaudithook(audit)
sys.argv = [str(TASK / 'worktree/am-style-r5/run.py'), *arguments]
code = 1
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
    code = 0
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else 1
finally:
    report = {'label': label, 'exit_code': code, 'subprocess_events': events,
              'trainer_start_attempts': sum(x['trainer'] for x in events),
              'metadata_probe_subprocesses': sum(x['metadata_probe'] for x in events),
              'mlx_imported': any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules),
              'actual_training_runs': 0,
              'protection': 'Unexpected trainer attempts are counted and would raise before OS process creation.'}
    (TASK / 'private' / (label + '.audit.json')).write_text(json.dumps(report, indent=2) + '\n')
raise SystemExit(code)
