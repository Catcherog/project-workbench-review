from pathlib import Path
import json,os,subprocess,sys,time
root=Path(__file__).resolve().parents[3];task=Path(__file__).resolve().parents[1]
label=sys.argv[1];studio=root/'FS-AGENT-GROK-POC-20261017-01_R1_Studio';bridge=root/'local-qwen3.8/feishu-bridge'
out=task/'evidence'/label;out.mkdir(parents=True,exist_ok=False);tmp=out/'tmp';tmp.mkdir()
roots=[root/'am-integrated-r6',root/'am-conversation-r1/src',bridge,studio/'src',studio/'tests',root/'am-style-r5/src',root/'am-style-r3']
env=dict(os.environ,PYTHONPATH=os.pathsep.join(map(str,roots)),TMPDIR=str(tmp.resolve()),PYTHONDONTWRITEBYTECODE='1',AM_R5_HOST_SRC=str(roots[1]),AM_R5_TRAINING_ROOT=str(roots[-1]))
env['AM_R7_TEST_PYTHON']=json.loads((root/'AM-HARNESS-20261031-01/R6/private/pilot-plan-001/plan.json').read_text())['python_interpreter']['path']
targets=[studio/'tests',*sorted(bridge.glob('test*.py'))] if 'full' in label else [root/'am-integrated-r6/tests']
start=time.time()
with (out/'pytest.log').open('w') as log:
 r=subprocess.run([str(studio/'.venv/bin/python'),'-m','pytest','-q',*map(str,targets),'--junitxml='+str(out/'results.xml')],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
import xml.etree.ElementTree as E
suites=E.parse(out/'results.xml').getroot().findall('testsuite');fails=[]
for s in suites:
 for c in s.findall('testcase'):
  for kind in ('failure','error'):
   x=c.find(kind)
   if x is not None:fails.append({'id':c.attrib.get('classname','')+'::'+c.attrib['name'],'kind':kind,'message':x.attrib.get('message'),'text':x.text})
report={'label':label,'elapsed_seconds':time.time()-start,'returncode':r.returncode,'counts':{k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')},'failures':fails,'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'real_training':False,'real_model_calls':0}
(out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='failures'},ensure_ascii=False))
