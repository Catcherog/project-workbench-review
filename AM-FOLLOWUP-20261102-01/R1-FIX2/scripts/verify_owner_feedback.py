"""Independent current-message proof and persisted feedback; never copy reply text."""
from pathlib import Path
import hashlib,json,sqlite3,time
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from fs_agent.reminder_feishu import ReminderPort
from fs_agent.message_text import normalize_message
from fs_agent.card_ui import card_readback_matches

T=Path(__file__).resolve().parents[1]
settings=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text());cfg=Config.load(Path(settings['poc_config']))
api=Feishu(cfg);port=ReminderPort(cfg,api.client)
previews=json.loads((T.parent/'R1-FIX1/private/owner-previews.json').read_text())
good=[r for r in previews['results'] if r['ok']];assert len(good)==1
ident=good[0]['item_id'];nonce=good[0]['nonce']
result={'read_at':time.time(),'scope':'owner self-test; not independent engineer acceptance','reply_checks':[],'raw_reply_text_exported':False}
with sqlite3.connect((cfg.root/'state/gateway.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
 db.row_factory=sqlite3.Row
 item=dict(db.execute('SELECT * FROM action_items WHERE id=?',(ident,)).fetchone())
 links=db.execute('SELECT * FROM followup_reply_links WHERE item_id=? ORDER BY created',(ident,)).fetchall()
 for link in links:
  incoming=dict(db.execute('SELECT * FROM am_inbox WHERE id=?',(link['message_id'],)).fetchone())
  o=dict(db.execute('SELECT * FROM reminder_occurrences WHERE id=?',(link['occurrence_id'],)).fetchone())
  value=json.loads(incoming['body']);m=port.read(link['message_id'])
  mentions=[dict(v,id=v['id'] if isinstance(v.get('id'),dict) else {'open_id':v.get('id','')}) for v in m.get('mentions',[])]
  normalized=normalize_message({'message_type':m['msg_type'],'content':m['content'] if isinstance(m['content'],str) else json.dumps(m['content']),
    'mentions':mentions},bot_open_id=cfg.bot_open_id,max_chars=4000).text.strip()
  exact=(m['message_id']==link['message_id'] and m['sender_id']==cfg.owner==incoming['user']==link['actor']
    and m['chat_id']==incoming['chat'] and m['parent_id']==o['message_id'] and normalized==value['text']
    and m['sender_type']=='user' and not m['deleted'] and abs(m['created_at']-incoming['created'])<=1)
  assert exact
  feedback=[dict(r) for r in db.execute('SELECT * FROM item_feedback WHERE item_id=?',(ident,)) if json.loads(r['source']).get('message_id')==link['message_id']]
  assert len(feedback)==1
  f=feedback[0];raw=db.execute('SELECT * FROM item_feedback_raw WHERE feedback_id=?',(f['id'],)).fetchone()
  operation=db.execute('SELECT result FROM item_operations WHERE id=?',(f['id'],)).fetchone()[0]
  check={'message_sha256':hashlib.sha256(link['message_id'].encode()).hexdigest(),'kind':link['kind'],
    'exact_current_platform_reply':exact,'inbox_state':incoming['state'],'feedback_count':len(feedback),'feedback_kind':f['kind'],
    'applied':bool(f['applied']),'item_not_closed':item['state']!='closed','raw_present_within_retention':bool(raw),
    'raw_expiry':raw['expires'] if raw else None,'original_message_time':m['created_at'],
    'expiry_within_original_24h':bool(raw and raw['expires']<=m['created_at']+86400+1),
    'permanent_body_is_neutral':f['body'] in ('已回应。','自报进展，待核对。'),
    'raw_body_not_in_operation_result':normalized not in operation}
  notices=[]
  for c in db.execute("SELECT c.*,o.body,o.state AS outbox_state FROM am_cards c JOIN outbox o ON o.id=c.outbox_id WHERE c.flow='ux' AND c.expires>?",(time.time(),)):
   snap=json.loads(c['snapshot'])
   if snap.get('data',{}).get('business_event')!=f['id']:continue
   if c['message_id'] and c['outbox_state']=='sent':
    actual=port.read_card(c['message_id']);content=json.loads(actual['content']) if isinstance(actual['content'],str) else actual['content']
    matched=(actual['sender_id']==cfg.bot_open_id and actual['chat_id']==incoming['chat'] and not actual['deleted'] and card_readback_matches(content,json.loads(c['body'])))
    notices.append({'exact_card_verified':matched,'message_sha256':hashlib.sha256(c['message_id'].encode()).hexdigest()})
  check['owner_notice_cards']=notices;result['reply_checks'].append(check)
 result['item_state']=item['state'];result['close_evidence_present']=bool(item['close_evidence'])
 result['distinct_confirmation_callbacks']=db.execute("SELECT count(*) FROM am_inbox WHERE kind='card' AND body LIKE ?",('%'+nonce+'%',)).fetchone()[0]
 result['confirmed_native_occurrences']=[dict(r) for r in db.execute('SELECT state,attempts,readback_state FROM reminder_occurrences WHERE item_id=?',(ident,))]
(T/'evidence/owner-feedback-readback.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
