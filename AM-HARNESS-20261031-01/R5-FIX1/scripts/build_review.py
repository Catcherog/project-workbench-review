"""Export this task only, keeping source/remote byte identities and privacy boundaries explicit."""
from pathlib import Path
import hashlib, json, os, re, subprocess

TASK = Path(__file__).resolve().parents[1]; ROOT = TASK.parents[1]; WORK = TASK / 'worktree'
OUT = TASK / 'review-export'; UP = TASK / 'upload'; PREFIX = 'AM-HARNESS-20261031-01/R5-FIX1/'
OUT.mkdir(exist_ok=False); UP.mkdir(exist_ok=True)
def sha(raw): return hashlib.sha256(raw).hexdigest()
def git(*args): return subprocess.check_output(['git', *args], cwd=WORK)
def read(p): return json.loads(p.read_text())
def dump(p, d): p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n')
source_record = read(TASK / 'evidence/source-commit.json'); source = source_record['source_commit']
assert git('rev-parse', 'HEAD').decode().strip() == source
assert not git('status', '--porcelain', '--untracked-files=no').strip()
cfg = read(Path.home() / '.local/share/local-qwen-feishu/config.json'); poc = read(Path(cfg['poc_config']))
ids, secrets = set(), set()
def inspect(value, key=''):
    if isinstance(value, dict):
        for k, v in value.items(): inspect(v, k)
    elif isinstance(value, list):
        for v in value: inspect(v, key)
    elif isinstance(value, str):
        if value.startswith(('ou_', 'oc_', 'od_', 'cli_', 'o-')) and len(value) > 20: ids.add(value)
        if re.search(r'(?i)secret|password|access_token|refresh_token|api_key', key) and len(value) > 12: secrets.add(value)
inspect(cfg); inspect(poc)
replacements = {v: 'REDACTED_SECRET' for v in secrets}
replacements.update({v: v.split('_')[0] + '_REDACTED_' + sha(v.encode())[:12] for v in ids})
replacements.update({str(ROOT): '/workspace/am', str(Path.home()): '/home/am',
                     'example.feishu.cn': 'example.feishu.cn',
                     'REDACTED_LEDGER_TOKEN': 'REDACTED_LEDGER_TOKEN'})
def redact(text):
    for old, new in sorted(replacements.items(), key=lambda pair: -len(pair[0])):
        text = text.replace(old, new).replace(json.dumps(old)[1:-1], json.dumps(new)[1:-1])
    return re.sub(r'\b(?:ou|oc|od|cli)_[A-Za-z0-9]{20,}\b', lambda m: m[0].split('_')[0] + '_REDACTED_' + sha(m[0].encode())[:12], text)
boundary = {}
def save(name, raw, origin, mode=0o644):
    assert not Path(name).is_absolute() and '..' not in Path(name).parts
    raw = raw.encode() if isinstance(raw, str) else raw
    public = redact(raw.decode()).encode(); path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(public); path.chmod(mode)
    boundary[name] = {'origin': origin, 'original_sha256': sha(raw), 'public_sha256': sha(public), 'redacted': raw != public}
    return boundary[name]

tests = {name: read(TASK / 'evidence' / (name + '-contracts.json')) for name in ('bundled', 'host', 'r4')}
lock = read(TASK / 'evidence/resource-lock-contract.json'); native = read(TASK / 'evidence/native-input-check.json')
runtime = read(TASK / 'evidence/runtime-final.json'); initial = read(TASK / 'evidence/runtime-start.json')
for key in ('config_sha256', 'poc_config_sha256', 'loaded_manifest_sha256', 'model_digest'):
    assert runtime[key] == initial[key], key
old_plan = read(ROOT / 'AM-HARNESS-20261031-01/R5/private/feedback-003/pilot-plan-001/plan.json')
new_plan = read(TASK / 'private/pilot-plan-001/plan.json')
assert Path(new_plan['config']['path']).read_bytes() == Path(old_plan['config']['path']).read_bytes()
checks = {'source_commit': source, 'r5_bundled': tests['bundled'], 'r5_current_host': tests['host'],
          'r4_training_contracts': tests['r4'], 'r4_lock_order_contracts': lock,
          'same_134_r5_tests_repeated_in_two_dependency_modes': True,
          'native_cli_checks': [{'label': c['label'], 'exit_code': c['exit_code'], 'trainer_start_attempts': c['trainer_start_attempts'],
                                 'metadata_probe_subprocesses': c['metadata_probe_subprocesses']} for c in native['checks']],
          'pilot_config_identical_to_original_r5': True, 'pilot_config_sha256': new_plan['config']['sha256'],
          'runtime_config_and_loaded_manifest_unchanged_start_to_final': True,
          'host_regression_scope': 'All 411 existing tracked host files preserved; unchanged full host suites were not rerun.',
          'actual_training_runs': 0, 'production_changed': False}
dump(TASK / 'CHECKS_SUMMARY.json', checks)
status = {'source_commit': source, 'code_integration': 'completed', 'gold': native['gold_counts'],
          'training': {'status': 'blocked', 'actual_pilot_runs': 0, 'optimizer_steps': 0, 'adapter_created': False,
                       'metadata_ready': True, 'independent_test_gate': 'blocked', 'actual_resource_clearance': 'not_checked',
                       'blockers': ['No qualified independent frozen case bundle plus case-bound human declaration and original.',
                                    'Latest read-only available memory is below the unchanged 24 GiB policy.']},
          'independent_test': {'qualified_frozen_cases': 0, 'candidate_source_objects': 659,
                               'candidate_scenario_independence': 'not_verified', 'case_bound_human_declaration': 'missing'},
          'effect_evaluation': {'three_arm_generation': 'not_run', 'model_calls': 0, 'human_ratings': 0, 'quality': 'not_established'},
          'host_new_expression_integration': {'status': 'not_completed', 'identity_and_verification_task_projection': 'pending'},
          'business_acceptance': {'status': 'not_completed', 'mobile': 'not_completed', 'independent_person': 'not_completed'},
          'production': {'q8_unchanged': True, 'consumer_count': runtime['consumer_count'], 'identity_cache_seconds': 600,
                         'ledger_write': False, 'response_mode': 'legacy', 'rewrite_mode': 'off', 'terminal_expression_mode': 'off'},
          'latest_resource_observation': {'time_utc': runtime['observed_at_utc'], 'available_memory_GiB': runtime['available_memory_GiB'],
                                          'policy_before_load_GiB': 24, 'lease_acquired': False, 'automatic_retry_scheduled': False}}
dump(TASK / 'EXPERIMENT_STATUS.json', status)

tracked = {}
for item in git('ls-tree', '-rz', source).split(b'\0'):
    if not item: continue
    header, path = item.split(b'\t', 1); mode, kind, blob = header.decode().split()
    assert kind == 'blob'; tracked[path.decode()] = {'mode': mode, 'blob_sha': blob}
selected = [name for name in tracked if name.startswith(('am-style-r5/', 'am-style-r3/training/', 'am-conversation-r1/src/am_style/'))]
source_files = {}
for name in selected:
    e = tracked[name]; raw = git('cat-file', 'blob', e['blob_sha'])
    assert raw == (WORK / name).read_bytes()
    b = save('source/' + name, raw, 'actual_source_commit', int(e['mode'], 8))
    source_files[name] = {'source_sha256': b['original_sha256'], 'audit_sha256': b['public_sha256'], 'mode': e['mode'], 'git_blob_sha': e['blob_sha']}
inherited = [p.decode() for p in git('diff', '--name-only', '-z', source_record['parents'][1], source, '--', '.', ':!am-style-r5').split(b'\0') if p]
for name in inherited:
    e = tracked[name]; save('preserved-host/' + name, git('cat-file', 'blob', e['blob_sha']), 'preexisting_current_host', int(e['mode'], 8))
save('SOURCE_SHA256.json', json.dumps({'source_commit': source, 'parents': source_record['parents'], 'files': source_files,
     'scope': 'Actual R5 module, actual R4 trainer and actual am_style expression dependencies; newer host context separate.',
     'preserved_host_files': {n: {'sha256': sha((WORK / n).read_bytes()), **tracked[n]} for n in inherited},
     'host_file_hashes': {n: sha((WORK / n).read_bytes()) for n in tracked if not n.startswith('am-style-r5/')}}, ensure_ascii=False, indent=2) + '\n', 'computed_source_manifest')
for name in ('00_当前交接.md', 'CHECKS_SUMMARY.json', 'EXPERIMENT_STATUS.json', 'FINAL.diff', 'PRESERVED_HOST.diff'):
    save(name, (TASK / name).read_bytes(), 'original_machine_report')
for p in sorted((TASK / 'evidence').iterdir()):
    if p.is_file() and p.suffix in ('.json', '.log'):
        save('evidence/' + p.name, p.read_bytes(), 'original_machine_evidence')
received = TASK / 'input/AM-HARNESS-20261031-01_R5-FIX1_Pilot_Gate'
for p in sorted(received.rglob('*')):
    if p.is_file(): save('received-design/' + str(p.relative_to(received)), p.read_bytes(), 'received_review_package')
for p in sorted((TASK / 'scripts').glob('*.py')): save('scripts/' + p.name, p.read_bytes(), 'execution_reproduction_script')
bindings = read(received / 'INPUT_AND_PATCH_BINDINGS.json')
for e in bindings['changes']:
    assert sha((OUT / 'source' / e['path']).read_bytes()) == e['after_sha256'], e['path']
# Match public data to exactly the already-published R5 gold; no new raw business data is exported.
for p in sorted((ROOT / 'AM-HARNESS-20261031-01/R5/review-export-feedback/data/current-gold').rglob('*')):
    if p.is_file(): save('reused-public-gold/' + str(p.relative_to(ROOT / 'AM-HARNESS-20261031-01/R5/review-export-feedback/data/current-gold')), p.read_bytes(), 'already_public_r5_gold')
save('EVIDENCE_BOUNDARY.json', json.dumps(boundary, ensure_ascii=False, indent=2) + '\n', 'computed_redaction_boundary')
for p in OUT.rglob('*'):
    if not p.is_file(): continue
    raw = p.read_bytes(); text = raw.decode()
    assert not any(s in text for s in ids | secrets), p
    assert str(Path.home()) not in text, p
    assert not re.search(r'\b(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_]{20,}', text), p
    if p.suffix == '.json': json.loads(text)
manifest = {'task': PREFIX.rstrip('/'), 'source_commit': source, 'files': {str(p.relative_to(OUT)): {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())} for p in sorted(OUT.rglob('*')) if p.is_file()}}
dump(OUT / 'MANIFEST.json', manifest)
entries = []
for p in sorted(OUT.rglob('*')):
    if not p.is_file(): continue
    raw = p.read_bytes(); mode = '100755' if p.stat().st_mode & 0o111 else '100644'
    entries.append({'path': str(p.relative_to(OUT)), 'sha256': sha(raw), 'bytes': len(raw), 'mode': mode,
                    'blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()})
index = {'prefix': PREFIX, 'source_commit': source, 'entries': entries}
dump(UP / 'index.json', index)
print(json.dumps({'source_commit': source, 'export_files': len(entries), 'bytes': sum(e['bytes'] for e in entries),
                  'source_files': len(source_files), 'preserved_host_context_files': len(inherited),
                  'four_patch_public_hashes_match': True, 'redacted_files': sum(e['redacted'] for e in boundary.values())}))
