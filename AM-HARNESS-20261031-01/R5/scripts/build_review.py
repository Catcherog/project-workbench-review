"""Export only this R5 source, synthetic inputs, and deidentified audit evidence."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[1]
SOURCE = TASK / 'worktree'
PARENT = '4009a3ab2dc79b969ce7bf96502866dad8478072'
R4 = '9255a70154ca82c0b9e2c0dbdb14a90cf94cbbde'
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
OUT = args.output.resolve()
OUT.mkdir(parents=True, exist_ok=False)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def git(*args):
    return subprocess.check_output(['git', *args], cwd=SOURCE)

source_sha = git('rev-parse', 'HEAD').decode().strip()
assert not git('status', '--short', '--untracked-files=no').strip()
cfg = json.loads((Path.home() / '.local/share/local-qwen-feishu/config.json').read_text())
poc = json.loads(Path(cfg['poc_config']).read_text())
identifiers, secrets = set(), set()
def inspect(value, key=''):
    if isinstance(value, dict):
        for k, v in value.items(): inspect(v, k)
    elif isinstance(value, list):
        for v in value: inspect(v, key)
    elif isinstance(value, str):
        if value.startswith(('ou_', 'oc_', 'od_', 'cli_', 'o-')) and len(value) > 20:
            identifiers.add(value)
        if re.search(r'(?i)secret|password|access_token|refresh_token|api_key', key) and len(value) > 12:
            secrets.add(value)
inspect(cfg)
inspect(poc)
replacements = {v: 'SYNTHETIC_REDACTED_SECRET' for v in secrets}
replacements.update({v: v.split('_')[0] + '_SYNTHETIC_' + sha(v.encode())[:12] for v in identifiers})
replacements.update({str(ROOT): '/workspace/am', str(Path.home()): '/home/am',
                     'example.feishu.cn': 'example.feishu.cn',
                     'SYNTHETIC_TH2_LEDGER_TOKEN': 'SYNTHETIC_TH2_LEDGER_TOKEN',
                     'AR900合成甲': 'AR900合成甲', '所有者': '所有者'})
def redact(text):
    text = re.sub(r'/(?:private/)?var/folders/[^/]+/[^/]+/T/', '/tmp/audit/', text)
    text = re.sub(r'pytest-of-[A-Za-z0-9_.-]+', 'pytest-of-audit', text)
    for old, new in sorted(replacements.items(), key=lambda item: -len(item[0])):
        text = text.replace(old, new).replace(json.dumps(old)[1:-1], json.dumps(new)[1:-1])
    text = re.sub(r'\b(?:ou|oc|od|cli)_[A-Za-z0-9]{20,}\b',
                  lambda m: m[0].split('_')[0] + '_SYNTHETIC_' + sha(m[0].encode())[:12], text)
    return text

boundary = {}
def save(name, raw, *, origin, mode=0o644):
    assert not Path(name).is_absolute() and '..' not in Path(name).parts
    text = raw.decode('utf-8') if isinstance(raw, bytes) else raw
    original = text.encode('utf-8')
    public = redact(text).encode('utf-8')
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(public)
    path.chmod(mode)
    boundary[name] = {'origin': origin, 'original_sha256': sha(original), 'public_sha256': sha(public),
                      'redacted': original != public}
    return boundary[name]

changed = [x.decode() for x in git('diff', '--name-only', '-z', PARENT, source_sha).split(b'\0') if x]
assert len(changed) == 93 and all(p.startswith('am-style-r5/') for p in changed)
source_records = {}
for name in changed:
    path = SOURCE / name
    assert path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts
    entry = save('source/' + name, git('show', source_sha + ':' + name), origin='R5_source_commit', mode=path.stat().st_mode & 0o777)
    source_records[name] = {'source_sha256': entry['original_sha256'], 'audit_sha256': entry['public_sha256']}
inherited = [x.decode() for x in git('diff', '--name-only', '-z', R4, PARENT).split(b'\0') if x]
inherited_records = {}
for name in inherited:
    path = SOURCE / name
    entry = save('inherited-host/' + name, git('show', PARENT + ':' + name), origin='preserved_preexisting_host', mode=path.stat().st_mode & 0o777)
    inherited_records[name] = {'source_sha256': entry['original_sha256'], 'audit_sha256': entry['public_sha256']}
save('FINAL.diff', git('diff', PARENT, source_sha), origin='R5_source_commit')
save('INHERITED_HOST.diff', git('diff', R4, PARENT), origin='preserved_preexisting_host')
save('SOURCE_SHA256.json', json.dumps({'source_commit': source_sha, 'source_parent': PARENT,
     'r4_source': R4, 'r4_review': '0641a282584a68f60ddaf198326fc431ba67ee13',
     'kind': 'isolated_R5_module_plus_explicit_inherited_context', 'files': source_records,
     'inherited_host_files': inherited_records}, ensure_ascii=False, indent=2) + '\n', origin='computed_manifest')
for name in ('00_当前交接.md', '01_原机接入与验证.md', '02_数据训练与评测状态.md',
             'CHECKS_SUMMARY.json', 'DATA_SUMMARY.json', 'EXPERIMENT_STATUS.json'):
    save(name, (TASK / name).read_bytes(), origin='R5_execution_report')
save('input/input-snapshot.json', (TASK / 'input/input-snapshot.json').read_bytes(), origin='received_input_snapshot')
for path in sorted((TASK / 'evidence').rglob('*')):
    if not path.is_file() or path.suffix not in ('.json', '.xml', '.log', '.txt'):
        continue
    if path.name in {'remote-readback.json', 'published-commit.json', 'export-validation.json'}:
        continue
    save('evidence/' + path.relative_to(TASK / 'evidence').as_posix(), path.read_bytes(), origin='R5_actual_observation')
for name in ('original-input-audit.json', 'runtime-loaded-before.json', 'runtime-loaded-final.json'):
    save('evidence/' + name, (TASK / 'private' / name).read_bytes(), origin='private_runtime_metadata_redacted')
for name in ('runtime-drift-resolution.json',):
    if (TASK / 'private' / name).exists():
        save('evidence/' + name, (TASK / 'private' / name).read_bytes(), origin='private_runtime_metadata_redacted')
for path in sorted((TASK / 'private/run-001/prepared').rglob('*')):
    if path.is_file():
        save('data/prepared/' + path.relative_to(TASK / 'private/run-001/prepared').as_posix(), path.read_bytes(), origin='synthetic_pending_or_unchanged_R4_gold')
save('data/calibration.frozen.json', (TASK / 'private/run-001/calibration.frozen.json').read_bytes(), origin='public_calibration_not_holdout')
for path in sorted((TASK / 'scripts').glob('*.py')):
    save('scripts/' + path.name, path.read_bytes(), origin='R5_execution_support_script')
# Original mechanics weights, raw user replies, source conversation and live DBs are never traversed.
report = {'source_commit': source_sha, 'raw_chat_included': False, 'raw_human_replies_included': False,
          'real_business_data_included': False, 'credentials_included': False,
          'real_blind_mapping_included': False, 'weights_or_adapters_included': False,
          'bundled_demo_mapping': 'source/am-style-r5/examples/demo contains original explicitly synthetic fixture only',
          'redaction': ['local paths', 'configuration IDs/secrets', 'owner display labels', 'long platform IDs'],
          'scope': 'Public copies are audit evidence, not executable original training credentials',
          'files': boundary.copy()}
save('EXPORT_BOUNDARY.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n', origin='computed_manifest')
for path in OUT.rglob('*'):
    if path.is_file():
        text = path.read_text()
        assert path.suffix not in ('.sqlite3', '.db', '.safetensors', '.gguf', '.pyc', '.zip')
        assert not any(value in text or json.dumps(value)[1:-1] in text for value in identifiers | secrets)
        assert str(Path.home()) not in text
        assert re.search(r'\b(?:ou|oc|od|cli)_[A-Za-z0-9]{20,}\b', text) is None
files = {path.relative_to(OUT).as_posix(): {'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size,
         'mode': oct(path.stat().st_mode & 0o777)} for path in sorted(OUT.rglob('*')) if path.is_file()}
save('MANIFEST.json', json.dumps({'source_commit': source_sha, 'files': files}, ensure_ascii=False, indent=2) + '\n', origin='computed_manifest')
print(json.dumps({'source_commit': source_sha, 'source_files': len(source_records), 'inherited_host_files': len(inherited_records),
                  'total_files': len(files) + 1, 'bytes': sum(v['bytes'] for v in files.values()),
                  'r5_source_redacted_files': [p for p, v in source_records.items() if v['source_sha256'] != v['audit_sha256']],
                  'privacy_scan_passed': True}, ensure_ascii=False))
