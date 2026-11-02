"""Small-tensor numerical diagnostics only; never load a model or train LoRA.

The failed 24-GiB model-load gate remains unchanged. This separate process is
capped at 2 GiB and keeps the original lease, business and 5-GiB runtime guards.
It cannot produce a closed mechanics result or authorize a pilot.
"""
from pathlib import Path
import fcntl
import json
import sys
import time

task = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(task / 'worktree/am-style-r3'), str(task / 'worktree/am-conversation-r1/src')]
from training.mlx_r4_contracts import validate_environment
from training.mlx_r4_resources import OriginalLease
from training.mlx_r4_runtime import atomic_json, code_hashes

manifest = json.loads((task / 'private/mlx-base.json').read_text())
environment = validate_environment(manifest)
lease = OriginalLease(manifest, 90)
report = {'scope': 'small_tensor_kernel_only', 'model_loads': 0, 'optimizer_steps': 0,
          'mechanics_closed': False, 'production_changed': False,
          'memory_limit_bytes': 2 * 2**30, 'code_sha256': code_hashes(), 'environment': environment}
try:
    with lease.paths['lease_file'].open('rb') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lease.started = time.monotonic()
        report['before'] = lease.check(before_load=False)
        import mlx.core as mx
        mx.set_memory_limit(2 * 2**30)
        mx.set_cache_limit(64 * 2**20)
        from training.mlx_r4_kernels.chunk_gated_delta import validate_numerics
        cfg = json.loads((Path(manifest['local_model_path']) / 'config.json').read_text())
        report['numerical'] = validate_numerics(cfg.get('text_config', cfg))
        report['after'] = lease.check(before_load=False)
        report['peak_memory_bytes'] = mx.get_peak_memory()
        report['status'] = 'passed'
except Exception as exc:
    report.update(status='blocked_or_failed', error_type=type(exc).__name__, reason=str(exc))
finally:
    atomic_json(task / 'evidence/kernel-only.json', report)
print(json.dumps({k: report.get(k) for k in ('status', 'reason', 'peak_memory_bytes', 'model_loads', 'optimizer_steps')}))
raise SystemExit(0 if report.get('status') == 'passed' else 2)
