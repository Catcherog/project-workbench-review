"""Independent original-app SDK readback; no sends and no callback fabrication."""
from pathlib import Path
import json,sqlite3,time,hashlib
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from fs_agent.reminder_feishu import ReminderPort
from fs_agent.card_ui import card_readback_matches
TASK=Path(__file__).resolve().parents[1]
config=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
c=Config.load(Path(config['poc_config']));api=Feishu(c);port=ReminderPort(c,api.client)
poc=json.loads(Path(config['poc_config']).read_text());path=Path(poc['service']['root_directory'])/'state/gateway.sqlite3'
data=json.loads((TASK/'private/live-previews.json').read_text());checks=[];private=[]
with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
 db.row_factory=sqlite3.Row
 for r in data['results']:
  if not r['ok']:checks.append({'channel':r['channel'],'status':'blocked','reason':r['error']});continue
  started=time.monotonic()
  while time.monotonic()-started<50:
   row=db.execute('SELECT c.*,o.state AS send_state,o.body,o.created FROM am_cards c JOIN outbox o ON o.id=c.outbox_id WHERE c.nonce=?',(r['nonce'],)).fetchone()
   if row and row['send_state'] not in ('pending','sending'):break
   time.sleep(.3)
  if not row or row['send_state']!='sent':
   checks.append({'channel':r['channel'],'status':'preview_delivery_unverified','outbox_state':row['send_state'] if row else 'missing'});continue
  m=port.read_card(row['message_id']);body=json.loads(row['body']);content=json.loads(m['content']) if isinstance(m['content'],str) else m['content']
  matched=(m['message_id']==row['message_id'] and m['chat_id']==row['chat'] and m['sender_id']==c.bot_open_id
    and m['sender_type'] in ('app','bot') and not m['deleted'] and card_readback_matches(content,body))
  assert matched
  private.append({'channel':r['channel'],'message':m,'nonce':row['nonce'],'item_id':r['item_id'],'expires':row['expires']})
  checks.append({'channel':r['channel'],'status':'owner_preview_readback_verified','exact_message_id':True,'exact_chat':True,
    'exact_bot':True,'exact_card_content':True,'message_id_sha256':hashlib.sha256(m['message_id'].encode()).hexdigest(),
    'preview_expires_at':row['expires'],'readback_at':time.time(),'source_kind':'synthetic_system_validation'})
 attempts=[dict(x) for x in db.execute("SELECT o.state,o.readback_state,o.attempts FROM reminder_occurrences o JOIN followup_adoptions a ON a.occurrence_id=o.id JOIN action_items i ON i.id=o.item_id WHERE i.project_ref LIKE 'validation:AM-FOLLOWUP-20261102-01:%'")]
summary={'checks':checks,'actual_native_engineer_attempts':attempts,'readback_only':True,'real_business_acceptance':False}
(TASK/'evidence/live-preview-readback.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
p=TASK/'private/live-preview-readback.json';p.write_text(json.dumps(private,ensure_ascii=False,indent=2));p.chmod(0o600)
print(json.dumps(summary,ensure_ascii=False))
