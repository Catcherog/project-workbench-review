"""Reproduce only the four findings on a clean, fixed git archive."""
from pathlib import Path
import subprocess,tarfile,io,tempfile,os,json,shutil,hashlib,sys
task=Path(__file__).resolve().parents[1];root=task.parents[1];out=task/'evidence/baseline-final';out.mkdir(exist_ok=True)
baseline='f767cea93444217d40a52bea6330f51434f3ce27'
with tempfile.TemporaryDirectory(prefix='r2fix2-baseline-') as temp:
    src=Path(temp)
    tarfile.open(fileobj=io.BytesIO(subprocess.check_output(['git','archive',baseline],cwd=root)),mode='r:').extractall(src,filter='data')
    st=src/'FS-AGENT-GROK-POC-20261017-01_R1_Studio';test=st/'tests/test_harness_r2_fix2_audit.py'
    shutil.copyfile(task/'worktree'/test.relative_to(src),test)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=os.pathsep.join(str(x) for x in [st/'src',st/'tests',src/'am-conversation-r1/src',src/'local-qwen3.8/feishu-bridge']))
    with (out/'counterexamples.txt').open('w') as f:
        run=subprocess.run([str(root/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/.venv/bin/python'),'-m','pytest',str(test),'-q','-p','no:cacheprovider','-k','two_overlapping or one_native_receipt or lost_result or question_does_not or statement_and_legal or forecast_metadata','--junitxml='+str(out/'counterexamples.xml')],env=env,cwd=src,stdout=f,stderr=subprocess.STDOUT)
    (out/'exit-code.json').write_text(json.dumps({'returncode':run.returncode,'source':baseline,'isolated_git_archive':True,'test_sha256':hashlib.sha256(test.read_bytes()).hexdigest()})+'\n')
    print((out/'counterexamples.txt').read_text()[-3500:]);sys.exit(run.returncode)
