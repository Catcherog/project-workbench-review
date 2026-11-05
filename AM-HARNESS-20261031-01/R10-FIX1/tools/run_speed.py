from pathlib import Path
import subprocess,sys
T=Path(__file__).resolve().parents[1]
for i,model in enumerate(['sol','terra','terra','sol','sol','terra']):
    r=subprocess.run([sys.executable,str(T/'scripts/compare_codex_task_stack.py'),'--model','gpt-6.1-'+model,'--effort','high','--run-name',f'{model}-high-{i+1:02d}'])
    if r.returncode: raise SystemExit(r.returncode)
