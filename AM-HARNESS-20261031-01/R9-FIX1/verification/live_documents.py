"""Operator-only local document session with real source reads and original Qwen.
No ingress fabrication in the live service, no consumer, no external mutation.
The information store is opened in SQLite read-only mode; document state is local.
"""
from pathlib import Path
import argparse,json,os,sqlite3,sys,threading,time,uuid,hashlib
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[3];TASK=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('local-qwen3.8/feishu-bridge','FS-AGENT-GROK-POC-20261017-01_R1_Studio/src','am-conversation-r1/src','am-integrated-r6')]
from fs_agent.config import Config,BoundaryError
from fs_agent.feishu import Feishu
from fs_agent.store import Store
from fs_agent.gateway import Gateway
from fs_agent.document_standards import DocumentStandards,load_settings
from fs_agent.model_coordinator import ModelCoordinator
from fs_agent.qwen_provider import LocalQwenProvider
from am_service import AmSelfService
from group_ledger import FeishuLedgerPort,GroupLedger
from am_information import AMInformation
from am_info_sync.store import Store as InfoStore
from am_info_sync.runtime import InformationService
from am_info_sync.facts import FactEngine
from am_info_sync.models import now_ms
from am_conversation.documents import DocumentTools
from am_conversation.legacy import LegacyConversationBridge

p=argparse.ArgumentParser();p.add_argument('stage',choices=['read','generate']);p.add_argument('--kind',choices=['charter','change','closure'],default='charter');p.add_argument('--label',default='initial');a=p.parse_args()
os.umask(0o077)
cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text());config=Config.load(Path(cfg['poc_config']));config.check_service();api=Feishu(config)
out=TASK/'private'/('live-document-'+a.kind+('' if a.label=='initial' else '-'+a.label));out.mkdir(parents=True,exist_ok=True,mode=0o700)
source_store=Store(config.db);provider=ModelCoordinator(LocalQwenProvider(config),source_store,config.root/'state');provider.pin()
store=Store(out/'gateway.sqlite3')
class ReadOnlyApi:
 def __getattr__(self,name):
  if name in ('send','upload','upload_file','create_document','update_document'):raise AssertionError('EXTERNAL_MUTATION_NOT_AUTHORIZED')
  return getattr(api,name)
g=Gateway(config,store,ReadOnlyApi(),provider)
settings=load_settings(config.root);g.logic.standards=DocumentStandards(g.logic,settings)
port=FeishuLedgerPort(api.client,app_id=config.app_id,tenant_key=config.tenant_key,bot_open_id=config.bot_open_id,department_root_id=cfg['group_ledger']['department_root_id'],disclosure=cfg['group_ledger'].get('disclosure',{}))
ledger=GroupLedger(out,port,lambda *a,**k:(_ for _ in ()).throw(AssertionError('NO_SEND')))
am=AmSelfService(g,ledger,flags=cfg['am_self'],query_settings=cfg['am_query'])
# Use the original read methods against the real, currently running information DB.
info_store=InfoStore.__new__(InfoStore);info_store.path=str(Path(cfg['state_directory'])/'information/information.sqlite3');info_store.clock=now_ms;info_store._lock=threading.RLock()
info_store.conn=sqlite3.connect(Path(info_store.path).as_uri()+'?mode=ro',uri=True,isolation_level=None,check_same_thread=False,timeout=10);info_store.conn.row_factory=sqlite3.Row
service=InformationService.__new__(InformationService);service.store=info_store;service.facts=FactEngine.__new__(FactEngine);service.facts.store=info_store;service.facts.clock=now_ms
info=AMInformation.__new__(AMInformation);info.store=info_store;info.service=service;info.am=am;am.information=info
g.logic.shared_evidence=info.evidence_bundle;g.logic.shared_evidence_current=info.document_evidence_current;g.logic.shared_evidence_authorize=info.authorize_document_evidence
now=time.time();row=dict(id='r9fix1-local-'+uuid.uuid4().hex,app=config.app_id,tenant=config.tenant_key,user=config.owner,chat='r9fix1-local-document-validation',chat_type='p2p',created=now,received=now,expires=now+3600,body='',kind='text')
report={'source_commit':__import__('subprocess').check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'stage':a.stage,'kind':a.kind,'real_feishu_reads':True,'actual_user_ingress':False,'human_acceptance':False,'external_writes':0,'independent_engineer_acceptance':'deferred_by_user','stages':[]}
start=time.monotonic()
access_changes=[];watch_stop=threading.Event();watch_thread=None
def watch_access():
 with sqlite3.connect(Path(info_store.path).as_uri()+'?mode=ro',uri=True) as db:
  def snapshot():
   epoch=db.execute('SELECT revision FROM source_access_version WHERE singleton=1').fetchone()[0]
   rows={r[0]:(r[1],hashlib.sha256(r[2].encode()).hexdigest()) for r in db.execute('SELECT source_id,availability,config_json FROM sources')}
   return epoch,rows
  previous,states=snapshot()
  while not watch_stop.wait(1):
   epoch,current=snapshot()
   if epoch!=previous:
    changed=[{'source_sha256':hashlib.sha256(k.encode()).hexdigest(),'before_availability':states.get(k,(None,None))[0],
     'after_availability':current.get(k,(None,None))[0],'configuration_changed':states.get(k,(None,None))[1]!=current.get(k,(None,None))[1]}
     for k in set(states)|set(current) if states.get(k)!=current.get(k)]
    access_changes.append({'seconds':time.monotonic()-start,'before_revision':previous,'after_revision':epoch,'changed_sources':changed})
   previous,states=epoch,current
def progress(stage):
 entry={'stage':stage,'seconds':round(time.monotonic()-start,3)};report['stages'].append(entry);print(json.dumps(entry),flush=True)
g.logic.standards.progress=progress
try:
 am.query_grant(row)
 am.snapshots.refresh().result(45)
 project,bundle=info.evidence_bundle(row,'IRAD-2026-003')
 (out/'evidence-bundle-private.json').write_text(json.dumps(bundle.data,ensure_ascii=False,indent=2))
 current=info.document_evidence_current(row,bundle.data['document_binding'])
 report.update(project_code='IRAD-2026-003',project_type_selection='IRAD:L1 reused prior operator test, not business approval',binding_current=current,claims=len(bundle.data['claims']),source_gaps=len(bundle.data['gaps']),project_read_seconds=time.monotonic()-start)
 progress('shared_project_evidence')
 if a.stage=='read':
  from fs_agent.document_delivery import discover_targets
  report['delivery_discovery']={}
  for kind in ('charter','change','closure'):
   status=discover_targets(g.logic.business,row,project_code='IRAD-2026-003',doc_type=kind,guard=lambda:g.authorized(row),deadline=time.monotonic()+120)
   (out/('target-'+kind+'-private.json')).write_text(json.dumps(status,ensure_ascii=False,indent=2))
   report['delivery_discovery'][kind]={'state':status['state'],'targets':len(status['targets']),'unresolved':len(status['unresolved']),'read_only':True,'diagnostics':[dict(d,alias=hashlib.sha256(d['alias'].encode()).hexdigest()[:12]) for d in status.get('diagnostics',[])]}
 if a.stage=='generate':
  watch_thread=threading.Thread(target=watch_access,daemon=True);watch_thread.start()
  if (out/'generation-attempted.json').exists():raise RuntimeError('DO_NOT_REPLAY_GENERATION')
  (out/'generation-attempted.json').write_text(json.dumps({'time':time.time(),'row_id':row['id']}))
  # Exact original document tool methods, with an operator-local scope.
  ctx=NS(session_id='r9fix1-local-document-session',can_access_project=lambda value:value==project['key'])
  bridge=NS(service=am,s=store,_current=lambda _: {'row':row},authorize=lambda *a,**k:am.query_grant(row),projects=NS(read_project=lambda _ctx,pid:project if pid==project['key'] else (_ for _ in ()).throw(BoundaryError('PROJECT_ACCESS_DENIED'))))
  dt=DocumentTools(bridge);row['body']='按台账正式模板整理 IRAD-2026-003 项目的'+{'charter':'章程','change':'变更申请','closure':'结项报告'}[a.kind]+'，项目类型 IRAD，级别 L1；仅作验收草稿。'
  result=dt.edit(ctx,{'operation':'template','project_id':project['key'],'kind':a.kind,'project_type':'IRAD','level':'L1'},row['id'])
  draft_id=result['draft_id'];task=store.rows('SELECT * FROM tasks ORDER BY rowid DESC LIMIT 1')[0]
  task['run_id']=uuid.uuid4().hex;store.execute("UPDATE tasks SET run_id=?,state='running' WHERE id=?",(task['run_id'],task['id']))
  content,result,expires=g.logic.generate(task,lambda *args:None)
  store.execute("UPDATE tasks SET state='completed' WHERE id=?",(task['id'],))
  draft=g.logic.get(row,draft_id);payload=json.loads(store.rows('SELECT payload FROM amdoc_results WHERE draft_id=? AND revision=?',(draft_id,draft['revision']))[0]['payload'])
  (out/'draft-private.md').write_text(content);(out/'result-private.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
  report.update(draft_state=draft['state'],document_state=payload['document']['state'],revision=draft['revision'],content_sha256=draft['content_hash'],fields=len(payload['document']['fields']),issues=len(payload['document']['issues']),timings=payload['timings'],actual_qwen_calls=payload['timings']['model_calls'],draft_id_sha256=hashlib.sha256(draft_id.encode()).hexdigest())
  report['read_metadata']=dt.read(ctx,{'draft_id':draft_id,'section':'summary'},'r9-read')
  status=dt.delivery(ctx,{'draft_id':draft_id,'version':draft['revision']},'r9-target')
  (out/'delivery-private.json').write_text(json.dumps(status,ensure_ascii=False,indent=2));report['delivery_state']=status['state'];report['delivery_target_count']=len(status['targets']);report['delivery_unresolved_count']=len(status['unresolved'])
  # Current reads and local adoption are script checks, never claimed as user approval.
  report['content_read_matches']=dt.read(ctx,{'draft_id':draft_id,'section':'content'},'r9-content')['drafts'][0]['content']==content
  report['read_review_succeeded']=bool(dt.read(ctx,{'draft_id':draft_id,'section':'review'},'r9-review')['drafts'])
  row['body']='这版文字可以，采用这版（本地脚本验收，非本人批准）'
  adopted=dt.edit(ctx,{'operation':'adopt','draft_id':draft_id,'version':draft['revision'],'content_hash':draft['content_hash']},'r9fix1-local-adopt')
  report['local_adoption_recorded']=adopted['accepted_hash']==draft['content_hash']
  report['publish_preview']=dt.publish_preview(ctx,{'draft_id':draft_id,'version':draft['revision'],'content_hash':draft['content_hash'],'operation':'save_cloud'})
  report['external_action_status']='preview_only_no_user_approval'
  report.pop('read_metadata',None)
 report['status']='completed'
except Exception as exc:
 report.update(status='failed',error_type=type(exc).__name__,error=str(exc));import traceback;(out/(a.stage+'-traceback.log')).write_text(traceback.format_exc())
finally:
 watch_stop.set()
 if watch_thread:watch_thread.join(3)
 report['access_changes']=access_changes
 report['elapsed_seconds']=time.monotonic()-start
 traces=store.rows('SELECT trace FROM amdoc_attempt_traces') if store.rows("SELECT 1 FROM sqlite_master WHERE name='amdoc_attempt_traces'") else []
 report['attempt_traces']=[json.loads(t['trace']) for t in traces]
 (out/(a.stage+'-summary.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:report[k] for k in ('status','stage','kind','elapsed_seconds','error_type','error','draft_state','document_state','actual_qwen_calls','content_read_matches','delivery_state','delivery_target_count') if k in report},ensure_ascii=False),flush=True)
 am.close_query();port.identity_pool.shutdown(wait=True,cancel_futures=True);g.pool.shutdown(wait=True);g.delivery_pool.shutdown(wait=True);g.verification_pool.shutdown(wait=True);ledger.db.close();store.close();info_store.close();source_store.close()
