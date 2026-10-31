from pathlib import Path
import os,sys,subprocess
r=Path(__file__).resolve().parents[1]/'worktree';st=r/'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',AM_R2_FIX1_L2='1',PYTHONPATH=os.pathsep.join(str(p) for p in (st/'src',st/'tests',r/'am-conversation-r1/src',r/'local-qwen3.8/feishu-bridge')))
if os.environ.get('AM_R2_FIX1_DRY')!='1' and 'test_capture_outcomes.py' not in ' '.join(sys.argv):
    import json
    if (r.parent/'input/hold-full-evaluation').exists():raise SystemExit('Core revision verification in progress; no formal tasks queued')
    lock=json.loads((r.parent/'input/evaluation-lock.json').read_text())
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip()
    if actual!=lock['source_commit'] or subprocess.run(['git','diff','--quiet','HEAD'],cwd=r).returncode:raise SystemExit('Evaluation source changed; explicit refreeze required')
    env['AM_R2_EVAL_SHA']=actual
args=sys.argv[1:]
code=subprocess.run([sys.executable,'-m','pytest',str(Path(__file__).with_name('test_model_tasks.py')),'-q','-s','-p','no:cacheprovider',*args],env=env).returncode
sys.exit(code)
