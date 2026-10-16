from pathlib import Path
import subprocess,json,os,datetime
root=Path(__file__).resolve().parents[1];node=os.environ.get('NODE_BINARY','node');out=root/'evidence/ready1';out.mkdir(exist_ok=True)
groups=[('r1',root/'r1',['--test','--test-reporter=tap',*sorted(str(p.relative_to(root/'r1')) for p in (root/'r1/tests').glob('*.test.mjs'))]),('fix3',root/'r1/vendor/fix3',['--test','--test-reporter=tap',*sorted(str(p.relative_to(root/'r1/vendor/fix3')) for p in (root/'r1/vendor/fix3/tests').glob('*.test.mjs'))]),('dm',root/'dm',['--test','--test-reporter=tap',*sorted(str(p.relative_to(root/'dm')) for p in (root/'dm/tests').glob('*.test.mjs'))]),('bridge',root/'dm',['candidate/scripts/test-feishu-event-bridge.mjs'])]
results=[]
for name,cwd,args in groups:
 with (out/(name+'.tap')).open('w') as f:r=subprocess.run([node,*args],cwd=cwd,stdout=f,stderr=subprocess.STDOUT,env=os.environ.copy())
 text=(out/(name+'.tap')).read_text();summary=[l for l in text.splitlines() if l.startswith(('# tests','# pass','# fail','# skipped','# cancelled','PASS','✓'))]
 record={'group':name,'command':['node',*args],'cwd':str(cwd.relative_to(root)),'exit':r.returncode,'summary':summary,'at':datetime.datetime.now(datetime.timezone.utc).isoformat()};results.append(record);print(json.dumps(record),flush=True)
(root/'evidence/ready1/verification.json').write_text(json.dumps(results,indent=2))
raise SystemExit(1 if any(r['exit'] for r in results) else 0)
