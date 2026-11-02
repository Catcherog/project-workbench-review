from pathlib import Path
import os,json,subprocess,hashlib,sys
task=Path(__file__).resolve().parents[1];root=task.parents[1];src=task/'worktree';st=src/'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
lock=json.loads((task/'input/model-supplement-lock.json').read_text())
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=src,text=True).strip()
assert sha==lock['source_commit'] and not subprocess.check_output(['git','diff','HEAD'],cwd=src)
for rel,digest in lock['files'].items():assert hashlib.sha256((task/rel).read_bytes()).hexdigest()==digest,rel
env=dict(os.environ,AM_R2_FIX2_L2='1',AM_R2_EVAL_SHA=sha,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=os.pathsep.join(str(x) for x in [st/'src',st/'tests',src/'am-conversation-r1/src',src/'local-qwen3.8/feishu-bridge']))
out=task/'evidence/model-supplement-run';out.mkdir(exist_ok=True)
with (out/'pytest.txt').open('x') as f:
    run=subprocess.run([str(root/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/.venv/bin/python'),'-m','pytest',str(task/'scripts/test_model_fix2_supplement.py'),'-q','-s','-p','no:cacheprovider','--junitxml='+str(out/'pytest.xml')],cwd=src,env=env,stdout=f,stderr=subprocess.STDOUT)
(out/'exit-code.json').write_text(json.dumps({'returncode':run.returncode,'source_commit':sha,'interpretation':'runner success means observations saved; inspect individual checks and adoption separately'})+'\n')
print((out/'pytest.txt').read_text()[-8000:]);sys.exit(run.returncode)
