"""Independent frozen-denominator report. Driver success is not business success."""
from pathlib import Path
import json,collections,statistics,math,hashlib,re
TASK=Path(__file__).resolve().parents[1];OUT=TASK/'evidence';manifest=json.loads((TASK/'input/evaluation-manifest.json').read_text())
seeds={c['case_id']:c for c in manifest['cases']};expected={(r,c,m) for r in range(1,4) for c in seeds for m in ('legacy','enforce')}
rows={}
for p in (OUT/'full-model').glob('*.json'):
 d=json.loads(p.read_text());rows[(d['repeat'],d['case_id'],d['mode'])]=d

def pct(values,p):
 if not values:return None
 v=sorted(values);return v[min(len(v)-1,max(0,math.ceil(p*len(v))-1))]
def latency(values):return {'n':len(values),'p50_seconds':statistics.median(values) if values else None,'p95_seconds':pct(values,.95)}
def native_checks(d):
 c=d['case_id'];items=d.get('items',[]);notes=d.get('notes',[]);know=d.get('knowledge',[]);setup=d.get('setup',{});objects=setup.get('native_objects',{});checks={}
 if c=='SYN-QRY-03':checks['cancelled_body_not_published']=not any('syn-private-todo-1' in o.get('body','') for o in d.get('event_outbox',[]))
 if c=='SYN-QRY-04':checks['latest_project_focus']=any(x in (d.get('selected_text') or '') for x in ('需求76','合成星榆'))
 if c=='SYN-FUP-01':
  checks['one_followup']=len(items)==1
  if len(items)==1:
   x=items[0];checks.update(project_matches=x.get('project_ref')==setup.get('project_id'),assignee_matches='ou_engineer_a' in x.get('assignees',''),deadline_not_invented_commitment=x.get('deadline_kind')!='commitment')
 if c=='SYN-FUP-02':checks['no_ambiguous_local_write']=not items and not notes
 if c=='SYN-FUP-03':checks['cancelled_restore_not_committed']=all(x.get('paused')==1 for x in items)
 if c=='SYN-FUP-04':checks['original_item_closed_after_confirmation']=any(x['id']==objects.get('followup') and x['state']=='closed' for x in items) and len(d.get('turns',[]))==2
 if c=='SYN-NOT-01':checks['one_private_note']=len(notes)==1 and notes[0].get('project_id')==setup.get('project_id')
 if c=='SYN-NOT-02':checks['ambiguous_notes_unchanged']=len(notes)==2 and all(x['version']==1 for x in notes)
 if c=='SYN-NOT-03':checks['unknown_commit_preserved_once']=len(notes)==1 and d.get('run_result',{}).get('status')=='unknown'
 if c=='SYN-KNW-01':checks['candidate_not_approval']=len(know)==1 and know[0]['status']=='candidate' and know[0]['scope']=='private'
 if c=='SYN-KNW-03':checks['candidate_rejected']=any(x['id']==objects.get('knowledge') and x['status']=='rejected' for x in know)
 if c=='SYN-KNW-04':checks['exact_v3_private_approval']=any(x['id']==objects.get('knowledge') and x['version']==3 and x['status']=='approved' and x['scope']=='private' for x in know);checks['subsequent_query_executed']=len(d.get('turns',[]))==2
 if c in ('SYN-APR-01','SYN-OUT-01'):checks['verified_send_receipt']=any(x['state']=='verified' and x.get('message_id') for x in d.get('send_records',[]))
 if c=='SYN-APR-03':checks['pending_action_cancelled']=any(x['id']==objects.get('action') and x['status']=='cancelled' for x in d.get('actions',[]));checks['no_send']=not d.get('send_records')
 if c=='SYN-REM-02':checks['no_guessed_clock_plan']=not d.get('plans')
 if c=='SYN-REM-03':checks['prior_unknown_preserved']=any(x['state']=='unknown' for x in d.get('occurrences',[]))
 if c=='SYN-CAN-03':checks['saved_note_preserved']=len(notes)==1;checks['send_cancelled_not_sent']=not d.get('send_records') and any(x['status']=='cancelled' for x in d.get('actions',[]))
 if c=='SYN-ERR-03':checks['quarantined_provider_not_called']=not d.get('model_calls')
 return {'checks':checks,'result':'not_assessed' if not checks else 'pass' if all(checks.values()) else 'fail','covers_all_business_semantics':False}

projection_file=OUT/'model-input-projections.json'
projection_rows=json.loads(projection_file.read_text())['entries'] if projection_file.exists() else []
projections_by_label={x['label']:x for x in projection_rows}
by_family={};flat=[]
for (repeat,case,mode),d in sorted(rows.items()):
 p=d.get('presentations',[]);last=p[-1] if p else {};native=native_checks(d)
 native_file=OUT/'native-measurements'/f'{repeat}-{case}-{mode}.json'
 measured=json.loads(native_file.read_text()) if native_file.exists() else None
 native_seconds=collections.Counter();native_calls=collections.Counter()
 for event in (measured or {}).get('request_timings',[]):
  for name,metric in event['stages'].items():
   native_seconds[name]+=metric.get('seconds',0);native_calls[name]+=metric.get('calls',0)
 native_statuses=collections.Counter((r.get('reply') or {}).get('status',r['state']) for r in (measured or {}).get('conversation_results',[]))
 generated=[];tool_choices=[];tokens={'input':0,'output':0};model_started=0;provider_seconds=0;queue_seconds=0
 for record in d.get('model_calls',[]):
  model_started+=record.get('model_calls',{}).get('started',0)
  for call in record.get('model_calls',{}).get('calls',[]):
   u=call.get('usage') or {};tokens['input']+=u.get('input_tokens',0);tokens['output']+=u.get('output_tokens',0)
   provider_seconds+=call.get('provider_seconds') or 0;queue_seconds+=call.get('queue_and_setup_seconds') or 0
  try:
   value=json.loads(record.get('text',''))
   if value.get('type')=='response_plan':generated.append(value['plan'])
   if value.get('type')=='tool_calls':tool_choices.extend({'name':t['name'],'arguments':t['arguments']} for t in value.get('tool_calls',[]))
  except (ValueError,TypeError):pass
 stage=[projections_by_label[r['label']] for r in d.get('model_calls',[]) if r.get('label') in projections_by_label and projections_by_label[r['label']].get('raw_plan') is not None]
 selected=last.get('selected_source','legacy' if mode=='legacy' else 'not_prepared')
 completion=last.get('business_completion')
 if completion is None and d.get('goals'):
  states=[json.loads(x['data_json']).get('completion',x['state']) for x in d['goals']]
  completion='fulfilled' if states and all(s=='fulfilled' for s in states) else 'partial'
 verifications=d.get('independent_readbacks',[])
 item={'repeat':repeat,'case_id':case,'family':d['family'],'mode':mode,'eligible':seeds[case]['eligible_free_expression'],
  'driver_status':d['status'],'native_checks':native,'business_completion':completion or 'not_verified',
  'schema':dict(collections.Counter(x['schema'] for x in stage)),
  'binding':dict(collections.Counter(x['binding'] for x in stage)),
  'coverage':dict(collections.Counter(x['coverage'] for x in stage)),
  'semantic':dict(collections.Counter(x['semantic'] for x in stage)),
  'valid_final_candidate':any(x['schema']=='pass' and x['binding']=='pass' and x.get('raw_plan')==last.get('candidate_plan') for x in stage),
  'valid_schema_binding_candidate':any(x['schema']=='pass' and x['binding']=='pass' for x in stage),
  'raw_candidate_count':len(generated),'host_attempted':last.get('attempted',False),'host_accepted':last.get('accepted',False),
  'selected_source':selected,'free_adopted':last.get('adopted',False) and selected=='candidate','reason':last.get('reason'),
  'semantic_verdict':last.get('semantic_verdict'),'budget_exhausted':bool(native_statuses.get('budget_exhausted')) or any(x.get('dispatch_budget_exhausted') for x in p),
  'native_telemetry_available':measured is not None,'native_reply_statuses':dict(native_statuses),
  'native_stage_seconds':dict(native_seconds),'native_stage_calls':dict(native_calls),
  'native_tool_handler_calls':{k.split(':',1)[1]:v for k,v in native_calls.items() if k.startswith('conversation_tool:')},
  'original_transport_errors':[r.get('error') for r in d.get('model_calls',[]) if not r.get('ok')],
  'reply_selected':d.get('selected_text') is not None,'synthetic_reply_verified':bool(verifications) and all(v['verified'] for v in verifications),
  'real_feishu_delivery':False,'naturalness':'not_evaluated','total_seconds':d['total_seconds'],'fixture_setup_seconds':d.get('setup_seconds',0),'task_seconds':d['total_seconds'],'probe_including_setup_seconds':d['total_seconds']+d.get('setup_seconds',0),
  'input_received_epoch':d.get('input_received_epoch'),'task_terminal_epoch':d.get('task_terminal_epoch'),
  'final_prepare_ms':last.get('prepare_ms'),'pipeline_total_ms':last.get('total_ms'),
  'error':d.get('error') or (d.get('run_result') or {}).get('error'),
  'model_tool_choices':tool_choices,'model_choice_is_not_execution_proof':True,
  'adapted_outcome_operations':[u.get('operation') for batch in d.get('tool_calls',[]) for u in batch],
  'adapted_telemetry_available':bool(p),
  'task_model_attempts':sum(x.get('task_model_calls',0) for x in p) if p else None,'task_repair_attempts':sum(x.get('task_repair_calls',0) for x in p) if p else None,'presentation_calls':sum(x.get('presentation_calls',0) for x in p),
  'actual_prompt_call_roles':dict(collections.Counter(projections_by_label.get(r.get('label'),{}).get('call_role_from_actual_prompt','indeterminate') for r in d.get('model_calls',[]))),
  'provider_started':model_started,'transport_calls':len(d.get('model_calls',[])),'tokens':tokens,'provider_seconds':provider_seconds,'queue_seconds':queue_seconds}
 flat.append(item);key=d['family']+' / '+mode
 by_family.setdefault(key,[]).append(item)
summary={}
for key,items in by_family.items():
 fam,mode=key.split(' / ');expected_family=[c for c in seeds.values() if c['family']==fam]
 denominator=sum(c['eligible_free_expression'] for c in expected_family)*3
 summary[key]={'distinct_cases':len(expected_family),'planned_observations':len(expected_family)*3,'observed':len(items),
  'frozen_eligible_denominator':denominator,'generated_candidate_requests':sum(x['raw_candidate_count']>0 for x in items),
  'host_accepted':sum(x['host_accepted'] for x in items),'free_adopted':sum(x['free_adopted'] for x in items),
  'valid_final_candidate_rate':sum(x['eligible'] and x['valid_final_candidate'] for x in items)/denominator if denominator else None,
  'valid_schema_binding_rate':sum(x['eligible'] and x['valid_schema_binding_candidate'] for x in items)/denominator if denominator else None,
  'schema_stages':dict(sum((collections.Counter(x['schema']) for x in items),collections.Counter())),
  'coverage_stages':dict(sum((collections.Counter(x['coverage']) for x in items),collections.Counter())),
  'semantic_stages':dict(sum((collections.Counter(x['semantic']) for x in items),collections.Counter())),
  'candidate_rate':sum(x['eligible'] and x['raw_candidate_count']>0 for x in items)/denominator if denominator else None,
  'free_adoption_rate':sum(x['eligible'] and x['free_adopted'] for x in items)/denominator if denominator else None,
  'selected_sources':dict(collections.Counter(x['selected_source'] for x in items)),
  'business_completion':dict(collections.Counter(x['business_completion'] for x in items)),
  'independent_native_checks':dict(collections.Counter(x['native_checks']['result'] for x in items)),
  'native_telemetry_observations':sum(x['native_telemetry_available'] for x in items),
  'native_reply_statuses':dict(sum((collections.Counter(x['native_reply_statuses']) for x in items),collections.Counter())),
  'native_stage_calls':dict(sum((collections.Counter(x['native_stage_calls']) for x in items),collections.Counter())),
  'native_stage_latency':{stage:latency([x['native_stage_seconds'][stage] for x in items if stage in x['native_stage_seconds']]) for stage in sorted({stage for x in items for stage in x['native_stage_seconds']})},
  'original_transport_errors':dict(collections.Counter(error for x in items for error in x['original_transport_errors'])),
  'original_transport_error_rate':sum(bool(x['original_transport_errors']) for x in items)/len(items) if items else None,
  'synthetic_reply_verified':sum(x['synthetic_reply_verified'] for x in items),'budget_exhausted':sum(x['budget_exhausted'] for x in items),
  'final_prepare_p95_ms':pct([x['final_prepare_ms'] for x in items if x['final_prepare_ms'] is not None],.95),
  'provider_time':latency([x['provider_seconds'] for x in items]),
  'queue_time':latency([x['queue_seconds'] for x in items]),
  'actual_prompt_call_roles':dict(sum((collections.Counter(x['actual_prompt_call_roles']) for x in items),collections.Counter())),
  'token_totals':{k:sum(x['tokens'][k] for x in items) for k in ('input','output')},
  'extra_expression_calls':sum(x['presentation_calls'] for x in items),
  'task_latency':latency([x['task_seconds'] for x in items]),
  'all_observation_latency':latency([x['total_seconds'] for x in items]),
  'selected_reply_latency':latency([x['total_seconds'] for x in items if x['reply_selected']]),'naturalness':'not_evaluated'}
paired=[]
for repeat,case in sorted({(r,c) for r,c,m in rows}):
 left=rows.get((repeat,case,'legacy'));right=rows.get((repeat,case,'enforce'))
 if left is None or right is None:continue
 a,b=left['total_seconds'],right['total_seconds']
 paired.append({'repeat':repeat,'case_id':case,'family':seeds[case]['family'],'legacy_probe_seconds':left['total_seconds']+left.get('setup_seconds',0),'enforce_probe_seconds':right['total_seconds']+right.get('setup_seconds',0),'legacy_seconds':a,'enforce_seconds':b,'delta_seconds':b-a,'ratio':b/a if a else None})
paired_summary={}
for family in sorted({p['family'] for p in paired}|{'all'}):
 ps=[p for p in paired if family=='all' or p['family']==family]
 a=latency([p['legacy_seconds'] for p in ps]);b=latency([p['enforce_seconds'] for p in ps])
 ratio=b['p95_seconds']/a['p95_seconds'] if a['p95_seconds'] else None
 paired_summary[family]={'paired_observations':len(ps),'legacy':a,'enforce':b,'p95_ratio':ratio,'p95_over_10_percent':ratio>1.1 if ratio is not None else None,'median_paired_delta_seconds':statistics.median(p['delta_seconds'] for p in ps) if ps else None}
gates={}
for key,info in summary.items():
 family,mode=key.split(' / ')
 if mode!='enforce':continue
 ps=paired_summary.get(family,{})
 gates[family]={'frozen_eligible_denominator':info['frozen_eligible_denominator'],'schema_bound_final_candidate_rate':info['valid_final_candidate_rate'],'candidate_rate_at_least_90pct':info['valid_final_candidate_rate']>=.9 if info['valid_final_candidate_rate'] is not None else None,'free_adoption_rate':info['free_adoption_rate'],'adoption_at_least_85pct':info['free_adoption_rate']>=.85 if info['free_adoption_rate'] is not None else None,'paired_total_p95_ratio':ps.get('p95_ratio'),'paired_total_p95_within_10pct':not ps['p95_over_10_percent'] if ps.get('p95_over_10_percent') is not None else None,'final_prepare_p95_ms':info['final_prepare_p95_ms'],'whole_code_expression_latency_proven':False,'severe_fact_and_action_error_oracle':'bounded automated predicates only; full semantic/human check not complete','naturalness':'not_scored','allowed_to_enable':False}
all48={}
for mode in ('legacy','enforce'):
 items=[x for x in flat if x['mode']==mode]
 all48[mode]={'denominator':144,'observed':len(items),'schema_bound_final_candidates':sum(x['valid_final_candidate'] for x in items),'schema_bound_final_candidate_rate':sum(x['valid_final_candidate'] for x in items)/144,'free_adopted':sum(x['free_adopted'] for x in items),'free_adoption_rate':sum(x['free_adopted'] for x in items)/144,'note':'All 48 cases, including deterministic/suppressed cases; supplementary inclusive denominator, does not replace frozen 41-case eligibility'}
result={'model_measurement_source':json.loads((TASK/'input/evaluation-lock.json').read_text())['source_commit'],
 'planned_distinct_cases':48,'paired_repetitions':3,'planned_observations':288,'recorded_observations':len(rows),
 'missing':[{'repeat':r,'case_id':c,'mode':m} for r,c,m in sorted(expected-rows.keys())],
 'all_48_denominator':all48,'family_gates':gates,'families':summary,'paired_latency':paired_summary,'pairs':paired,'observations':flat,'notes':['Driver pass only means observed and saved.','Native hard checks are partial business predicates, not complete semantic or human acceptance.','All fixed eligible samples remain in denominators, including failures and absent candidates.','Source/protected projection, canonical, fallback and shadow are excluded from free adoption.','The driver resets its monotonic timer after fixture setup; total_seconds is already task duration. Setup time is reported separately and is not subtracted twice; epoch endpoints are retained. Synthetic platform I/O; real platform acceptance is separate.','Known fixture-contract gaps remain unverified; see input/fixture-mapping-notes.json.'],
 'production_activation':False,'activation_reason':'Per-family technical, naturalness and business acceptance not all established'}
(OUT/'model-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'observed':len(rows),'planned':288,'free_adopted':sum(x['free_adopted'] for x in flat),'missing':len(result['missing'])}))
