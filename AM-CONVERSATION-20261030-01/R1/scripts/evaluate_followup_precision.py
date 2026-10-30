"""Actual pinned Qwen; isolated original AM with synthetic business and Feishu."""
import importlib.util,json,sys,time,tempfile,hashlib
from pathlib import Path
from contextlib import ExitStack
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-CONVERSATION-20261030-01/R1';STUDIO=ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
if importlib.util.find_spec('pytest') is None:sys.path.append(str(STUDIO/'.venv/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'))
sys.path[:0]=[str(STUDIO/'tests'),str(STUDIO/'src'),str(ROOT/'local-qwen3.8/feishu-bridge'),str(ROOT/'am-conversation-r1/src')]
from test_conversation_integration import base_rig,am_rig,service,ux,convo,speak
from fs_agent.config import Config
from fs_agent.store import Store
from fs_agent.qwen_provider import LocalQwenProvider
from fs_agent.model_coordinator import ModelCoordinator
private=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((private/'config.json').read_text());config=Config.load(Path(settings['poc_config']))
store=Store(config.db);coordinator=ModelCoordinator(LocalQwenProvider(config),store,config.root/'state')
report={'real_model':True,'model':coordinator.pin()['model'],'synthetic_business_and_transport_only':True,'real_business_calls':0,'started_at':time.time(),'turns':[],
 'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'am-conversation-r1/src').rglob('*.py')}}
class Measured:
 def complete(self,prompt,**kw):
  before=time.monotonic();r={'prompt_chars':len(prompt)}
  try:
   value=coordinator.complete(prompt,**kw);r.update(usage=value.usage,proposal=json.loads(value.text));return value
  except Exception as exc:r['error']=str(exc)[:80];raise
  finally:r['seconds']=time.monotonic()-before;calls.append(r)
calls=[]
with tempfile.TemporaryDirectory(prefix='am-conversation-real-model-') as directory,ExitStack() as stack:
 def fixture(gen):
  value=next(gen);stack.callback(lambda:next(gen,None));return value
 base=fixture(base_rig.__wrapped__(Path(directory)));base[4].now=time.time()
 setup=fixture(service.__wrapped__(am_rig.__wrapped__(base),Path(directory)))
 rig=fixture(convo.__wrapped__(ux.__wrapped__(setup)));am,g,s,api,clock,port=rig[0]
 am.conversation.agent.model.model.coordinator=Measured()
 def turn(text):
  start=time.monotonic();before=len(calls);row,reply=speak(rig,text)
  report['turns'].append({'input':text,'reply':reply,'state':row['state'],'error':row['error'],'seconds':time.monotonic()-start,'model_calls':calls[before:]})
  (TASK/'evidence/qwen-followup-precision.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps({'turn':len(report['turns']),'state':row['state'],'error':row['error'],'seconds':round(time.monotonic()-start,2),'calls':len(calls)-before}),flush=True)
  if row['state']!='done':raise RuntimeError('EVALUATION_TURN_FAILED')
 turn('给需求75登记一项跟进：核对合成测试报告，要求保留尚未验收的状态，预计明天下午处理。不用发消息。')
 item=s.rows('SELECT * FROM action_items')[0]
 expected=(datetime.fromtimestamp(clock(),ZoneInfo('Asia/Shanghai'))+timedelta(days=1)).strftime('%Y-%m-%d')
 report['checks']={'estimate_preserved':item['deadline_kind']=='estimate','afternoon_not_invented_as_clock':item['next_check'] is None,'relative_day_anchored':expected in item['deadline'] and '明天' not in item['deadline'],'afternoon_preserved':'下午' in item['deadline'],'no_plan_or_send':not s.rows('SELECT * FROM reminder_plans') and not s.rows('SELECT * FROM am_conversation_sends')}
 report['stored_deadline']=item['deadline'];assert all(report['checks'].values())
 (TASK/'evidence/qwen-followup-precision.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report['checks']),flush=True)
store.close()
