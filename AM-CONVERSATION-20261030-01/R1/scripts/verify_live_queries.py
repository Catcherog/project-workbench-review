"""Independently GET actual owner/test-group replies, exporting no chat content."""
import json,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-CONVERSATION-20261030-01/R1'
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from group_ledger import FeishuLedgerPort
p=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((p/'config.json').read_text());cfg=Config.load(Path(settings['poc_config']));api=Feishu(cfg)
port=FeishuLedgerPort(api.client,app_id=cfg.app_id,tenant_key=cfg.tenant_key,bot_open_id=cfg.bot_open_id,department_root_id=settings['group_ledger']['department_root_id'],disclosure=settings['group_ledger']['disclosure'])
db=sqlite3.connect(cfg.db);db.row_factory=sqlite3.Row;results=[]
for f in sorted((p/'validation/am-conversation-r1').glob('live-query-*.json')):
 receipt=json.loads(f.read_text());mid=receipt.get('data',{}).get('message_id')
 if not mid:continue
 i=db.execute('SELECT * FROM am_inbox WHERE id=?',(mid,)).fetchone()
 if not i:continue
 assert i['user']==cfg.owner
 o=db.execute('SELECT c.reply,o.* FROM am_conversation_outputs c JOIN outbox o ON o.id=c.outbox_id WHERE c.event_id=?',(mid,)).fetchone()
 timing=db.execute('SELECT * FROM am_request_timings WHERE event_id=?',(mid,)).fetchone()
 actual_status=json.loads(o['reply']).get('status') if o else None;verified=False
 if o and o['message_id']:
  row=dict(o)
  def guard():
   port.authorize_private_user(cfg.owner)
   return row['expires']>time.time() and (row['chat_type']=='p2p' or row['chat'] in port.disclosure)
  row['_query_readback_guard']=guard;verified=api.verify_text(row['message_id'],row)
 results.append({'sequence':len(results)+1,'state':i['state'],'error':i['error'],'chat_type':i['chat_type'],'reply_status':actual_status,
   'successful_answer':i['state']=='done' and actual_status=='answered' and verified,'text_readback_verified':verified,'reply_chars':len(o['body']) if o else 0,
   'publication_seconds':round(timing['actionable']-timing['received'],4) if timing and timing['actionable'] else None,
   'stages':json.loads(timing['stages']) if timing else {}})
data={'source_commit':__import__('subprocess').check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'cases':results,'successful_answers':sum(x['successful_answer'] for x in results),'failure_notices_not_counted_as_answers':True,'client_paint_measured':False}
(TASK/'evidence/live-query-readback.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in data.items() if k!='cases'}));port.identity_pool.shutdown(wait=True)
