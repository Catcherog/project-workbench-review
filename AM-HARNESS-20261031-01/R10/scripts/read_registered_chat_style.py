"""Read authorized user-bound chat histories; persist owner text only, never other senders."""
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import json,sqlite3,subprocess,time,hashlib,re
TASK=Path(__file__).resolve().parents[1]
cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
who=json.loads(subprocess.check_output(['lark-cli','whoami'],text=True));owner=who['onBehalfOf']['openId']
assert who['identity']=='user' and who['available'] and owner in cfg['allowed_open_ids']
db=Path(cfg['state_directory'])/'information/information.sqlite3'
with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as c:sources=[json.loads(x[0]) for x in c.execute('SELECT config_json FROM sources')]
sources=[s for s in sources if s['enabled'] and s['kind']=='im_chat' and s['owner_user_id']==owner and s.get('settings',{}).get('read_identity')=='existing_user']
now=int(time.time()*1000);iso=lambda ms:datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()
def read(source):
    started=time.monotonic();start=max(source['start_ms'],now-30*86400000)
    argv=['lark-cli','im','+chat-messages-list','--as','user','--chat-id',source['remote_id'],'--start',iso(start),'--end',iso(now),
        '--page-all','--page-limit','10','--page-size','50','--no-reactions']
    run=subprocess.run(argv,capture_output=True,text=True,timeout=180)
    error=None;data={};rows=[]
    try:
        reply=json.loads(run.stdout if run.stdout else run.stderr)
        if run.returncode or reply.get('ok') is not True:error=reply.get('error',{}).get('subtype','read_failed')
        else:data=reply.get('data',{})
    except ValueError:error='invalid_json'
    for item in data.get('messages',[]):
        sender=item.get('sender',{})
        if sender.get('id')!=owner or sender.get('sender_type')!='user' or item.get('deleted'):continue
        text=item.get('content');
        if not isinstance(text,str) or not text.strip():continue
        reasons=[]
        if not 8<=len(text)<=2000:reasons.append('length')
        if re.search(r'来自.*助手|Cortana|测试消息|自测|联调|Harness|run_[a-z0-9]+|action_[a-z0-9]+|^/|^https?://\S+$',text,re.I):reasons.append('automation_command_link_or_test')
        rows.append({'source_id':source['source_id'],'object_id':item['message_id'],'create_time':item.get('create_time'),
            'text':text,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'exclude_reasons':reasons,
            'authorship':'owner_sender; human_authorship_not_independently_verified',
            'raw_expires_at_ms':now+source['raw_retention_seconds']*1000})
    return rows,{'source_hash':hashlib.sha256(source['source_id'].encode()).hexdigest(),'owner_rows':len(rows),'error':error,
        'has_more':data.get('has_more'),'duration_seconds':time.monotonic()-started,'start_ms':start,'end_ms':now}
allrows=[];reports=[]
with ThreadPoolExecutor(max_workers=3) as pool:
    for rows,report in pool.map(read,sources):allrows.extend(rows);reports.append(report)
dedup={row['text_sha256']:row for row in allrows};rows=list(dedup.values())
out=TASK/'private/style';out.mkdir(mode=0o700,exist_ok=True)
summary={'sources':reports,'unique_owner_texts':len(rows),'eligible_candidates':sum(not r['exclude_reasons'] for r in rows),'business_writes':0,
    'identity':'verified_existing_user','scope':'existing_registered_chats_with_existing_date_bounds'}
for name,data in [('registered-owner-messages.json',rows),('registered-history-report.json',summary)]:
    p=out/name;p.write_text(json.dumps(data,ensure_ascii=False,indent=2));p.chmod(0o600)
print(json.dumps({k:v for k,v in summary.items() if k!='sources'}));print('failed_sources',sum(bool(r['error']) for r in reports))
