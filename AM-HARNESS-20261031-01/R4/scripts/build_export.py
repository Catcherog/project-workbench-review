"""Build a fresh, sanitized R4 review directory; never export private state."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[1]
BASE = '73c1f9e11ec8b1ea9c3e36060a2522fab3676480'
EXPECTED = '9255a70154ca82c0b9e2c0dbdb14a90cf94cbbde'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
OUT = args.output.resolve()
OUT.mkdir(parents=True, exist_ok=False)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True)


assert git('rev-parse', 'HEAD').strip() == EXPECTED
assert not git('status', '--short', '--untracked-files=no').strip()
settings = json.loads((Path.home() / '.local/share/local-qwen-feishu/config.json').read_text())
poc = json.loads(Path(settings['poc_config']).read_text())
identifiers, secrets = set(), set()


def inspect(value, key=''):
    if isinstance(value, dict):
        for k, v in value.items():
            inspect(v, k)
    elif isinstance(value, list):
        for v in value:
            inspect(v, key)
    elif isinstance(value, str):
        if value.startswith(('ou_', 'oc_', 'od_', 'cli_', 'o-')) and len(value) > 20:
            identifiers.add(value)
        if re.search(r'(?i)secret|password|access_token|refresh_token|api_key', key) and len(value) > 12:
            secrets.add(value)


inspect(settings)
inspect(poc)
redactions = {v: v.split('_')[0] + '_SYNTHETIC_' + hashlib.sha256(('audit:' + v).encode()).hexdigest()[:12]
              for v in identifiers}
redactions.update({v: 'SYNTHETIC_REDACTED_SECRET' for v in secrets})
redactions.update({str(ROOT): '/workspace/am', str(Path.home()): '/home/am',
                   'example.feishu.cn': 'example.feishu.cn',
                   'SYNTHETIC_TH2_LEDGER_TOKEN': 'SYNTHETIC_TH2_LEDGER_TOKEN',
                   '所有者': '所有者', 'AR900合成甲': 'AR900合成甲'})


def redact(text):
    text = re.sub(r'/(?:private/)?var/folders/[^/]+/[^/]+/T/', '/tmp/audit/', text)
    text = re.sub(r'pytest-of-[A-Za-z0-9_.-]+', 'pytest-of-audit', text)
    for old, new in sorted(redactions.items(), key=lambda item: -len(item[0])):
        text = text.replace(old, new)
    return text


def save(relative, text, mode=0o644):
    path = OUT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact(text))
    path.chmod(mode)


changed = git('diff', '--name-only', BASE, EXPECTED).splitlines()
source = {}
for relative in changed:
    assert relative.startswith(('am-conversation-r1/', 'am-style-r3/'))
    path = ROOT / relative
    assert path.is_file() and not path.is_symlink()
    save('source/' + relative, path.read_text(), path.stat().st_mode & 0o777)
    source[relative] = {'source_sha256': sha(path), 'audit_sha256': sha(OUT / 'source' / relative)}
save('SOURCE_SHA256.json', json.dumps({
    'source_commit': EXPECTED, 'base_source': BASE,
    'base_review_commit': '3eb75504515f483b0fc284db5930ee13db12588c',
    'base_review_directory': 'AM-FOLLOWUP-20261102-01/R1',
    'kind': 'incremental_overlay', 'files': source,
}, indent=2) + '\n')
save('FINAL.diff', git('diff', BASE, EXPECTED))
for name in ('00_当前交接.md', '01_实现与复现.md', '02_模型数据与训练.md', '03_验收与未完成.md'):
    save(name, (TASK / name).read_text())
for path in (TASK / 'scripts').glob('*.py'):
    if path.name not in {'import_human_feedback.py'}:
        save('scripts/' + path.name, path.read_text())

evidence = {}
for path in (TASK / 'evidence').rglob('*'):
    if not path.is_file() or path.suffix not in ('.json', '.xml', '.log', '.txt'):
        continue
    if path.name in {'published-commit.json', 'remote-readback.json', 'paused-state.json'}:
        continue
    relative = 'evidence/' + path.relative_to(TASK / 'evidence').as_posix()
    save(relative, path.read_text())
    evidence[relative] = {'original_sha256': sha(path), 'audit_sha256': sha(OUT / relative)}
save('EVIDENCE_SHA256.json', json.dumps({
    'scope': 'Sanitized observational evidence. Original and audit bytes are distinct; audit copies are not live execution credentials.',
    'files': evidence,
}, indent=2) + '\n')
save('input/frozen-comparison.json', (TASK / 'input/frozen-comparison.json').read_text())
save('input/received-MANIFEST.json', (TASK / 'input/AM-HARNESS-20261031-01_R4/MANIFEST.json').read_text())
for path in (TASK / 'private/qwen-comparison').glob('*.json'):
    save('model-observations/' + path.name, path.read_text())
for path in (TASK / 'private/human-feedback-001').glob('*'):
    if path.name == 'actual-human-replies.json' or path.suffix not in ('.json', '.jsonl'):
        continue
    save('data/human-feedback-001/' + path.name, path.read_text())
save('data/README.md', '本轮8条新增gold来自真实人工对完整答复的认可，均为虚构情境；合并原gold为train9/dev1。原始人工回复留本机，只公开处理后的绑定记录和原始文件哈希。未选择的候选不自动标坏；DPO与silver仍为0。\n')
save('EXPORT_BOUNDARY.json', json.dumps({
    'source_commit': EXPECTED, 'source_overlay_files': len(source),
    'credentials_included': False, 'real_business_data_included': False,
    'private_blind_pairs_or_key_included': False, 'raw_human_replies_included': False,
    'model_weights_or_adapters_included': False,
    'public_data': 'fictional model scenarios, processed human labels, deidentified runtime metadata',
}, indent=2) + '\n')
for path in OUT.rglob('*'):
    if path.is_file():
        text = path.read_text()
        assert not any(v in text for v in identifiers | secrets), str(path)
        assert str(Path.home()) not in text, str(path)
        assert path.suffix not in ('.sqlite3', '.safetensors', '.gguf'), str(path)
files = {path.relative_to(OUT).as_posix(): {
    'sha256': sha(path), 'bytes': path.stat().st_size, 'mode': oct(path.stat().st_mode & 0o777),
} for path in OUT.rglob('*') if path.is_file()}
save('MANIFEST.json', json.dumps({'source_commit': EXPECTED, 'files': files}, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'source_overlay_files': len(source), 'export_files': len(files) + 1,
                  'bytes': sum(v['bytes'] for v in files.values()), 'privacy_scan_passed': True}))
