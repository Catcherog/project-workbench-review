from pathlib import Path
import subprocess,json,os,tempfile
root=Path(__file__).resolve().parents[1];out=root/'evidence/ready1-fix1/after';out.mkdir(parents=True,exist_ok=True);node=os.environ.get('NODE_BINARY','node')
groups=[('dm',root/'dm',['--test','--test-reporter=tap',*sorted(str(p.relative_to(root/'dm')) for p in (root/'dm/tests').glob('*.test.mjs'))]),('bridge',root/'dm',['candidate/scripts/test-feishu-event-bridge.mjs']),('reviewer-seven',root/'reviewer-repro',['--test','--test-reporter=tap','binding-consistency.test.mjs'])]
results=[]
for group,cwd,args in groups:
 env=os.environ.copy()
 if group=='reviewer-seven':env['TMPDIR']=str(Path(tempfile.gettempdir()).resolve())
 with (out/(group+'.tap')).open('w') as f:r=subprocess.run([node,*args],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
 text=(out/(group+'.tap')).read_text();summary=[s for s in text.splitlines() if s.startswith(('# tests','# pass','# fail','# skipped','# cancelled','PASS'))]
 row={'group':group,'command':['node',*args],'cwd':str(cwd.relative_to(root)),'exit':r.returncode,'summary':summary};results.append(row);print(json.dumps(row),flush=True)
(out/'verification.json').write_text(json.dumps(results,indent=2)+'\n')
raise SystemExit(int(any(x['exit'] for x in results)))
