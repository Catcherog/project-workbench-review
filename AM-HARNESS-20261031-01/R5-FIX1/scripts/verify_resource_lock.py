"""Exercise unchanged R4 lease ordering on a temporary lock and synthetic metrics only."""
from pathlib import Path
import fcntl, json, sys, tempfile
from unittest.mock import patch

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / 'worktree/am-style-r3'), str(TASK / 'worktree/am-conversation-r1/src')]
from training import mlx_r4_resources as resources
from training.common import file_hash

checks = []
with tempfile.TemporaryDirectory(dir=TASK / 'tmp', prefix='r4-lock-fixture-') as directory:
    lock = Path(directory) / 'model-coordinator.lock'; lock.touch()
    for available in (23.99, 24.0):
        observed = []
        def read_metrics_under_lock(lease, *, before_load=False):
            assert before_load is True
            with lock.open('rb') as competing:
                try:
                    fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    held = True
                else:
                    fcntl.flock(competing, fcntl.LOCK_UN); held = False
            observed.append({'lock_held_before_resource_check': held, 'before_load': before_load})
            assert held
            resources.check_metrics({'available_memory_GiB': available, 'memory_pressure': 1,
                                     'pending_business': 0, 'swap_used_GiB': 0, 'loaded_models': []}, before_load=True)
        reached_body = False; blocked = False
        with patch.object(resources, 'validate_service_paths', return_value={'lease_file': lock}), \
             patch.object(resources.OriginalLease, 'check', new=read_metrics_under_lock):
            try:
                with resources.OriginalLease({'fixture': True}, 300): reached_body = True
            except resources.ResourcePause: blocked = True
        with lock.open('rb') as competing:
            fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(competing, fcntl.LOCK_UN)
        assert len(observed) == 1 and blocked == (available < 24) and reached_body == (available >= 24)
        checks.append({'available_memory_GiB_fixture': available, **observed[0],
                       'blocked': blocked, 'with_body_entered': reached_body, 'lock_released': True})
report = {'tests_run': len(checks), 'passed': len(checks), 'exit_code': 0, 'checks': checks,
          'resource_source_sha256': file_hash(Path(resources.__file__)),
          'real_flock_on_temporary_file': True, 'metrics_and_manifest_are_synthetic': True,
          'original_production_lock_acquired': False, 'actual_resource_clearance_issued': False,
          'model_calls': 0, 'training_runs': 0, 'production_changed': False}
(TASK / 'evidence/resource-lock-contract.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
