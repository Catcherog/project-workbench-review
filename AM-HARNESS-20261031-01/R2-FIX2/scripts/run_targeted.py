"""Run on an explicit source tree; preserve true return code and JUnit."""
from pathlib import Path
import argparse,subprocess,os,json,sys
p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--label',required=True);p.add_argument('--baseline',action='store_true');a=p.parse_args()
task=Path(__file__).resolve().parents[1];root=task.parents[1];src=(a.source or task/'worktree').resolve();st=src/'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
out=task/'evidence'/a.label;out.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=os.pathsep.join(str(x) for x in [st/'src',st/'tests',src/'am-conversation-r1/src',src/'local-qwen3.8/feishu-bridge']))
test=task/'worktree/FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests/test_harness_r2_fix2_audit.py'
cmd=[str(root/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/.venv/bin/python'),'-m','pytest',str(test)]
if not a.baseline:cmd += [str(st/'tests/test_harness_r2_fix1_audit.py')]
cmd+=['-q','-p','no:cacheprovider','--junitxml='+str(out/'counterexamples.xml')]
with (out/'counterexamples.txt').open('w') as f:run=subprocess.run(cmd,env=env,cwd=src,stdout=f,stderr=subprocess.STDOUT)
(out/'exit-code.json').write_text(json.dumps({'returncode':run.returncode,'source':subprocess.check_output(['git','rev-parse','HEAD'],cwd=src,text=True).strip(),'uncommitted':bool(subprocess.check_output(['git','diff','HEAD'],cwd=src))})+'\n')
print((out/'counterexamples.txt').read_text()[-13000:]);sys.exit(run.returncode)
