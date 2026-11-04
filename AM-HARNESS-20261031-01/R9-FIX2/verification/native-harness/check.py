from pathlib import Path
import os,sys,json,time,hashlib,subprocess,xml.etree.ElementTree as ET
task=Path(__file__).resolve().parents[1];host=task.parents[1]
root=Path(os.environ.get('AM_FIX2_CHECK_ROOT',str(task/'worktree')))
label=sys.argv[1];out=task/'evidence'/label;out.mkdir(parents=True,exist_ok=False)
studio=root/'FS-AGENT-GROK-POC-20261017-01_R1_Studio';bridge=root/'local-qwen3.8/feishu-bridge'
paths=[root/'am-integrated-r6',root/'am-conversation-r1/src',bridge,studio/'src',studio/'tests',root/'am-style-r5/src',root/'am-style-r3']
env=dict(os.environ,PYTHONPATH=os.pathsep.join(map(str,paths)),PYTHONDONTWRITEBYTECODE='1')
plan=host/'AM-HARNESS-20261031-01/R6/private/pilot-plan-001/plan.json'
env.update(AM_R5_HOST_SRC=str(paths[1]),AM_R5_TRAINING_ROOT=str(paths[-1]),AM_R7_TEST_PYTHON=json.loads(plan.read_text())['python_interpreter']['path'])
def manifest():
    files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    files+=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
    return {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sorted(set(files)) if p and (root/p).is_file() and '__pycache__' not in p and not p.startswith(('AM-','SFT','交付'))}
before=manifest();(out/'source-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
targets=sys.argv[2:] or [str(studio/'tests'),*map(str,sorted(bridge.glob('test*.py')))]
started=time.time()
with (out/'pytest.log').open('w') as f:
    r=subprocess.run([str(host/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/.venv/bin/python'),'-m','pytest','-q','-p','no:cacheprovider',*targets,'--junitxml='+str(out/'results.xml')],cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT)
after=manifest();(out/'source-after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
suites=ET.parse(out/'results.xml').getroot().findall('testsuite');fails=[]
for suite in suites:
    for case in suite.findall('testcase'):
        for kind in ('failure','error'):
            failure=case.find(kind)
            if failure is not None:fails.append({'id':case.attrib.get('classname','')+'::'+case.attrib['name'],'kind':kind,'message':failure.attrib.get('message'),'text':failure.text})
result={'label':label,'returncode':r.returncode,'elapsed':time.time()-started,'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'source_unchanged_during_run':before==after,'counts':{k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')},'failures':fails,'real_model_calls':0}
(out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!='failures'},ensure_ascii=False))
print('\n'.join((out/'pytest.log').read_text().splitlines()[-min(12,len(fails)+2):]))
