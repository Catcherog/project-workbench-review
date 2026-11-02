"""Inspect only the approved test group's bounded reply window, without raw logs."""
from pathlib import Path
import hashlib,json,sqlite3,time
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from fs_agent.reminder_feishu import ReminderPort
from fs_agent.message_text import normalize_message
from lark_oapi.api.im.v1 import ListMessageRequest
T=Path(__file__).resolve().parents[1]
settings=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text());c=Config.load(Path(settings['poc_config']));api=Feishu(c);port=ReminderPort(c,api.client)
with sqlite3.connect((c.root/'state/gateway.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
 db.row_factory=sqlite3.Row
 o=dict(db.execute('SELECT o.* FROM reminder_occurrences o JOIN followup_adoptions a ON a.occurrence_id=o.id ORDER BY o.scheduled_at DESC LIMIT 1').fetchone())
 payload=json.loads(o['payload']);group=payload['target']['payload']['group']['id'];target=payload['target']['payload']['people'][0]['id']
 assert port.allowed(group)
 request=(ListMessageRequest.builder().container_id_type('chat').container_id(group).start_time(str(int(o['send_started'])-2)).end_time(str(int(time.time())+1)).page_size(50).build())
 data=port._data(api.client.im.v1.message.list(request));rows=[]
 for item in data.items or []:
  m=port._message(item)
  who='bot' if m['sender_id']==c.bot_open_id else 'owner' if m['sender_id']==c.owner else 'engineer' if m['sender_id']==target else 'other'
  raw=m['content'];content=json.loads(raw) if isinstance(raw,str) else raw
  text=content.get('text','') if m['msg_type']=='text' else ''
  rows.append({'message_sha256':hashlib.sha256(m['message_id'].encode()).hexdigest(),'sender_role':who,'kind':m['msg_type'],
    'exact_parent':m.get('parent_id')==o['message_id'],'exact_root':m.get('root_id')==o['message_id'],
    'has_parent':bool(m.get('parent_id')),'has_root':bool(m.get('root_id')),'mentions_bot':any(x.get('id') in (c.bot_open_id,c.app_id) for x in m.get('mentions',[])),
    'acknowledgment_text':text.strip().lower() in ('收到','好的','了解','ok'),'deleted':m['deleted'],'created_at':m['created_at'],
    'in_am_inbox':bool(db.execute('SELECT 1 FROM am_inbox WHERE id=?',(m['message_id'],)).fetchone())})
result={'read_at':time.time(),'window_start':o['send_started'],'window_complete':not data.has_more,'messages':rows,'no_message_body_saved':True}
(T/'evidence/reply-window.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
