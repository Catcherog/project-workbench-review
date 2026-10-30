"""Independent current-card/public-answer GETs; no bodies or IDs in the export."""
import json,sys,time,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-SELF-20261029-01/UX4'
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from group_ledger import FeishuLedgerPort
private=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((private/'config.json').read_text());cfg=Config.load(Path(settings['poc_config']));api=Feishu(cfg)
port=FeishuLedgerPort(api.client,app_id=cfg.app_id,tenant_key=cfg.tenant_key,bot_open_id=cfg.bot_open_id,department_root_id=settings['group_ledger']['department_root_id'],disclosure=settings['group_ledger']['disclosure'])
db=sqlite3.connect('file:'+str(cfg.db)+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
since=json.loads((TASK/'evidence/installation.json').read_text())['installed_at']
rows=db.execute("SELECT o.*,i.kind request_kind FROM outbox o JOIN am_outbox_events e ON e.outbox_id=o.id JOIN am_inbox i ON i.id=e.event_id WHERE o.created>? AND o.message_id IS NOT NULL AND o.user=? ORDER BY o.created DESC LIMIT 20",(since,cfg.owner)).fetchall()
results=[];seen=set()
for raw in rows:
 row=dict(raw)
 if row['message_id'] in seen:continue
 seen.add(row['message_id']);route=db.execute('SELECT * FROM am_group_delivery WHERE outbox_id=?',(row['id'],)).fetchone()
 def guard():
  port.authorize_private_user(cfg.owner)
  return row['expires']>time.time() and (not route or route['source_chat'] in port.disclosure)
 actual=db.execute('SELECT chat FROM am_group_private_chats WHERE outbox_id=?',(row['id'],)).fetchone()
 if actual:row['chat']=actual[0]
 row['_query_readback_guard']=guard
 ok=api.verify_card(row['message_id'],row)
 results.append({'kind':row['request_kind'],'direct_callback':row.get('error')=='CALLBACK_APPLICATION_UNKNOWN','verified':ok,'observed_at':time.time(),'request_state':row['state']})
result={'source_commit':json.loads((TASK/'evidence/installation.json').read_text())['source_commit'],'owner_only':True,'checks':results,'exact_payload_readback':True}
out=TASK/'evidence'/((sys.argv[1] if len(sys.argv)>1 else 'live-query-readback')+'.json');out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
port.identity_pool.shutdown(wait=True)
