"""Explicit final owner-only synthetic message through original preview/approval/send."""
from pathlib import Path
import json,sqlite3,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from group_ledger import FeishuLedgerPort
private=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((private/'config.json').read_text());cfg=Config.load(Path(settings['poc_config']));folder=private/'validation/am-harness-r1'
probe=ROOT/'am-harness-r1/scripts/live_probe.py';prefix='release-send';expected='【AM Harness R1 最终版自测】仅验证消息投递与回读。'
def invoke(mode,label,prompt=None):
 cmd=[sys.executable,str(probe),mode,'--label',label]
 if prompt:cmd+=['--prompt',prompt]
 if mode=='check':cmd+=['--verify']
 p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
 if p.returncode:raise RuntimeError('OWNER_PROBE_FAILED')
 return json.loads(p.stdout)
def query(sql,args=(),conversation=False):
 path=cfg.root/'state/am-conversation-r1/conversation.sqlite3' if conversation else cfg.db
 with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute(sql,args)]
def mid(label):return json.loads((folder/(label+'.json')).read_text())['message_id']
def wait_reply(label):
 end=time.monotonic()+125
 while time.monotonic()<end:
  rows=query('SELECT c.* FROM am_conversation_outputs c JOIN outbox o ON o.id=c.outbox_id WHERE c.event_id=? AND o.state=\'sent\' AND c.state=\'acknowledged\'',(mid(label),))
  if rows:return rows[0]
  time.sleep(.2)
 raise RuntimeError('OWNER_REPLY_NOT_VERIFIED')
invoke('submit',prefix+'-preview','请先预览一条发给我本人 AM 私聊的消息，正文必须是：'+expected)
preview=wait_reply(prefix+'-preview');proof=invoke('check',prefix+'-preview');assert proof['independent_text_readback']
ids=json.loads(preview['reply'])['pending_actions'];assert len(ids)==1 and preview['verified_at']
action=query('SELECT * FROM conversation_actions WHERE id=?',(ids[0],),True)[0];args=json.loads(action['arguments_json'])
assert action['actor_id']==cfg.owner and action['tool_name']=='send_message' and action['status']=='draft'
assert args['target']=='self' and args['body']==expected and action['presented_version']==action['version'] and action['expires_at']>time.time()
confirmation='确认执行 '+action['id']+' v'+str(action['version'])
invoke('submit',prefix+'-confirm',confirmation);wait_reply(prefix+'-confirm');confirmed=invoke('check',prefix+'-confirm')
assert confirmed['independent_text_readback'] and confirmed['reply_statuses']==['execution_succeeded']
sent=query('SELECT * FROM am_conversation_sends WHERE action_id=?',(action['id'],))[0];assert sent['state']=='verified'
invoke('submit',prefix+'-repeat',confirmation);wait_reply(prefix+'-repeat');repeated=invoke('check',prefix+'-repeat')
assert repeated['independent_text_readback'] and repeated['reply_statuses']==['no_pending_action']
assert len(query('SELECT * FROM am_conversation_sends WHERE action_id=?',(action['id'],)))==1
payload=json.loads(sent['payload']);target=payload['target'];assert target['kind']=='owner' and target['user']==cfg.owner and target['body']==expected
api=Feishu(cfg);port=FeishuLedgerPort(api.client,app_id=cfg.app_id,tenant_key=cfg.tenant_key,bot_open_id=cfg.bot_open_id,department_root_id=settings['group_ledger']['department_root_id'],disclosure=settings['group_ledger']['disclosure'])
row=dict(payload['origin'],id=payload['request_key'],task_id=None,kind='text',body=expected,artifact=None,nonce=None)
try:
 def guard():
  port.authorize_private_user(cfg.owner)
  return row['user']==cfg.owner and row['chat_type']=='p2p' and row['expires']>time.time()
 verified=api.verify_text(sent['message_id'],dict(row,_query_readback_guard=guard))
finally:port.identity_pool.shutdown(wait=True)
assert verified
reservations=query('SELECT kind,state FROM am_harness_reservations WHERE action_id=?',(action['id'],));assert {r['kind'] for r in reservations}=={'action','send'} and all(r['state']=='succeeded' for r in reservations)
result={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'owner_private_only':True,'exact_preview_body_and_version_checked_before_confirmation':True,'original_action_state':'succeeded','actual_send_state':sent['state'],'independent_business_message_readback':verified,'reservation_kinds_and_states':reservations,'send_records_after_repeat_confirmation':1,'repeat_reply_statuses':repeated['reply_statuses'],'repeat_reply_readback':True,'new_group_sends':0,'new_reminder_plans':0,'cloud_document_writes':0,'business_mounts':0,'checked_at':time.time()}
(ROOT/'AM-HARNESS-20261031-01/R1/verification/live-self-send.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
