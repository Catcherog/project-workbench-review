"""Recheck actual existing gold/mechanics with the patched CLI. Never fabricate holdout."""
from pathlib import Path
import hashlib, json, os, subprocess, sys, time

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[1]
WORK = TASK / 'worktree'
sys.path[:0] = [str(WORK / 'am-style-r5/src'), str(WORK / 'am-conversation-r1/src'), str(WORK / 'am-style-r3')]
from am_style_r5.common import seal
from am_style_r5.dataset import verify_gold_snapshot
from am_style_r5.pilot import _source_binding, _original_mechanics

def read(p): return json.loads(p.read_text())
def h(p): return hashlib.sha256(p.read_bytes()).hexdigest()
old = ROOT / 'AM-HARNESS-20261031-01/R5/private/feedback-003/pilot-plan-001/plan.json'
old_plan = read(old)
snapshot_path = Path(old_plan['snapshot']['path'])
snapshot_before = {str(p): h(p) for p in snapshot_path.parent.rglob('*') if p.is_file()}
snapshot = verify_gold_snapshot(snapshot_path)
assert snapshot['counts']['train'] == 24 and snapshot['counts']['dev'] == 8
assert snapshot['counts']['train_groups'] == 14 and snapshot['counts']['dev_groups'] == 5
roots = {'training': str(WORK / 'am-style-r3'), 'am_style': str(WORK / 'am-conversation-r1/src')}
binding = _source_binding(roots)
mechanics = Path(old_plan['mechanics_result']['path']); manifest = Path(old_plan['manifest']['path'])
_original_mechanics(mechanics, manifest)
interpreter = old_plan['python_interpreter']['path']; assert sys.executable == interpreter
env = dict(os.environ, AM_R5_HOST_SRC=roots['am_style'], AM_R5_TRAINING_ROOT=roots['training'],
           PYTHONDONTWRITEBYTECODE='1', TMPDIR=str((TASK / 'tmp').resolve()))
results = []
def cli(label, arguments, expected):
    p = subprocess.run([interpreter, str(TASK / 'scripts/audited_cli.py'), label, *arguments],
                       cwd=WORK, env=env, capture_output=True, text=True)
    (TASK / 'private' / (label + '.stdout.log')).write_text(p.stdout)
    (TASK / 'private' / (label + '.stderr.log')).write_text(p.stderr)
    audit = read(TASK / 'private' / (label + '.audit.json'))
    audit.update(command=arguments[0], reason=p.stderr.strip(), stdout_sha256=hashlib.sha256(p.stdout.encode()).hexdigest())
    assert p.returncode == expected and audit['exit_code'] == expected, (label, p.returncode, p.stderr)
    assert audit['trainer_start_attempts'] == 0 and not audit['mlx_imported'], label
    results.append(audit)
    return json.loads(p.stdout) if p.stdout.strip() else None
out = TASK / 'private/pilot-plan-001'; run = TASK / 'private/pilot-run-001'
prepared = cli('prepare-real-missing-holdout', ['pilot-plan', '--snapshot', str(snapshot_path),
    '--mechanics', str(mechanics), '--manifest', str(manifest), '--output', str(out),
    '--python', interpreter, '--run-dir', str(run), '--host-src', roots['am_style'],
    '--training-root', roots['training']], 0)
plan_path = out / 'plan.json'; plan = read(plan_path)
report = cli('preflight-real-missing-holdout', ['pilot-preflight', '--plan', str(plan_path)], 0)
assert report['metadata_ready'] and report['execution_gate']['status'] == 'blocked'
assert report['resource_gate']['status'] == 'not_checked' and report['ready_for_launch'] is False
assert report['resource_lease_acquired'] is False
for label, path in [('new', plan_path), ('legacy', old)]:
    for command in ('pilot-command', 'pilot-execute'):
        cli(label + '-' + command, [command, '--plan', str(path)] + (['--execute'] if command == 'pilot-execute' else []), 2)
cached = dict(plan); cached.pop('holdout_gate', None)
cached.update(ready_for_launch=True, execution_gate={'status': 'passed'}, initial_preflight={'passed': True})
cached_path = TASK / 'private/cached-green-plan.json'
cached_path.write_text(json.dumps(seal(cached), ensure_ascii=False, indent=2) + '\n')
for command in ('pilot-command', 'pilot-execute'):
    cli('cached-' + command, [command, '--plan', str(cached_path)] + (['--execute'] if command == 'pilot-execute' else []), 2)
assert not run.exists() and not Path(old_plan['run_directory']).exists()
assert snapshot_before == {str(p): h(p) for p in snapshot_path.parent.rglob('*') if p.is_file()}
assert read(old) == old_plan
for split in ('train', 'dev'):
    current = snapshot_path.parent / snapshot['files'][split]['path']
    baseline = WORK / 'am-style-r5/baseline/data/r4-gold' / ('sft.' + split + '.jsonl')
    assert current.read_bytes().startswith(baseline.read_bytes())
record = {'schema': 'am-r5-fix1-native-input-check/1', 'gold_counts': snapshot['counts'],
          'gold_snapshot_file_sha256': h(snapshot_path), 'gold_snapshot_content_sha256': snapshot['sha256'],
          'gold_snapshot_files_unchanged': len(snapshot_before), 'r4_gold_prefixes_unchanged': True,
          'mechanics_result_sha256': h(mechanics), 'original_mechanics_graph_verified': True,
          'runtime_source_binding': binding, 'metadata_ready': report['metadata_ready'],
          'original_metadata_checks': sorted(report['original_probe']['r4_preflight']['checks']),
          'execution_gate': report['execution_gate'], 'resource_gate': report['resource_gate'],
          'ready_for_launch': report['ready_for_launch'], 'resource_lease_acquired': False,
          'checks': results, 'actual_training_runs': 0, 'optimizer_steps': 0,
          'new_model_calls': 0, 'new_human_feedback': 0, 'actual_independent_test_cases': 0,
          'run_directories_absent': True, 'legacy_plan_unchanged': True, 'production_changed': False}
(TASK / 'evidence/native-input-check.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: record[k] for k in ('gold_counts', 'metadata_ready', 'execution_gate', 'resource_gate', 'actual_training_runs', 'run_directories_absent')}, ensure_ascii=False))
