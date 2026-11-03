"""Read original runtime and exact platform messages, never send or approve."""
from pathlib import Path
import hashlib,json,sqlite3,time
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from fs_agent.reminder_feishu import ReminderPort

T=Path(__file__).resolve().parents[1]
settings=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
cfg=Config.load(Path(settings['poc_config']))
api=Feishu(cfg);port=ReminderPort(cfg,api.client)
since=json.loads((T/'evidence/installation.json').read_text())['installed_at']
hash_text=lambda v:hashlib.sha256(str(v).encode()).hexdigest()
private=[];report={'read_at':time.time(),'platform_operations':'read_only','new_send_calls':0,'events':[],
    'phone_acceptance':'not_accepted_user_requested_natural_language','independent_business':'deferred_by_user'}
dbpath=cfg.root/'state/gateway.sqlite3'
with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    events=db.execute('SELECT * FROM am_inbox WHERE user=? AND created>? ORDER BY created',(cfg.owner,since)).fetchall()
    for raw in events:
        row=dict(raw)
        # Scope: these are explicitly requested R6 owner test messages only.
        if not (row['body']=='我的跟进' or '哪些事情' in row['body'] or '现在有哪些跟进' in row['body'] or '本人联调' in row['body'] or '原话' in row['body']):continue
        entry={'input_sha256':hash_text(row['body']),'event_sha256':hash_text(row['id']),'kind':row['kind'],
               'state':row['state'],'error':row['error'],'created':row['created'],'outputs':[]}
        outputs=db.execute('''SELECT DISTINCT o.* FROM outbox o WHERE o.id IN
            (SELECT outbox_id FROM am_conversation_outputs WHERE event_id=?
             UNION SELECT outbox_id FROM am_outbox_events WHERE event_id=?
             UNION SELECT h.outbox_id FROM am_harness_outbox h JOIN am_harness_runs r ON r.id=h.run_id WHERE r.event_id=?)''',
             (row['id'],row['id'],row['id'])).fetchall()
        for output in outputs:
            o=dict(output);proof={'outbox_sha256':hash_text(o['id']),'kind':o['kind'],'state':o['state'],'error':o['error'],
                'body_sha256':hash_text(o['body']),'chars':len(o['body'] or ''),'contains_test_label':'测试' in (o['body'] or ''),
                'command_menu_present':any(t in (o['body'] or '') for t in ('查看跟进 1','跟进反馈 1','切换分区','确认发送 '))}
            if o['message_id'] and o['state']=='sent':
                m=port.read(o['message_id']);content=json.loads(m['content']) if isinstance(m['content'],str) else m['content']
                proof['exact_platform_readback']=(m['message_id']==o['message_id'] and m['sender_id']==cfg.bot_open_id
                    and m['chat_id']==o['chat'] and not m['deleted'] and m['msg_type']=='text' and content=={'text':o['body']})
                proof['message_sha256']=hash_text(o['message_id'])
                private.append({'inbox':row,'outbox':o,'platform':m})
            entry['outputs'].append(proof)
        report['events'].append(entry)
    previews=db.execute('''SELECT t.*,c.message_id,c.object_id,o.state,o.body AS sent_body,o.kind FROM am_followup_text_actions t
        JOIN am_cards c ON c.nonce=t.nonce JOIN outbox o ON o.id=t.outbox_id WHERE t.created>?''',(since,)).fetchall()
    report['previews']=[]
    for row in previews:
        p=dict(row);proof={'state':p['state'],'type':p['kind'],'expires':p['expires'],'superseded':p['superseded'],
            'approved_intents':db.execute('SELECT count(*) FROM followup_intents WHERE preview_id=?',(p['object_id'],)).fetchone()[0],
            'command_menu_present':any(t in (p['sent_body'] or '') for t in ('确认发送 ','取消发送 ','修改跟进 1'))}
        if p['expires']<=time.time():proof['current_content_expired']=True
        if p['message_id'] and p['state']=='sent' and p['sent_body']:
            m=port.read(p['message_id']);c=json.loads(m['content']) if isinstance(m['content'],str) else m['content']
            proof['exact_platform_readback']=(m['chat_id']==p['chat'] and m['sender_id']==cfg.bot_open_id
                and m['msg_type']=='text' and not m['deleted'] and c=={'text':p['sent_body']})
            private.append({'preview':p,'platform':m})
        report['previews'].append(proof)
(T/'private/live-followup-originals.json').write_text(json.dumps(private,ensure_ascii=False,indent=2)+'\n')
(T/'evidence/live-followup-readback.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'events':len(report['events']),'sent_outputs':sum(o['state']=='sent' for e in report['events'] for o in e['outputs']),
                  'previews':report['previews']},ensure_ascii=False))
