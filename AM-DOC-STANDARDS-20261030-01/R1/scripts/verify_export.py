"""Assemble isolated validation support; no credentials, network or service mutation."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
project=root/'source/FS-AGENT-GROK-POC-20261017-01_R1_Studio'
results=[]
with tempfile.TemporaryDirectory(prefix='amdoc-export-check-') as directory:
    src=Path(directory)/'src'
    shutil.copytree(root/'validation_support',src)
    shutil.copytree(project/'src',src,dirs_exist_ok=True)
    env=dict(os.environ,PYTHONPATH=str(src))
    commands=[([sys.executable,'-m','pytest','-q',str(project/'tests/test_document_standards.py')],root,'host-new'),
              ([sys.executable,'-m','unittest','discover','-s','tests','-t','.'],root/'engine_reference','engine-core')]
    for command,cwd,name in commands:
        run=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True)
        text=run.stdout+run.stderr
        (root/'verification'/('export-'+name+'.txt')).write_text(text)
        results.append({'suite':name,'exit_code':run.returncode,'output':text})
        print(text)
(root/'verification/export-checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
raise SystemExit(any(r['exit_code'] for r in results))
