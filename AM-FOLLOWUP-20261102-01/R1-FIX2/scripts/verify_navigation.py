"""Read actual owner navigation/callbacks and cards; no sending or callbacks."""
from pathlib import Path
import hashlib
import json
import sqlite3
import time
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from fs_agent.reminder_feishu import ReminderPort
from fs_agent.card_ui import card_readback_matches

T=Path(__file__).resolve().parents[1]
settings=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
cfg=Config.load(Path(settings['poc_config']))
api=Feishu(cfg);port=ReminderPort(cfg,api.client)
installed=json.loads((T/'evidence/installation.json').read_text())['installed_at']
sha=lambda v:hashlib.sha256(v.encode()).hexdigest()
report={'checked_at':time.time(),'since_installation':installed,'read_only':True,
        'real_followup_send_calls':0,'real_callback_injections':0,'events':[],
        'mobile_user_confirmation':'pending','independent_engineer_business':'deferred_by_user'}
with sqlite3.connect((cfg.root/'state/gateway.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    rows=db.execute('SELECT * FROM am_inbox WHERE user=? AND created>? ORDER BY created',
                    (cfg.owner,installed)).fetchall()
    for row in rows:
        page=None
        if row['kind']=='card':
            value=json.loads(row['body']).get('value',{})
            c=db.execute('SELECT snapshot FROM am_cards WHERE nonce=?',(value.get('nonce'),)).fetchone()
            if c:page=json.loads(c['snapshot']).get('actions',{}).get(value.get('action'),{}).get('page')
            if page not in ('work','item','history','item_full','followup_dashboard'):continue
        elif row['body'] not in ('我的跟进','我的跟进？','我的跟进?','我的跟进。'):continue
        entry={'event_sha256':sha(row['id']),'kind':row['kind'],'page':page,'state':row['state'],
               'error':row['error'],'platform_created':row['created'],'retention_expires':row['expires'],
               'harness_runs_for_event':db.execute('SELECT count(*) FROM am_harness_runs WHERE event_id=?',(row['id'],)).fetchone()[0]}
        timing=db.execute('SELECT * FROM am_request_timings WHERE event_id=?',(row['id'],)).fetchone()
        anchors=db.execute('SELECT * FROM am_latency_anchors WHERE event_id=?',(row['id'],)).fetchone()
        if timing:
            entry['timing']={k:timing[k] for k in timing.keys() if k not in ('event_id','stages')}
            entry['stages']=json.loads(timing['stages'])
            if timing['actionable'] is not None:entry['host_received_to_actionable_seconds']=timing['actionable']-timing['received']
        if anchors:entry['anchors']={k:anchors[k] for k in anchors.keys() if k!='event_id'}
        cards=db.execute('''SELECT c.*,o.body,o.state AS outbox_state FROM am_outbox_events e
            JOIN outbox o ON o.id=e.outbox_id JOIN am_cards c ON c.outbox_id=o.id
            WHERE e.event_id=?''',(row['id'],)).fetchall()
        entry['cards']=[]
        for card in cards:
            snap=json.loads(card['snapshot']);body=json.loads(card['body'])
            proof={'outbox_state':card['outbox_state'],'expires':card['expires'],
                   'within_original_retention':card['expires']<=row['expires'],
                   'action_pages':[a.get('page') for a in snap.get('actions',{}).values()],
                   'has_review_label':'待核对' in card['body'],'has_followup_title':'我的跟进' in card['body']}
            if card['message_id'] and card['outbox_state']=='sent':
                actual=port.read_card(card['message_id'])
                content=json.loads(actual['content']) if isinstance(actual['content'],str) else actual['content']
                proof.update(message_sha256=sha(card['message_id']),
                    exact_current_platform_card=(actual['sender_id']==cfg.bot_open_id and actual['chat_id']==row['chat']
                        and not actual['deleted'] and card_readback_matches(content,body)))
            if page=='history':
                value=json.loads(row['body'])['value'];origin=db.execute('SELECT snapshot FROM am_cards WHERE nonce=?',(value['nonce'],)).fetchone()
                action=json.loads(origin['snapshot'])['actions'][value['action']]
                raws=db.execute('''SELECT r.body,r.expires FROM item_feedback_raw r
                    JOIN item_feedback f ON f.id=r.feedback_id WHERE f.item_id=? AND r.expires>?''',
                    (action['item'],time.time())).fetchall()
                proof['feedback_raw_count']=len(raws)
                proof['all_retained_raw_visible']=all(r['body'] in card['body'] for r in raws)
                proof['expiry_within_feedback_raw']=all(card['expires']<=r['expires'] for r in raws)
            entry['cards'].append(proof)
        report['events'].append(entry)
    report['new_native_sends_since_install']=db.execute('SELECT count(*) FROM reminder_occurrences WHERE send_started>?',(installed,)).fetchone()[0]
    report['new_intents_since_install']=db.execute('SELECT count(*) FROM followup_intents WHERE created_at>?',(installed,)).fetchone()[0]
report['status']='real_events_observed' if report['events'] else 'awaiting_owner_navigation'
(T/'evidence/navigation-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False))
