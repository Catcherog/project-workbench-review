"""Run only the five offline audit regressions against a chosen AM source root."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True,
                        help='Original workspace root or the fixed review export source/ directory')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.output.resolve()
    if out.is_relative_to(source):
        raise SystemExit('Keep evidence output outside the selected source tree.')
    poc = source / 'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
    convo = source / 'am-conversation-r1'
    bridge = source / 'local-qwen3.8/feishu-bridge'
    required = [poc/'src/am_harness/host_context.py', poc/'src/am_harness/runtime.py',
                poc/'src/am_harness/fastpath.py', poc/'tests/test_harness_host.py',
                convo/'src/am_conversation/engine.py', bridge/'am_harness_host.py']
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit('Missing original source/test files: ' + ', '.join(missing))
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in required}
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    paths = [poc/'src', poc/'tests', convo/'src', bridge]
    old_path = env.get('PYTHONPATH')
    env['PYTHONPATH'] = os.pathsep.join([*(str(p) for p in paths), *([old_path] if old_path else [])])
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    test_file = Path(__file__).resolve().parent/'tests/test_harness_regressions.py'
    command = [sys.executable, '-m', 'pytest', str(test_file), '-q', '-s',
               '-p', 'no:cacheprovider', '--junitxml=' + str(out/'regressions.xml')]
    with (out/'regressions.txt').open('w') as log:
        code = subprocess.run(command, cwd=source, env=env, stdout=log,
                              stderr=subprocess.STDOUT).returncode
    cases = list(ET.parse(out/'regressions.xml').iter('testcase'))
    failures = [p.get('name') for p in cases if p.find('failure') is not None]
    errors = [p.get('name') for p in cases if p.find('error') is not None]
    skipped = [p.get('name') for p in cases if p.find('skipped') is not None]
    after = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in required}
    summary = {'returncode': code, 'tests': len(cases),
               'passed': len(cases)-len(failures)-len(errors)-len(skipped),
               'failures': failures, 'errors': errors, 'skipped': skipped,
               'source_stable': hashes == after, 'source_sha256': hashes,
               'python': sys.version, 'synthetic_only': True,
               'live_qwen': False, 'live_feishu': False, 'production_changed': False}
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ('tests','passed','failures','errors','source_stable')}, ensure_ascii=False))
    return code if hashes == after else 2


if __name__ == '__main__':
    raise SystemExit(main())
