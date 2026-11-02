#!/usr/bin/env python3
"""Run original local tests using the caller's correctly installed interpreter.

No service start, configuration edits, model probes, network sends or package
installation. For Studio tests, use an environment in which python -I can
import fs_agent; PYTHONPATH alone does not install the attachment worker.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def summarize(path):
    root = ET.parse(path).getroot()
    cases = root.findall('.//testcase')
    tests = {}
    for case in cases:
        ident = case.get('classname', '') + '::' + case.get('name', '')
        status = 'passed'
        detail = ''
        for kind in ('failure', 'error', 'skipped'):
            entry = case.find(kind)
            if entry is not None:
                status, detail = kind, entry.get('message', '')
                break
        tests[ident] = {'status': status, 'message': detail}
    return {'counts': {kind: sum(v['status'] == kind for v in tests.values())
                       for kind in ('passed', 'failure', 'error', 'skipped')},
            'tests': tests}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--suite', choices=['focused', 'studio', 'information'], default='focused')
    parser.add_argument('--label', default='local')
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    studio = repo / 'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
    bridge = repo / 'local-qwen3.8/feishu-bridge'
    if args.suite == 'studio':
        selected = [studio / 'tests']
    elif args.suite == 'information':
        selected = [bridge / name for name in (
            'test_am_information.py', 'test_info_cloud.py', 'test_info_sources.py',
            'test_info_url_metadata.py', 'test_info_semantics.py')]
    else:
        selected = [studio / 'tests' / name for name in (
            'test_followup_native.py', 'test_followup_final_dependencies.py',
            'test_followup_dispatch_recovery.py', 'test_followup_state_regressions.py')]
        selected += [bridge / 'test_info_semantics.py']
    missing = [str(p) for p in selected if not p.exists()]
    if missing:
        parser.error('Missing test paths: ' + ', '.join(missing))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    env['PYTHONPATH'] = os.pathsep.join(map(str, [studio / 'src', studio / 'tests', bridge,
        repo / 'am-conversation-r1/src'])) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    stem = args.label + '-' + args.suite
    xml = output / (stem + '.xml')
    # A failed pytest startup must never be paired with a previous run's XML.
    if xml.exists():
        xml.unlink()
    cmd = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
           *map(str, selected), '--junitxml=' + str(xml)]
    version = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    started = time.time()
    with (output / (stem + '.log')).open('w') as log:
        result = subprocess.run(cmd, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT)
    report = {'command': cmd, 'python': sys.version, 'exit_code': result.returncode,
              'git_head': version.stdout.strip() if version.returncode == 0 else None,
              'elapsed_seconds': round(time.time() - started, 3), 'suite': args.suite,
              'repo': str(repo), **(summarize(xml) if xml.exists() else {'xml_missing': True})}
    (output / (stem + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('tests', 'command')}, ensure_ascii=False, indent=2))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
