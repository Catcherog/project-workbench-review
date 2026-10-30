"""Labeled owner-only live tests. Never sends business content or to colleagues."""
import json,sqlite3,subprocess,sys,time,uuid,hashlib
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-CONVERSATION-20261030-01/R1'
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from group_ledger import FeishuLedgerPort
private=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((private/'config.json').read_text());cfg=Config.load(Path(settings['poc_config']));api=Feishu(cfg)
port=FeishuLedgerPort(api.client,app_id=cfg.app_id,tenant_key=cfg.tenant_key,bot_open_id=cfg.bot_open_id,department_root_id=settings['group_ledger']['department_root_id'],disclosure=settings['group_ledger']['disclosure'])
db=sqlite3.connect(cfg.db);db.row_factory=sqlite3.Row
chat=db.execute("SELECT chat FROM am_inbox WHERE user=? AND chat_type='p2p' ORDER BY created DESC LIMIT 1",(cfg.owner,)).fetchone()[0]
receipt_folder=private/'validation/am-conversation-r1';out=TASK/'evidence/live-business.json'
assert not out.exists(),'Existing live test must be reviewed before another run'
report={'started_at':time.time(),'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'owner_private_only':True,'synthetic_content_only':True,'turns':[],'checks':{}}
def save():out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
def wait(fn,seconds=160):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  value=fn()
  if value:return value
  time.sleep(.5)
 raise RuntimeError('LIVE_RESULT_WAIT_EXPIRED')
def send(text,label,preview=False):
 key='am-r1-live-'+uuid.uuid4().hex
 run=subprocess.run([str(Path.home()/'.local/bin/lark-cli'),'im','+messages-send','--chat-id',chat,'--as','user','--msg-type','text','--content',json.dumps({'text':text},ensure_ascii=False),'--idempotency-key',key],capture_output=True,text=True)
 raw=json.loads(run.stdout);assert run.returncode==0 and raw['ok']
 f=receipt_folder/(key+'.json');f.write_text(run.stdout);f.chmod(0o600)
 mid=raw['data']['message_id']
 def result():
  row=db.execute('SELECT * FROM am_inbox WHERE id=?',(mid,)).fetchone()
  if row and row['state']=='failed':raise RuntimeError('LIVE_REQUEST_FAILED:'+str(row['error']))
  o=db.execute("SELECT c.reply,c.state presentation_state,c.verified_at,o.* FROM am_conversation_outputs c JOIN outbox o ON o.id=c.outbox_id WHERE c.event_id=? AND o.state='sent'",(mid,)).fetchone()
  if o and (not preview or o['verified_at']):return dict(o)
 row=wait(result);reply=json.loads(row['reply']);assert reply['status'] not in ('context_limit','failed','tool_limit')
 row['_query_readback_guard']=lambda:port.authorize_private_user(cfg.owner) is not False and row['expires']>time.time()
 verified=api.verify_text(row['message_id'],row);assert verified
 timing=db.execute('SELECT received,actionable FROM am_request_timings WHERE event_id=?',(mid,)).fetchone()
 record={'case':label,'reply_status':reply['status'],'reply_chars':len(row['body']),'exact_text_readback':verified,'preview_readback_before_confirmation':bool(row['verified_at']) if preview else None,
   'publication_seconds':round(timing['actionable']-timing['received'],4) if timing and timing['actionable'] else None}
 report['turns'].append(record);save();print(json.dumps(record),flush=True)
 return row,reply
plan_id=None
try:
 body='AM-R1 合成发送验证，不是业务通知。'
 row,reply=send('请向我本人私聊发送：'+body,'send_preview',True)
 assert body in row['body'] and '本人 AM 私聊' in row['body'] and reply['status']=='needs_confirmation'
 send('确认第1项','send_confirm')
 sent=db.execute('SELECT * FROM am_conversation_sends WHERE started>=?',(report['started_at'],)).fetchall()
 assert len(sent)==1 and sent[0]['state']=='verified';report['checks']['one_actual_self_message_verified']=True
 send('按这个发','repeat_confirmation')
 assert db.execute('SELECT count(*) FROM am_conversation_sends WHERE started>=?',(report['started_at'],)).fetchone()[0]==1
 report['checks']['repeat_did_not_resend']=True
 at=(datetime.now(ZoneInfo('Asia/Shanghai'))+timedelta(minutes=3)).replace(second=0,microsecond=0)
 reminder='AM-R1 合成定时提醒验证，不是业务催办。'
 row,reply=send('请在北京时间'+at.strftime('%Y-%m-%d %H:%M')+'提醒我：'+reminder+'只提醒一次，发给我本人。','reminder_preview',True)
 assert reminder in row['body'] and '本人 AM 私聊' in row['body'] and reply['status']=='needs_confirmation'
 send('确认第1项','reminder_confirm')
 plans=db.execute('SELECT * FROM reminder_plans WHERE created>=?',(report['started_at'],)).fetchall();assert len(plans)==1
 plan=dict(plans[0]);plan_id=plan['id'];target=json.loads(plan['target'])
 assert target['kind']=='owner' and target['user']==cfg.owner and abs(plan['next_at']-at.timestamp())<1
 def occurrence():
  row=db.execute("SELECT * FROM reminder_occurrences WHERE plan_id=? AND state='sent' AND readback_state='verified'",(plan_id,)).fetchone()
  return dict(row) if row else None
 occ=wait(occurrence,max(1,at.timestamp()-time.time())+90)
 payload=json.loads(occ['payload']);assert reminder in payload['body']
 probe={'body':payload['body'],'kind':'text','chat':chat,'_query_readback_guard':lambda:port.authorize_private_user(cfg.owner) is not False}
 assert api.verify_text(occ['message_id'],probe)
 report['checks']['one_actual_timer_message_verified']=True
 report['checks']['timer_lateness_seconds']=round(json.loads(occ['receipt'])['sent_at']-at.timestamp(),3)
 send('取消刚才的合成定时提醒。','reminder_cancel')
 assert db.execute('SELECT state FROM reminder_plans WHERE id=?',(plan_id,)).fetchone()[0]=='cancelled'
 report['checks']['test_plan_cancelled']=True
 assert db.execute('SELECT count(*) FROM reminder_occurrences WHERE plan_id=?',(plan_id,)).fetchone()[0]==1
 report['checks']['one_occurrence_only']=True
 report['checks']['ledger_write_attempts']=db.execute('SELECT count(*) FROM ledger_write_attempts').fetchone()[0]
 report['finished_at']=time.time();save();print(json.dumps(report['checks']),flush=True)
except Exception as exc:
 report['error']=str(exc)[:160];save();raise
finally:
 if plan_id:
  current=db.execute('SELECT * FROM reminder_plans WHERE id=?',(plan_id,)).fetchone()
  if current and current['state'] not in ('cancelled','expired'):
   from fs_agent.store import Store
   from fs_agent.action_items import ActionItems
   from fs_agent.scheduler import Scheduler
   store=Store(cfg.db)
   try:Scheduler(store,ActionItems(store,cfg.owner),cfg.owner,None).control(cfg.owner,'validation-cleanup/'+plan_id,plan_id,current['version'],'cancel')
   finally:store.close()
   report['cleanup_cancelled_test_plan']=True;save()
 port.identity_pool.shutdown(wait=True);db.close()
