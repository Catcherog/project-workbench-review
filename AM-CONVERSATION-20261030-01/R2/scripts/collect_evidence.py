"""Export metadata/booleans; real questions, facts and A/B/C stay private."""
from pathlib import Path
from collections import Counter,defaultdict
import hashlib,json,math,sqlite3,time

ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-CONVERSATION-20261030-01/R2';OUT=TASK/'evidence'
PRIVATE=Path.home()/'.local/share/local-qwen-feishu'
config=json.loads((PRIVATE/'config.json').read_text());environment=json.loads(Path(config['poc_config']).read_text())
STATE=Path(environment['service']['root_directory'])/'state';R2=STATE/'am-conversation-r2'
SHA='b9b0444edf34aeb962b982fca0501dc7df7d83da'
def save(name,value):
    existing=OUT/name
    if existing.exists() and name in ('live-business-cases.json','style-comparison.json'):
        archive=OUT/'observations';archive.mkdir(exist_ok=True)
        (archive/(name.removesuffix('.json')+'-'+str(time.time_ns())+'.json')).write_bytes(existing.read_bytes())
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def pct(values,q):return sorted(values)[max(0,math.ceil(q*len(values))-1)] if values else None
probes=[json.loads(p.read_text()) for p in sorted((R2/'results').glob('final-probe-*.json'))]
durations=[v['elapsed_seconds'] for v in probes if v.get('model_calls',{}).get('completed')]
save('live-model-final.json',{'source_commit':SHA,'model_cases':len(probes),
    'counts':dict(Counter(p.get('disposition','failed') for p in probes)),
    'attempted':sum(v.get('model_calls',{}).get('attempted',0) for v in probes),
    'started':sum(v.get('model_calls',{}).get('started',0) for v in probes),
    'completed':sum(v.get('model_calls',{}).get('completed',0) for v in probes),
    'p50_seconds':pct(durations,.5),'p95_seconds':pct(durations,.95),
    'same_as_fixed':sum(v.get('candidate_after_checks')==v.get('fixed_baseline') for v in probes if v.get('candidate_after_checks')),
    'human_full_acceptance':False,'results':probes})
corpus=[json.loads(p.read_text()) for p in sorted((R2/'results').glob('final-survey-*.json'))]
counts=defaultdict(Counter)
for row in corpus:
    for case in row.get('cases',[]):counts[case['field']][case['disposition']]+=1
save('coverage-final.json',{'source_commit':SHA,'kind':'real_authorized_corpus_projection_not_repeated_user_messages',
    'denominator_per_field':23,'field_counts':{k:dict(v) for k,v in counts.items()},
    'identity_not_verified_projects':4,'projects_with_unmerged_extra_facts':18,
    'llm_acceptance_not_implied_by_contract_eligibility':True,'results':corpus})
db=sqlite3.connect('file:'+str(STATE/'gateway.sqlite3')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
conv=sqlite3.connect('file:'+str(STATE/'am-conversation-r1/conversation.sqlite3')+'?mode=ro',uri=True);conv.row_factory=sqlite3.Row
cases=[];styles=[]
for path in sorted((PRIVATE/'validation/am-harness-r1').glob('r2-*.json')):
    record=json.loads(path.read_text());ident=record['message_id']
    row=db.execute('SELECT * FROM am_inbox WHERE id=?',(ident,)).fetchone()
    if row is None:continue
    outputs=db.execute('SELECT o.* FROM outbox o JOIN am_outbox_events e ON e.outbox_id=o.id WHERE e.event_id=?',(ident,)).fetchall()
    reply=db.execute('SELECT * FROM am_conversation_outputs WHERE event_id=?',(ident,)).fetchone()
    timing=db.execute('SELECT * FROM am_request_timings WHERE event_id=?',(ident,)).fetchone()
    stages=json.loads(timing['stages']) if timing else {}
    item={'label':record['label'],'source_commit':record['source_commit'],'input_origin':record.get('origin','owner_private_cli'),
          'state':row['state'],'error':row['error'],'query_hash':digest(row['body']),
          'reply_count':len(outputs),'sent_count':sum(o['state']=='sent' for o in outputs),
          'independent_text_readback':record.get('verification',{}).get('independent_text_readback',False),
          'publication_seconds':round(timing['actionable']-timing['received'],4) if timing and timing['actionable'] else None,
          'stages':stages,'assistant_reply_present':reply is not None}
    if reply:
        value=json.loads(reply['reply'])
        if 'event_id' not in value:
            item['source_derived_record_invalidated']=True
            item['reply_event_and_history_equal']=None
            cases.append(item)
            continue
        eid=value['event_id']
        history=conv.execute("SELECT content_json FROM conversation_messages WHERE event_id=? AND role='assistant'",(eid,)).fetchall()
        event=conv.execute('SELECT reply_json FROM conversation_events WHERE event_id=?',(eid,)).fetchone()
        texts=[json.loads(h[0]) for h in history]
        item.update(reply_status=value['status'],assistant_history_count=len(history),
            reply_event_and_history_equal=bool(event and json.loads(event[0])['text']==value['text'] and texts==[value['text']]),
            rendered_equals_outbox=bool(len(outputs)==1 and reply['rendered_text']==outputs[0]['body']),
            reply_equals_rendered=value['text']==reply['rendered_text'],content_hash=digest(value['text']))
        capture=R2/'captures'/(digest(ident)+'.json')
        if capture.exists():
            c=json.loads(capture.read_text())
            styles.append({'label':record['label'],'mode':c['mode'],'disposition':c['disposition'],
                'origin':c['contract']['origin'] if c.get('contract') else None,
                'frozen_contract_fingerprint':c.get('contract_fingerprint'),
                'A_chars':len(c['before']),'B_chars':len(c['fixed_baseline'] or ''),'C_chars':len(c['candidate_after_checks'] or ''),
                'C_equals_B':c['candidate_after_checks']==c['fixed_baseline'] if c.get('candidate_after_checks') else None,
                'final_equals_A':value['text']==c['before'],'final_equals_B':value['text']==c['fixed_baseline'],
                'final_equals_C':value['text']==c['candidate_after_checks'],
                'candidate_adopted':c.get('candidate_adopted',False),'human_score':None})
    cases.append(item)
save('live-business-cases.json',{'source_commit':SHA,'cases':cases,
    'protected_production_side_effects_added_by_validation':0,
    'scope':'original owner private queries only; no colleagues, groups, approval or ledger writes'})
save('style-comparison.json',{'real_cases':styles,'all_real_abc_content_private':True,'human_quality_acceptance':False,
    'synthetic_case_preferences_in':'human-review.json','same_contract_per_ABC_triplet':True,
    'comparison_across_events_not_a_controlled_latency_experiment':True})
print(json.dumps({'probes':len(probes),'corpus':len(corpus),'live_cases':len(cases),'style_triplets':len(styles),
    'model_p50':pct(durations,.5),'model_p95':pct(durations,.95)}))
