"""Run one original-machine contract suite; fixtures never become business data."""
from pathlib import Path
import argparse, hashlib, json, os, platform, sys, time, unittest

TASK = Path(__file__).resolve().parents[1]
WORK = TASK / 'worktree'
PACKAGE = WORK / 'am-style-r5'
p = argparse.ArgumentParser()
p.add_argument('mode', choices=('bundled', 'host', 'r4'))
a = p.parse_args()
source = PACKAGE / 'baseline' if a.mode == 'bundled' else WORK
roots = [PACKAGE / 'src', source / 'am-conversation-r1/src', source / 'am-style-r3']
sys.path[:0] = list(map(str, roots))
os.environ.update(PYTHONPATH=os.pathsep.join(map(str, roots)),
                  AM_R5_HOST_SRC=str(roots[1]), AM_R5_TRAINING_ROOT=str(roots[2]),
                  PYTHONDONTWRITEBYTECODE='1', TMPDIR=str((TASK / 'tmp').resolve()))
sys.dont_write_bytecode = True
start = time.monotonic()
test_dir = WORK / 'am-style-r3/tests' if a.mode == 'r4' else PACKAGE / 'tests'
suite = unittest.defaultTestLoader.discover(str(test_dir), pattern='test_mlx_r4.py' if a.mode == 'r4' else 'test*.py')
log = TASK / 'evidence' / (a.mode + '-contracts.log')
with log.open('w') as stream:
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
report = {'mode': a.mode, 'python': sys.version, 'system': platform.platform(),
          'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
          'skipped': len(result.skipped), 'exit_code': 0 if result.wasSuccessful() else 1,
          'elapsed_seconds': time.monotonic() - start, 'import_roots': list(map(str, roots)),
          'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
          'failure_names': [str(t) for t, _ in result.failures],
          'error_names': [str(t) for t, _ in result.errors],
          'synthetic_contracts_only': True, 'actual_training_runs': 0,
          'actual_model_calls': 0, 'business_acceptance': False,
          'mlx_imported': any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules)}
(TASK / 'evidence' / (a.mode + '-contracts.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False))
raise SystemExit(report['exit_code'])
