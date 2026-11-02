"""Read-only resource/runtime snapshot; no lease, load, inference or service change."""
from pathlib import Path
import argparse, hashlib, json, os, shlex, sqlite3, subprocess, sys, time
from datetime import datetime, timezone
from unittest.mock import patch
import psutil

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[1]
sys.path[:0] = [str(TASK / 'worktree/am-style-r3'), str(TASK / 'worktree/am-conversation-r1/src')]
from training import mlx_r4_resources as resources

p = argparse.ArgumentParser(); p.add_argument('label'); a = p.parse_args()
def read(path): return json.loads(path.read_text())
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
manifest = read(ROOT / 'AM-HARNESS-20261031-01/R4/private/mlx-base.json')
config_path = Path.home() / '.local/share/local-qwen-feishu/config.json'
cfg = read(config_path); poc_path = Path(cfg['poc_config']); poc = read(poc_path)
state = Path(cfg['state_directory']); loaded_path = state / 'loaded-manifest.json'
loaded = read(loaded_path); connection = read(state / 'connection-status.json')
prefix = {'feishu-bridge': 'local-qwen3.8/feishu-bridge',
          **{n: 'am-conversation-r1/src/' + n for n in ('am_conversation', 'am_reply', 'am_outcome', 'am_response', 'am_style')},
          **{n: 'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/' + n for n in ('fs_agent', 'am_doc_engine', 'am_harness', 'am_followup')}}
source_mismatches = []
for name, expected in loaded['files'].items():
    group, relative = name.split('/', 1)
    path = ROOT / prefix[group] / relative
    if not path.is_file() or digest(path) != expected: source_mismatches.append(name)
consumers, trainer_processes, process_rows = [], [], []
for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cmdline', 'create_time']):
    try:
        info = proc.info; argv = info['cmdline'] or []
        is_python = bool(argv) and Path(argv[0]).name.lower().startswith('python')
        if is_python and any(x.endswith('/feishu-bridge/bridge.py') for x in argv) and '--config' in argv:
            consumers.append(info['pid'])
        if is_python and any(x in ('training.mlx_r4', 'mlx_lm.lora', 'train_sft.py', 'train_dpo.py') for x in argv):
            trainer_processes.append({'pid': info['pid'], 'name': info['name']})
        if info['memory_info']:
            process_rows.append({'pid': info['pid'], 'name': info['name'], 'rss_GiB': info['memory_info'].rss / 2**30})
    except (psutil.AccessDenied, psutil.NoSuchProcess): pass
captured = {}; original_check = resources.check_metrics
def capture(metrics, **kwargs):
    captured.update(metrics)
    return original_check(metrics, **kwargs)
lease = resources.OriginalLease(manifest, 300); lease.started = time.monotonic()
try:
    with patch.object(resources, 'check_metrics', side_effect=capture): lease.check(before_load=True)
    resource_status, resource_reason = 'passed_observation_only', None
except Exception as exc:
    resource_status, resource_reason = 'blocked', type(exc).__name__ + ': ' + str(exc)
assert lease.stream is None
vm = psutil.virtual_memory(); swap = psutil.swap_memory()
db_path = Path(manifest['service']['gateway_db'])
with sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
    lane = db.execute('SELECT state FROM am_harness_lane').fetchone()[0]
    pause = db.execute("SELECT value FROM meta WHERE key='provider_pause'").fetchone()
report = {'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'label': a.label,
          'host_source_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
          'loaded_files': len(loaded['files']), 'source_mismatches': source_mismatches,
          'consumer_count': len(consumers), 'consumer_pid_matches_loaded_manifest': consumers == [loaded['pid']],
          'connection': connection['state'], 'config_sha256': digest(config_path), 'poc_config_sha256': digest(poc_path),
          'loaded_manifest_sha256': digest(loaded_path), 'model': loaded['model'], 'model_digest': loaded['model_digest'],
          'identity_cache_seconds': cfg['am_query']['identity_cache_seconds'], 'ledger_write': cfg['am_self']['ledger_write'],
          'response_mode': cfg['am_conversation'].get('response', {}).get('mode', 'legacy'),
          'rewrite_mode': cfg['am_conversation']['output_rewrite']['mode'],
          'terminal_expression_mode': cfg['am_conversation'].get('terminal_expression', {}).get('mode', 'off'),
          'lane_state': lane, 'provider_pause_present': pause is not None, 'trainer_processes': trainer_processes,
          'resource_status': resource_status, 'resource_reason': resource_reason,
          'original_resource_metrics': captured, 'physical_memory_GiB': vm.total / 2**30,
          'available_memory_GiB': vm.available / 2**30, 'swap_used_GiB': swap.used / 2**30,
          'largest_processes_by_rss': sorted(process_rows, key=lambda x: -x['rss_GiB'])[:12],
          'rss_limit': 'RSS is not unique physical memory; shared and compressed pages must not be summed to infer reclaimable memory.',
          'resource_policy': {'before_load_available_GiB': 24, 'running_available_GiB': 5, 'max_swap_growth_GiB': 1},
          'lease_acquired': False, 'resource_clearance_issued': False, 'new_model_calls': 0, 'production_changed': False}
assert len(consumers) == 1 and report['consumer_pid_matches_loaded_manifest']
assert not source_mismatches and not trainer_processes
assert report['identity_cache_seconds'] == 600 and report['ledger_write'] is False
assert report['response_mode'] == 'legacy' and report['rewrite_mode'] == 'off' and report['terminal_expression_mode'] == 'off'
assert loaded['model'] == resources.PRODUCTION_MODEL and loaded['model_digest'] == resources.PRODUCTION_DIGEST
(TASK / 'evidence' / ('runtime-' + a.label + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: report[k] for k in ('label', 'resource_status', 'available_memory_GiB', 'swap_used_GiB', 'consumer_count', 'connection', 'lane_state', 'trainer_processes', 'response_mode', 'terminal_expression_mode')}, ensure_ascii=False))
