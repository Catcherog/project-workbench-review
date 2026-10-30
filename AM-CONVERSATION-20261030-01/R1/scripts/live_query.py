"""Send only owner-authorized read-only test prompts; private receipts stay local."""
import json,sys,subprocess,sqlite3,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
private=Path.home()/'.local/share/local-qwen-feishu'
settings=json.loads((private/'config.json').read_text());pc=json.loads(Path(settings['poc_config']).read_text())
db=sqlite3.connect('file:'+str(Path(pc['service']['root_directory'])/'state/gateway.sqlite3')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
mode=sys.argv[1];text=sys.argv[2];owner=pc['feishu']['owner_notification_open_id']
if mode.startswith('group'):
 groups=list(settings['group_ledger']['disclosure']);assert len(groups)==1
 chat=groups[0];body='<at user_id="'+pc['feishu']['bot_open_id']+'">AM</at> '+text
else:
 row=db.execute("SELECT chat FROM am_inbox WHERE user=? AND chat_type='p2p' AND chat LIKE 'oc_%' ORDER BY created DESC LIMIT 1",(owner,)).fetchone()
 assert row;chat=row['chat'];body=text
operation=['+messages-send','--chat-id',chat]
if mode=='group_quote':
 ref=db.execute('SELECT message_id FROM am_group_refs WHERE chat=? AND expires>? ORDER BY rowid DESC LIMIT 1',(chat,time.time())).fetchone();assert ref
 operation=['+messages-reply','--message-id',ref[0]]
run=subprocess.run([str(Path.home()/'.local/bin/lark-cli'),'im',*operation,'--as','user','--msg-type','text','--content',json.dumps({'text':body},ensure_ascii=False),'--idempotency-key','conversation-r1-'+uuid.uuid4().hex],capture_output=True,text=True)
folder=private/'validation/am-conversation-r1';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
path=folder/('live-query-'+str(int(time.time()))+'.json');path.write_text(run.stdout);path.chmod(0o600)
try:
 result=json.loads(run.stdout)
 print(json.dumps({'exit_code':run.returncode,'mode':mode,'result_keys':list(result),'error':result.get('error'),'code':result.get('code'),'receipt_saved_privately':True},ensure_ascii=False))
except ValueError:print(json.dumps({'exit_code':run.returncode,'result_json':False,'stderr':run.stderr[:200]}))
