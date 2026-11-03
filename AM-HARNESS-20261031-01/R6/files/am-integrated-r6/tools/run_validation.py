"""Run offline contracts against an already merged original repository.

Uses temporary databases and synthetic providers. Never loads production state,
starts a real model/trainer, contacts Feishu, or installs dependencies.
"""
from argparse import ArgumentParser
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--with-r5', action='store_true')
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    module = repo / 'am-integrated-r6'
    studio = repo / 'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
    bridge = repo / 'local-qwen3.8/feishu-bridge'
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error('--output must be a new or empty evidence directory')
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(map(str, [module, repo/'am-conversation-r1/src',
        bridge, studio/'src', studio/'tests', repo/'am-style-r5/src', repo/'am-style-r3']))
    if os.environ.get('PYTHONPATH'):
        env['PYTHONPATH'] += os.pathsep + os.environ['PYTHONPATH']
    targets = [module/'tests/followup', module/'tests/integration']
    targets += [studio/'tests'/('test_followup_'+name+'.py') for name in (
        'native','dispatch_recovery','final_dependencies','owner_validation',
        'navigation','state_regressions','text_host')]
    targets += [bridge/name for name in ('test_info_semantics.py','test_info_semantic_scopes.py','test_info_sources.py')]
    missing = [str(p) for p in targets if not p.exists()]
    if missing:
        parser.error('Merge all files into the current repository first; missing: '+', '.join(missing))
    commands = [
        ('integrated-native', [sys.executable,'-m','pytest','-q',*map(str,targets),
                              '--junitxml='+str(output/'integrated-native.xml')]),
        ('resource-contracts', [sys.executable,'-m','unittest','discover','-s',
                                str(module/'tests/resource_window'),'-v']),
        ('resource-host', [sys.executable,str(module/'tools/verify_existing_host.py'),
                           '--host-source',str(studio/'src')]),
        ('resource-claims', [sys.executable,str(module/'tools/verify_claim_guards.py'),
                             '--host-source',str(studio/'src'),'--overlay',str(repo)]),
    ]
    if args.with_r5:
        commands.append(('r5-contracts',[sys.executable,'-m','unittest','discover','-s',
                                         str(repo/'am-style-r5/tests'),'-v']))
    results = []
    for name, command in commands:
        print('Running '+name, flush=True)
        with (output/(name+'.log')).open('w', encoding='utf-8') as log:
            completed = subprocess.run(command, cwd=repo, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, check=False)
        entry = {'name':name,'argv':command,'returncode':completed.returncode,'log':name+'.log'}
        if name == 'integrated-native' and (output/'integrated-native.xml').exists():
            suites = ET.parse(output/'integrated-native.xml').getroot().findall('testsuite')
            entry['counts'] = {key:sum(int(s.attrib.get(key,0)) for s in suites)
                               for key in ('tests','failures','errors','skipped')}
        results.append(entry)
    summary = {'scope':'offline synthetic-platform contracts against current source',
               'real_model_calls':0,'trainer_attempts':0,'live_platform_sends':0,
               'production_state_used':False,'groups':results,
               'success':all(r['returncode']==0 for r in results)}
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if summary['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
