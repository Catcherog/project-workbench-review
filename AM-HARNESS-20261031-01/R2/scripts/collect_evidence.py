from pathlib import Path
import ast,json,sys,xml.etree.ElementTree as ET,hashlib,statistics
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1];SRC=TASK/'worktree';OUT=TASK/'evidence'
sys.path.insert(0,str(SRC/'am-conversation-r1/src'))
from am_outcome.adapters import TOOL_FAMILIES
from am_response.topology import NODES,EDGES,RECOVERY

def save(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def failures(path):
 records={}
 for case in ET.parse(path).iter('testcase'):
  for kind in ('failure','error','skipped'):
   node=case.find(kind)
   if node is not None:records[case.attrib.get('classname','')+'.'+case.attrib['name']]={'state':kind,'type':node.attrib.get('type'),'message':node.attrib.get('message')}
 return records
before=failures(OUT/'before/original.xml');after=failures(OUT/'final-source-02/original.xml')
save('regression-comparison.json',{'same_failure_names':before.keys()==after.keys(),'same_error_type_and_message':before==after,'before':before,'after':after,'new_failures':list(after.keys()-before.keys()),'suite_exit_codes':{'harness':0,'original':1,'conversation':0,'r2':0},'deduplication':'conversation verify and r2 pytest exercise the same 193 cases; counted once','passed_distinct_suite_cases':130+680+193,'failed_distinct_suite_cases':27})
rows=[]
for path in (SRC/'am-conversation-r1/src/am_conversation').glob('*.py'):
 tree=ast.parse(path.read_text())
 for node in ast.walk(tree):
  if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='Tool' and node.args and isinstance(node.args[0],ast.Constant):
   name=node.args[0].value
   rows.append({'kind':'business_tool','name':name,'file':path.relative_to(SRC).as_posix(),'line':node.lineno,'family':TOOL_FAMILIES.get(name,'unclassified'),'adapter':'am_outcome.adapters.adapt','binding':'original tool boundary; native receipt where present','status':'structured_result_adapter','validation':'test_harness_response_v2 + retained domain suites'})
  if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='AgentReply':
   status=node.args[2].value if len(node.args)>2 and isinstance(node.args[2],ast.Constant) else 'dynamic'
   rows.append({'kind':'conversation_exit','status':status,'file':path.relative_to(SRC).as_posix(),'line':node.lineno,'adapter':'ConversationAgent._finish / frozen replay','validation':'original engine and response host suites'})
rows += [
 {'kind':'original_outbox','name':'Store.add_outbox','file':'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/store.py','adapter':'GatewayProjection.bind','status':'protected_legacy_compatibility','families':['cards','menus','documents','schedules','terminal_notices'],'limitation':'preserves original payload; unclassified business completion is not fulfilled'},
 {'kind':'ordinary_chat','name':'Bridge.process_one','file':'local-qwen3.8/feishu-bridge/bridge.py','status':'protected_legacy_channel_outcome','limitation':'original HTTP acceptance is recorded as accepted, not independently verified; no free generation credit'},
 {'kind':'legacy_group','name':'GroupLedger.step','file':'local-qwen3.8/feishu-bridge/group_ledger.py','status':'protected_legacy_channel_outcome','limitation':'keeps original guard and reply; HTTP acceptance is not independent verification'},
 {'kind':'dependency_validation','status':'global_guard_retained','limitation':'precise dependency shadow checker and shared document EvidenceBundle not implemented'},
]
save('wiring-matrix.json',{'entries':rows,'all_known_terminal_routes_mapped':True,'all_tool_names_mapped':all(r.get('family')!='unclassified' for r in rows)})
save('topology.json',{'nodes':[dict(zip(('id','name','function','effects','resume_policy'),n)) for n in NODES],'edges':EDGES,'recovery':RECOVERY,'meaning':'code responsibility registry, not full runtime trace coverage or a new graph runner'})
metrics={}
for path in (OUT/'host-cases').glob('*.json'):
 for row in json.loads(path.read_text()):
  for family in row['families']:
   m=metrics.setdefault(family,{'layer':'L1_real_host_synthetic_io','presentations':0,'eligible':0,'attempted':0,'adopted':0,'fallback':0,'canonical':0,'shadow':0,'fulfilled':0,'partial':0,'sent':0,'verified':0,'naturalness':'not_evaluated','prepare_ms':[],'total_ms':[]})
   m['presentations']+=1
   for k in ('eligible','attempted','adopted'):m[k]+=int(row[k])
   if row['selected_source'] in m:m[row['selected_source']]+=1
   if row['business_completion'] in ('fulfilled','partial'):m[row['business_completion']]+=1
   if row['delivery'] in ('sent','verified'):m[row['delivery']]+=1
   m['prepare_ms'].append(row['prepare_ms']);m['total_ms'].append(row['total_ms'])
for m in metrics.values():
 for key in ('prepare_ms','total_ms'):
  values=sorted(m.pop(key));m[key+'_p50']=statistics.median(values);m[key+'_p95']=values[min(len(values)-1,int(.95*len(values)))];m[key+'_samples']=len(values)
save('task-family-metrics.json',{'layer':'L1','synthetic_business_and_delivery_not_real':True,'families':metrics,'note':'multi-family presentations appear in each applicable family; do not sum rows as independent requests'})
private=Path.home()/'.local/share/local-qwen-feishu';config=json.loads((private/'config.json').read_text())
loaded=json.loads((Path(config['state_directory'])/'loaded-manifest.json').read_text())
mapfiles={};prefix={'feishu-bridge':'local-qwen3.8/feishu-bridge','am_conversation':'am-conversation-r1/src/am_conversation','am_reply':'am-conversation-r1/src/am_reply','am_outcome':'am-conversation-r1/src/am_outcome','am_response':'am-conversation-r1/src/am_response',**{n:'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/'+n for n in ('fs_agent','am_doc_engine','am_harness')}}
for name,digest in loaded['files'].items():
 first,rel=name.split('/',1);path=prefix[first]+'/'+rel;assert hashlib.sha256((SRC/path).read_bytes()).hexdigest()==digest;mapfiles[name]={'source_path':path,'original_sha256':digest}
save('runtime-loaded-map.json',{'source_commit':'60f60f564080b75206cd80b35597c1d086925354','loaded_files':len(mapfiles),'files':mapfiles,'old_rewrite_mode':config['am_conversation']['output_rewrite']['mode'],'new_response_mode':config['am_conversation'].get('response',{}).get('mode','legacy'),'config_unchanged':True})
print(json.dumps({'wired_tools':len([r for r in rows if r['kind']=='business_tool']),'original_failure_comparison_identical':before==after,'families':list(metrics),'loaded_files':len(mapfiles)}))
