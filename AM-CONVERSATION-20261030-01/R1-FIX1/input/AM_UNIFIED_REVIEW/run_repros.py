"""Run five offline scripts and report six observed defects, not fix results."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PACKAGE = Path(__file__).resolve().parent
AUDIT_COMMIT = '581632802f415b923e17ccf4817a153ac630de5c'
SOURCE_COMMIT = '53330c3869aa1ff4e39c7c41ec82243c6126491f'
BASE_AUDIT_COMMIT = '7445333757fd39b674caa7cca8237ee9ecc46f89'
SCRIPTS = [
    ('am_information_audit_repro.py', (
        ('F01', 'P1', '访问拒绝被普通读取错误清除', 'permission_regression'),
        ('F03', 'P1', '无法读取的队首持续阻塞后续发现', 'queue_head_blocking'),
    )),
    ('reproduce_conversation_history_revocation.py', (
        ('F02', 'P1', '已撤权来源经旧对话历史再次进入模型输入', None),
    )),
    ('repro_doc_receipt_mix.py', (
        ('F04', 'P1', '当前云写入未知却用旧回执确认新动作', None),
    )),
    ('am_information_subject_repro.py', (
        ('F05', 'P2', '追加项目关联后原事实未重新提取', None),
    )),
    ('repro_doc_wrong_draft.py', (
        ('F06', 'P2', '指定 A 稿预检要求实际写入最新 B 稿', None),
    )),
]


def source_fingerprints(root, expected):
    actual = {}
    for relative in expected:
        path = root / relative
        actual[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return actual


def main():
    parser = argparse.ArgumentParser(description='离线复现六个已确认问题；成功退出只表示现状缺陷被复现。')
    parser.add_argument('--output', type=Path, default=PACKAGE / 'repro-results.json')
    args = parser.parse_args()
    if not __debug__:
        parser.error('请勿使用 python -O。')
    supplied = os.environ.get('AM_AUDIT_SOURCE_ROOT')
    if not supplied:
        parser.error('请设置 AM_AUDIT_SOURCE_ROOT，指向原工程或固定快照重建根目录。')
    root = Path(supplied).expanduser().resolve(strict=True)
    expected = json.loads((PACKAGE / 'source-fingerprints.json').read_text(encoding='utf-8'))
    before = source_fingerprints(root, expected)
    differences = [path for path in expected if before[path] != expected[path]]
    env = dict(os.environ, AM_AUDIT_SOURCE_ROOT=str(root), PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONOPTIMIZE', None)
    script_results, defects = [], []
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for filename, findings in SCRIPTS:
        with tempfile.TemporaryDirectory(prefix='am-audit-run-') as workdir:
            try:
                completed = subprocess.run(
                    [sys.executable, '-B', str(PACKAGE / filename)], cwd=workdir,
                    env=env, capture_output=True, text=True, encoding='utf-8', timeout=30,
                )
                if completed.returncode == 0:
                    evidence = json.loads(completed.stdout)
                    state = 'defect_reproduced'
                else:
                    evidence = None
                    state = 'assertion_not_met_or_execution_error'
                item = {'script': filename, 'state': state, 'exit_code': completed.returncode,
                        'evidence': evidence}
                if completed.stderr:
                    item['stderr'] = completed.stderr
                if completed.returncode != 0 and completed.stdout:
                    item['stdout'] = completed.stdout
            except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
                item = {'script': filename, 'state': 'execution_error', 'error': str(exc)}
                evidence = None
            script_results.append(item)
            for finding_id, priority, title, key in findings:
                reproduced = item['state'] == 'defect_reproduced'
                defects.append({'id': finding_id, 'priority': priority, 'title': title,
                    'status': 'reproduced' if reproduced else 'not_established_by_this_run',
                    'script': filename, 'evidence': evidence.get(key) if reproduced and key else evidence})
    after = source_fingerprints(root, expected)
    reproduced_count = sum(item['status'] == 'reproduced' for item in defects)
    result = {
        'schema': 'am-audit-defect-reproduction-v1',
        'audit_commit': AUDIT_COMMIT,
        'source_commit_reported_by_handoff': SOURCE_COMMIT,
        'base_audit_commit': BASE_AUDIT_COMMIT,
        'started_at_utc': started,
        'finished_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'offline_defect_reproduction_only',
        'assertions_mean': 'These assertions prove the reported defective behavior; they are not fix-verification tests.',
        'live_model_calls': 0,
        'live_platform_calls': 0,
        'matches_fixed_snapshot_fingerprints': not differences,
        'source_fingerprint_differences': differences,
        'checked_source_files_unchanged': before == after,
        'script_count': len(SCRIPTS),
        'defect_count': len(defects),
        'reproduced_defect_count': reproduced_count,
        'fixed_snapshot_validation': 'six_defects_reproduced' if reproduced_count == 6 and not differences and before == after else 'not_fully_established',
        'defects': sorted(defects, key=lambda item: item['id']),
        'scripts': script_results,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'reproduced_defect_count': reproduced_count,
                     'defect_count': len(defects),
                     'matches_fixed_snapshot_fingerprints': not differences,
                     'checked_source_files_unchanged': before == after,
                     'meaning': '已复现现状缺陷；不表示修复通过。'}, ensure_ascii=False, indent=2))
    return 0 if reproduced_count == 6 and not differences and before == after else 1


if __name__ == '__main__':
    raise SystemExit(main())
