from pathlib import Path
import os,subprocess,json,sys,time,xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
T=Path(__file__).resolve().parents[1]; R=T.parents[1]; O=T/'evidence/supplemental';O.mkdir(exist_ok=True)
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=os.pathsep.join(map(str,[R/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src',R/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests',R/'am-conversation-r1/src',R/'local-qwen3.8/feishu-bridge'])),AM_REFERENCE_ROOT=str(R/'AM-HARNESS-20261031-01/R1/review-export/fixtures/reference_am'))
commands={'harness':[sys.executable,'-m','pytest',str(R/'am-harness-r1/tests'),'-q','-p','no:cacheprovider','--junitxml='+str(O/'harness.xml')], 'conversation':[sys.executable,str(R/'am-conversation-r1/scripts/verify.py'),'--output-dir',str(O/'conversation')], 'r4':[sys.executable,'-m','pytest',str(R/'am-conversation-r1/tests'),'-q','-p','no:cacheprovider','--junitxml='+str(O/'r4.xml')]}
def execute(entry):
 name,cmd=entry;start=time.monotonic()
 with (O/(name+'.log')).open('w') as log:p=subprocess.run(cmd,cwd=R,env=env,stdout=log,stderr=subprocess.STDOUT)
 return name,{'command':cmd,'exit_code':p.returncode,'elapsed_seconds':time.monotonic()-start}
with ThreadPoolExecutor(max_workers=3) as pool: report=dict(pool.map(execute,commands.items()))
for name in ('harness','r4'):
 cases=list(ET.parse(O/(name+'.xml')).iter('testcase')); report[name].update(tests=len(cases),failures=sum(x.find('failure') is not None for x in cases),errors=sum(x.find('error') is not None for x in cases),skips=sum(x.find('skipped') is not None for x in cases))
report['conversation']['validation']=json.loads((O/'conversation/validation.json').read_text())
(O/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
