"""Offline audit of the exact exported source; requires installed project dependencies.

Does not read production configuration, start AM, call a model or contact Feishu.
Known failing tests remain failures and produce a nonzero exit status.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT/'source'
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
out=a.output.resolve()
if out.is_relative_to(ROOT):raise ValueError('EVIDENCE_OUTPUT_MUST_BE_OUTSIDE_FROZEN_PACKAGE')
out.mkdir(parents=True,exist_ok=True)
manifest=json.loads((ROOT/'05_版本与文件清单.json').read_text())
for name,expected in manifest['files'].items():
    data=(ROOT/name).read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected['sha256']:raise ValueError('EXPORTED_FILE_CHANGED:'+name)
workspace=tempfile.TemporaryDirectory(prefix='am-harness-review-')
SOURCE=Path(workspace.name)/'source'
shutil.copytree(ROOT/'source',SOURCE)
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',
         PYTHONPATH=os.pathsep.join(str(SOURCE/p) for p in ('FS-AGENT-GROK-POC-20261017-01_R1_Studio/src','am-conversation-r1/src','local-qwen3.8/feishu-bridge')),
         AM_REFERENCE_ROOT=str(ROOT/'fixtures/reference_am'))
commands={
 'harness':[sys.executable,'-m','pytest',str(SOURCE/'am-harness-r1/tests'),'-q','-p','no:cacheprovider','--junitxml='+str(out/'harness.xml')],
 'original':[sys.executable,'-m','pytest',str(SOURCE/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests'),'-q','-p','no:cacheprovider','--junitxml='+str(out/'original.xml')],
 'conversation':[sys.executable,str(SOURCE/'am-conversation-r1/scripts/verify.py'),'--output-dir',str(out/'conversation')],
}
codes={}
for name,cmd in commands.items():
    with (out/(name+'.txt')).open('w') as log:codes[name]=subprocess.run(cmd,cwd=SOURCE,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
def result(path):
    cases=list(ET.parse(path).iter('testcase'))
    failures=sorted(x.attrib.get('classname','')+'.'+x.attrib['name'] for x in cases if x.find('failure') is not None or x.find('error') is not None)
    skips=sum(x.find('skipped') is not None for x in cases)
    return {'tests':len(cases),'passed':len(cases)-len(failures)-skips,'failures':failures,'skipped':skips}
summary={'source_commit':manifest['source_commit'],'files_verified_before_tests':len(manifest['files']),
         'returncodes':codes,'harness':result(out/'harness.xml'),'original':result(out/'original.xml'),
         'conversation':json.loads((out/'conversation/validation.json').read_text()),'live_model':False,'live_feishu':False}
known=set(result(ROOT/'verification/preexisting-pytest.xml')['failures'])
summary['new_failures']=sorted(set(summary['original']['failures'])-known)
summary['status']='passed' if not any(codes.values()) else 'failed'
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':summary['status'],'returncodes':codes,'new_failures':summary['new_failures']}))
sys.exit(0 if summary['status']=='passed' else 1)
