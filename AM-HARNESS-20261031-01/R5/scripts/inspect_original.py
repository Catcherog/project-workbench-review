"""Read original R4 artifacts and current source; no model load or training."""
from pathlib import Path
import importlib.metadata
import json
import os
import subprocess
import sys
import time

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[1]
SOURCE = TASK / 'worktree'
PACKAGE = SOURCE / 'am-style-r5'
sys.path[:0] = [str(PACKAGE / 'src'), str(SOURCE / 'am-conversation-r1/src'), str(SOURCE / 'am-style-r3')]
from am_style_r5.common import file_hash, write_json, read_json
from am_style_r5.pilot import _original_mechanics, _source_binding, _snapshot
from am_style_r5.dataset import verify_gold_snapshot
from am_style_r5.arms import build_queue_config
from training.mlx_r4_contracts import validate_base, validate_environment, validate_mechanics_gate
from training.mlx_r4_resources import validate_service_paths, OriginalLease, check_metrics

manifest_path = ROOT / 'AM-HARNESS-20261031-01/R4/private/mlx-base.json'
result_path = ROOT / 'AM-HARNESS-20261031-01/R4/private/mlx-mechanics-002/result.json'
manifest = read_json(manifest_path)
checks = {}
def check(name, call):
    try:
        value = call()
        checks[name] = {'status': 'passed', 'value': value}
        return value
    except Exception as exc:
        checks[name] = {'status': 'blocked', 'reason': type(exc).__name__ + ': ' + str(exc)}
        return None

binding = check('runtime_source', lambda: _source_binding({'training': str(SOURCE / 'am-style-r3'), 'am_style': str(SOURCE / 'am-conversation-r1/src')}))
check('original_mechanics_graph', lambda: bool(_original_mechanics(result_path, manifest_path)))
check('original_r4_mechanics_gate', lambda: validate_mechanics_gate({'mechanics_result': {'path': str(result_path), 'sha256': file_hash(result_path)}}))
check('independent_base_metadata', lambda: validate_base(manifest))
check('existing_environment', lambda: validate_environment(manifest))
check('protected_service_paths', lambda: bool(validate_service_paths(manifest)))
snapshot_path = TASK / 'private/run-001/prepared/current-gold/snapshot.json'
snapshot = check('gold_readback', lambda: verify_gold_snapshot(snapshot_path))
check('pilot_data_gate', lambda: bool(_snapshot(snapshot_path)))
host_config = Path.home() / '.local/share/local-qwen-feishu/config.json'
cfg = read_json(host_config)
poc = read_json(cfg['poc_config'])
loaded_path = Path(cfg['state_directory']) / 'loaded-manifest.json'
loaded = read_json(loaded_path)
queue = Path(poc['service']['root_directory']) / 'state/am-conversation-r2'
queue_config = check('original_queue_binding', lambda: build_queue_config(manifest_path, host_config, queue, loaded['pid']))
if queue_config is not None:
    write_json(TASK / 'private/run-001/queue.real.json', queue_config)
# Use the original read-only metrics method without acquiring its lease.
lease = OriginalLease(manifest, 300)
lease.started = time.monotonic()
metrics = check('current_resource_window', lambda: lease.check(before_load=True))
report = {'schema': 'am-r5-original-input-audit/1', 'checked_at': time.time(),
          'source_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip(),
          'python': sys.executable, 'checks': checks, 'mechanics_result_sha256': file_hash(result_path),
          'manifest_file_sha256': file_hash(manifest_path),
          'selected_consumer_pid': loaded['pid'], 'loaded_manifest_sha256': file_hash(loaded_path),
          'loaded_file_count': len(loaded['files']), 'model_loaded': False,
          'mlx_imported': any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules),
          'lease_acquired': False, 'training_executed': False, 'new_human_labels': 0,
          'independent_holdout': {'status': 'blocked', 'reason': 'No original human holdout cases and unused-for-tuning declaration supplied'},
          'production_changed': False}
write_json(TASK / 'private/original-input-audit.json', report)
write_json(TASK / 'private/runtime-loaded-before.json', loaded)
print(json.dumps({k: v for k, v in report.items() if k != 'checks'}, ensure_ascii=False))
print(json.dumps({k: {'status': v['status'], 'reason': v.get('reason')} for k, v in checks.items()}, ensure_ascii=False))
