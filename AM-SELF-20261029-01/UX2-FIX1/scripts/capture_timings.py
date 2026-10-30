"""Export only per-request durations and UI counts, never live bodies or IDs."""
import json,sqlite3,sys,time,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-SELF-20261029-01/UX2-FIX1'
p=Path.home()/'.local/share/local-qwen-feishu';cfg=json.loads((p/'config.json').read_text());pc=json.loads(Path(cfg['poc_config']).read_text());db=sqlite3.connect('file:'+str(Path(pc['service']['root_directory'])/'state/gateway.sqlite3')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
installed=json.loads((TASK/'evidence/installation.json').read_text())
rows=[]
for r in db.execute('SELECT t.*,i.state,i.error FROM am_request_timings t JOIN am_inbox i ON i.id=t.event_id ORDER BY t.received'):
 r=dict(r)
 if r['received']<installed['installed_at']:continue
 out=db.execute('SELECT o.*,v.metrics,v.interaction_id FROM am_outbox_events e JOIN outbox o ON o.id=e.outbox_id LEFT JOIN am_view_outputs v ON v.outbox_id=o.id WHERE e.event_id=? ORDER BY o.created DESC LIMIT 1',(r['event_id'],)).fetchone()
 title=json.loads(out['body'])['header']['title']['content'] if out and out['kind']=='interactive' else '无卡片结果'
 if title not in ('我的工作','项目','更多','待办与跟进','变化简报','项目操作','页面状态待核对'):title='项目栏目（脱敏）'
 m=json.loads(out['metrics']) if out and out['metrics'] else {}
 delta=lambda end,start: round(r[end]-r[start],4) if r[end] is not None and r[start] is not None else None
 rows.append({'sequence':len(rows)+1,'received':r['received'],'view':title,'state':r['state'],'error':r['error'],'model_busy':bool(r['model_busy']),'first_actionable_seconds':delta('actionable','received'),'final_verified_seconds':delta('finished','received'),'queue_seconds':delta('started','accepted'),'readback_verified':r['readback_verified'],'stages':json.loads(r['stages']),'visible_metrics':{k:v for k,v in m.items() if k not in ('origin_event','created','delivered_at','actionable_seconds')}})
values=[r['first_actionable_seconds'] for r in rows if r['first_actionable_seconds'] is not None]
result={'source_commit':installed['source_commit'],'captured_at':time.time(),'layer':'original_service_real_desktop_navigation','timing_basis':'consumer ingress to successful CREATE/PATCH receipt; final includes independent exact readback. Client paint time is not separately instrumented.','sample_count':len(rows),'median_actionable_seconds':statistics.median(values) if values else None,'range_actionable_seconds':[min(values),max(values)] if values else None,'over_3_seconds':sum(v>3 for v in values),'observations':rows,'real_business_actions':0,'new_model_calls_for_these_navigation_requests':0}
name=sys.argv[1] if len(sys.argv)>1 else 'live-navigation'
(TASK/'evidence'/f'{name}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
