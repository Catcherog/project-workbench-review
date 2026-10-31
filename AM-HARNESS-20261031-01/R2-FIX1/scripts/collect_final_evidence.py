from pathlib import Path
import json,hashlib,ast,subprocess,re,xml.etree.ElementTree as ET
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1];SRC=TASK/'worktree';OUT=TASK/'evidence'
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=SRC,text=True).strip()
def cases(path):
 out={}
 for c in ET.parse(path).iter('testcase'):
  row={'state':'passed'}
  for kind in ('failure','error','skipped'):
   n=c.find(kind)
   if n is not None:
    row={'state':kind,'type':n.get('type'),'message':n.get('message'),'assertion_locations':sorted(set(re.findall(r'(tests/[A-Za-z0-9_./-]+\.py:\d+)',n.text or '')))}
  out[c.get('classname','')+'.'+c.get('name','')]=row
 return out
before=cases(ROOT/'AM-HARNESS-20261031-01/R2/evidence/final-source-02/original.xml');after=cases(OUT/'final-source/original.xml')
bad=lambda d:{k:v for k,v in d.items() if v['state']!='passed'}
b=bad(before);a=bad(after)
comparison={'baseline_source':'60f60f564080b75206cd80b35597c1d086925354','source_commit':sha,'baseline_failures':len(b),'current_failures':len(a),
 'same_names':b.keys()==a.keys(),'same_states_types_messages_and_assertion_locations':b==a,'new_failures':sorted(a.keys()-b.keys()),'before':b,'after':a,'actual_complete_suite_exit_code':json.loads((OUT/'final-source/summary.json').read_text())['returncodes']['original'],
 'counting':'original suite, Harness and conversation are disjoint; conversation verify repeats same conversation cases and is not added'}
(OUT/'regression-comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2)+'\n')
new=[k for k in after if 'test_harness_r2_fix1_audit.' in k]
fix2={}
for name in ('test_harness_fix2.py','test_harness_r2_fix2.py'):
 relative='FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests/'+name
 baseline_bytes=subprocess.check_output(['git','show','60f60f564080b75206cd80b35597c1d086925354:'+relative],cwd=SRC)
 current_bytes=(SRC/relative).read_bytes()
 fix2[relative]={'baseline_sha256':hashlib.sha256(baseline_bytes).hexdigest(),'current_sha256':hashlib.sha256(current_bytes).hexdigest(),'byte_equal':baseline_bytes==current_bytes}
assert all(v['byte_equal'] for v in fix2.values())
(OUT/'six-fixes-tests.json').write_text(json.dumps({'source_commit':sha,'new_audit_cases':len(new),'cases':{k:after[k] for k in new},'legacy_fix2_tests_unchanged':all(v['byte_equal'] for v in fix2.values()),'fix2_assertion_sources':fix2},ensure_ascii=False,indent=2)+'\n')
import sys
sys.path.insert(0,str(SRC/'am-conversation-r1/src'))
from am_outcome.adapters import TOOL_FAMILIES
rows=[]
for p in (SRC/'am-conversation-r1/src/am_conversation').glob('*.py'):
 for n in ast.walk(ast.parse(p.read_text())):
  if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='Tool' and n.args and isinstance(n.args[0],ast.Constant):
   tool=n.args[0].value
   rows.append({'tool':tool,'family':TOOL_FAMILIES.get(tool,'unclassified'),'file':str(p.relative_to(SRC)),'line':n.lineno,'adapter':'am_outcome.adapters.adapt',
       'contract_basis':'typed native results; no success inference from prose','coverage':'bounded explicit adapters; unknown shapes remain partial/blocked'})
for row in rows:
 row['entry_kind']='synthetic_cli_verification' if row['tool']=='synthetic_notify' else 'production_tool'
for name in ('approve_knowledge','cancel_pending_action'):
 p=SRC/'am-conversation-r1/src/am_conversation/engine.py'
 line=next(i for i,v in enumerate(p.read_text().splitlines(),1) if "'"+name+"'" in v)
 rows.append({'tool':name,'family':TOOL_FAMILIES[name],'entry_kind':'original_direct_control','file':str(p.relative_to(SRC)),'line':line,'adapter':'am_outcome.adapters.adapt','contract_basis':'native versioned direct-control result; original approval/cancellation guard retained'})
(OUT/'adapter-matrix.json').write_text(json.dumps({'source_commit':sha,'method':'Static native Tool declarations plus original direct-control adapter entry points; not a claim of every branch live acceptance','tools':rows,'production_adapter_names':sorted(TOOL_FAMILIES),'unclassified_production':[r['tool'] for r in rows if r['family']=='unclassified' and r['entry_kind']!='synthetic_cli_verification'],'test_only':['synthetic_notify']},ensure_ascii=False,indent=2)+'\n')
private=Path.home()/'.local/share/local-qwen-feishu';c=json.loads((private/'config.json').read_text());loaded=json.loads((Path(c['state_directory'])/'loaded-manifest.json').read_text())
prefix={'feishu-bridge':'local-qwen3.8/feishu-bridge',**{n:'am-conversation-r1/src/'+n for n in ('am_conversation','am_reply','am_outcome','am_response')},**{n:'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/'+n for n in ('fs_agent','am_doc_engine','am_harness')}}
files={}
for name,digest in loaded['files'].items():
 group,rel=name.split('/',1);path=prefix[group]+'/'+rel
 assert hashlib.sha256((SRC/path).read_bytes()).hexdigest()==digest,path
 files[name]={'source_path':path,'original_sha256':digest}
(OUT/'runtime-loaded-map.json').write_text(json.dumps({'source_commit':sha,'loaded_files':len(files),'files':files,'response_mode':c['am_conversation'].get('response',{}).get('mode','legacy'),'rewrite_mode':c['am_conversation']['output_rewrite']['mode'],'goal_tracking':c['am_conversation'].get('runtime',{}).get('goal_tracking',False),'identity_seconds':c['am_query']['identity_cache_seconds'],'ledger_write':c['am_self']['ledger_write']},indent=2)+'\n')
print(json.dumps({'source':sha,'audit_cases':len(new),'failure_comparison_equal':b==a,'production_adapters':len(TOOL_FAMILIES),'test_only':['synthetic_notify'],'loaded_files':len(files)}))
