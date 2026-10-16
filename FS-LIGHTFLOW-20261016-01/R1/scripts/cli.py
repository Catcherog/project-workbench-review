# De-identified review copy. Not configured for live execution.
import datetime,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SPACE='TEST_SPACE'
USER='TEST_OPERATOR'
def registry():return json.loads((ROOT/'registry.json').read_text())
def call(label,args):
 p=ROOT/'evidence'/(label+'.json')
 if p.exists():raise RuntimeError('Receipt exists; reconcile before retry: '+label)
 intent=p.with_suffix('.intent.json')
 if intent.exists():raise RuntimeError('Unresolved intent: '+label)
 intent.write_text(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'args':args},ensure_ascii=False,indent=2))
 r=subprocess.run(['meegle',*args,'--format','json'],capture_output=True,text=True)
 p.write_text(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr},ensure_ascii=False,indent=2))
 if r.returncode:raise RuntimeError(r.stderr or r.stdout)
 d=json.loads(r.stdout)
 if isinstance(d,dict) and d.get('error'):raise RuntimeError(str(d['error']))
 return d
def allowed(i):
 r=registry();assert i in list(r['projects'].values())+list(r['children'].values()),'Only this task instances are writable'
def update(label,i,fields,roles=None):
 allowed(i);a=['workitem','update','--project-key',SPACE,'--work-item-id',str(i),'--fields',json.dumps([{'FIELD_09':k,'FIELD_13':v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)}for k,v in fields.items()],ensure_ascii=False)]
 if roles:a+=['--role-operate',json.dumps(roles)]
 return call(label,a)
def get(label,i):return call(label,['workitem','get','--project-key',SPACE,'--work-item-id',str(i),'--fields','_all','--page-size','200'])
def nodes(label,i):return call(label,['workflow','get-node','--project-key',SPACE,'--work-item-id',str(i),'--need-sub-task','true'])
def transition(label,i,node,action='confirm'):
 allowed(i);a=['workflow','transition','--project-key',SPACE,'--work-item-id',str(i),'--node-id',node,'--action',action]
 if action=='rollback':a+=['--rollback-reason','R1合成测试恢复；保留原记录，不影响其他项目']
 return call(label,a)
