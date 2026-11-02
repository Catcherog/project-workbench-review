"""Verify the current assembled AM tree, recording failures without hiding them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--reference-root',type=Path)
p.add_argument('--baseline-results',type=Path)
a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
paths=[ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src',ROOT/'am-conversation-r1/src',ROOT/'local-qwen3.8/feishu-bridge']
env=dict(os.environ,PYTHONPATH=os.pathsep.join(map(str,paths)),PYTHONDONTWRITEBYTECODE='1')
if a.reference_root:env['AM_REFERENCE_ROOT']=str(a.reference_root.resolve())
def fingerprint():
    files={}
    for base in paths+[ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests',ROOT/'am-conversation-r1/tests',ROOT/'am-harness-r1']:
        for path in sorted(base.rglob('*.py')):
            if '__pycache__' not in path.parts:files[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    return files
before=fingerprint();started=time.time()
commands={
    'harness':[sys.executable,'-m','pytest',str(ROOT/'am-harness-r1/tests'),'-q','--junitxml='+str(out/'harness.xml')],
    'original':[sys.executable,'-m','pytest',str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests'),'-q','--junitxml='+str(out/'original.xml')],
    'conversation':[sys.executable,str(ROOT/'am-conversation-r1/scripts/verify.py'),'--output-dir',str(out/'conversation')],
}
codes={}
for name,cmd in commands.items():
    with (out/(name+'.txt')).open('w') as log:
        codes[name]=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
def report(path):
    tree=ET.parse(path);cases=list(tree.iter('testcase'));failed={};skipped=[]
    for c in cases:
        name=c.attrib.get('classname','')+'.'+c.attrib['name']
        if c.find('failure') is not None or c.find('error') is not None:failed[name]=True
        if c.find('skipped') is not None:skipped.append(name)
    return {'tests':len(cases),'passed':len(cases)-len(failed)-len(skipped),'failures':list(failed),'skipped':skipped}
summary={'started_at':started,'finished_at':time.time(),'source_stable':before==fingerprint(),
         'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
         'returncodes':codes,'synthetic_only':True,'live_qwen':False,'live_feishu':False}
for name in ('harness','original'):summary[name]=report(out/(name+'.xml'))
summary['conversation']=json.loads((out/'conversation/validation.json').read_text())
if a.baseline_results:
    known=set(report(a.baseline_results)['failures']);current=set(summary['original']['failures'])
    summary['baseline_comparison']={'known_failures':len(known),'remaining_preexisting':sorted(current&known),'new_failures':sorted(current-known)}
summary['status']='passed' if not any(codes.values()) and summary['source_stable'] else 'failed'
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
(out/'source-sha256.json').write_text(json.dumps(before,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':summary['status'],'returncodes':codes,'source_stable':summary['source_stable']}))
sys.exit(0 if summary['status']=='passed' else 1)
