"""Body-free final-version samples, separating failures and callback evidence."""
import json,sqlite3,sys,time,math,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-SELF-20261029-01/UX4'
private=Path.home()/'.local/share/local-qwen-feishu';cfg=json.loads((private/'config.json').read_text());pc=json.loads(Path(cfg['poc_config']).read_text());root=Path(pc['service']['root_directory'])
db=sqlite3.connect('file:'+str(root/'state/gateway.sqlite3')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
installed=json.loads((TASK/'evidence/installation.json').read_text());rows=[]
model=json.loads((root/'state/model-coordinator.json').read_text());no_model=max(model.get('started',0),model.get('finished',0))<installed['installed_at']
for rr in db.execute('SELECT t.*,i.state,i.error,i.kind,i.chat_type,i.user FROM am_request_timings t JOIN am_inbox i ON i.id=t.event_id WHERE t.received>=? ORDER BY t.received',(installed['installed_at'],)):
 r=dict(rr);stages=json.loads(r['stages'])
 out=db.execute('SELECT o.*,v.metrics FROM am_outbox_events e JOIN outbox o ON o.id=e.outbox_id LEFT JOIN am_view_outputs v ON v.outbox_id=o.id WHERE e.event_id=? ORDER BY o.created DESC LIMIT 1',(r['event_id'],)).fetchone()
 anchors=db.execute('SELECT * FROM am_latency_anchors WHERE event_id=?',(r['event_id'],)).fetchone()
 direct=bool(db.execute('SELECT 1 FROM am_direct_responses WHERE event_id=?',(r['event_id'],)).fetchone())
 successful=r['state']=='done' and out is not None and out['state']=='sent'
 delta=lambda value:round(value-r['received'],4) if value is not None else None
 rows.append({'sequence':len(rows)+1,'request_kind':r['kind'],'chat_type':r['chat_type'],'actor_is_owner':r['user']==pc['feishu']['owner_notification_open_id'],
  'received':r['received'],'state':r['state'],'error':r['error'],'successful_query':successful,'delivery_state':out['state'] if out else None,
  'direct_callback':direct,'callback_response_seconds':delta(anchors['callback']) if anchors and direct else None,
  'successful_async_publish_seconds':delta(r['actionable']) if successful and not direct else None,
  'failure_notice_seconds':delta(r['actionable']) if not successful else None,
  'client_paint_seconds':None,'next_nonce_observation_seconds':delta(anchors['client']) if anchors and direct else None,
  'anchors_from_ingress_seconds':{k:delta(anchors[k]) for k in ('task_start','outbox_ready','delivery_start','callback','publish','client','verify') if anchors and anchors[k] is not None},
  'cache_condition':'source_refresh' if stages.get('remote_source',{}).get('calls') else 'identity_cold' if stages.get('remote_identity',{}).get('calls') else 'hot_snapshot' if stages.get('snapshot_hit') else 'no_source_needed',
  'remote_calls':{k:v['calls'] for k,v in stages.items() if k.startswith('remote_')},'model_dispatches':0 if no_model else None,
  'queue_to_first_start_seconds':round(r['started']-r['accepted'],4) if r['started'] is not None else None,'stages':stages})
def summary(values):
 return {'count':len(values),'range_seconds':[min(values),max(values)] if values else None,'median_seconds':statistics.median(values) if values else None,'observed_p95_seconds':sorted(values)[math.ceil(len(values)*.95)-1] if values else None,'over_3_seconds':sum(v>3 for v in values)}
result={'source_commit':installed['source_commit'],'installed_at':installed['installed_at'],'captured_at':time.time(),'layer':'real original service; owner desktop/CLI queries and any actual other-user inbound events',
 'identity_seconds':cfg['am_query']['identity_cache_seconds'],'direct_return_enabled':cfg['am_query'].get('direct_return_enabled',False),'sample_count':len(rows),'success_count':sum(r['successful_query'] for r in rows),
 'async_successful_publish':summary([r['successful_async_publish_seconds'] for r in rows if r['successful_async_publish_seconds'] is not None]),
 'direct_callback_response':summary([r['callback_response_seconds'] for r in rows if r['callback_response_seconds'] is not None]),
 'no_model_dispatch_since_install':no_model,'client_paint_measured':False,'overall_3_second_target_accepted':False,
 'timing_notes':'Failure notices are excluded from successful publication statistics. A callback response is not a platform receipt; next-nonce observation proves application but is not exact paint time. Stage totals can overlap. Cold resume preserves the first task start.',
 'observations':rows}
name=sys.argv[1] if len(sys.argv)>1 else 'final-navigation'
(TASK/'evidence'/f'{name}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='observations'},ensure_ascii=False))
