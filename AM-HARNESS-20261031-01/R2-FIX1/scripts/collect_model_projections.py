"""Read exact synthetic request snapshots; never rebind a proposal to new facts."""
from pathlib import Path
import json,hashlib,os,sys
from types import SimpleNamespace
TASK=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TASK/'worktree/am-conversation-r1/src'))
from am_conversation.model import validate_arguments,_object_pairs
from am_response.schema import compact_schema,plan_schema,expand
from am_response.semantics import SemanticAssessor
from am_outcome.types import OutcomeEnvelope,encode,fingerprint
private=Path.home()/'.local/share/local-qwen-feishu/poc/state/am-conversation-r2'
capsules=TASK/'evidence/model-request-capsules';capsules.mkdir(exist_ok=True)
result=[]
for file in sorted((TASK/'evidence/full-model').glob('*.json')):
 run=json.loads(file.read_text());prior_repair_count=0
 for record in run.get('model_calls',[]):
  label=record.get('label','')
  if not label.startswith('r2fix1-'):continue
  request=private/'requests'/(label+'.claimed')
  if not request.exists():continue
  stat=request.stat();assert stat.st_uid==os.getuid() and not stat.st_mode&0o077
  job=json.loads(request.read_text());assert job['operation']=='task_model_probe' and job['case']==run['case_id']
  capsule={'case_id':run['case_id'],'repeat':run['repeat'],'mode':run['mode'],'source_commit':run.get('source_commit'),'label':label,'operation':job['operation'],'transport_case':job['case'],'client_model_request':job['model_request'],'original_request_sha256':hashlib.sha256(request.read_bytes()).hexdigest(),'scope':'synthetic benchmark request only; provider wrapper stays the original service','business_calls_at_transport':0}
  (capsules/(label+'.json')).write_text(json.dumps(capsule,ensure_ascii=False,indent=2)+'\n')
  prompt=job['model_request']['prompt'];projection=None;call_role='indeterminate'
  try:
   payload=json.loads(prompt[prompt.index('{"messages":'):])
   repair_count=sum(m.get('role')=='system' and m.get('content','').startswith(('宿主完成检查发现','宿主执行记录显示')) for m in payload['messages'])
   call_role='task_correction' if repair_count>prior_repair_count else 'main'
   prior_repair_count=repair_count
   for m in payload['messages']:
    if m['role']=='system' and '\nhost_outcome=' in m['content']:projection=json.loads(m['content'].split('\nhost_outcome=',1)[1])
  except (ValueError,KeyError):pass
  entry={'label':label,'call_role_from_actual_prompt':call_role,'case_id':run['case_id'],'repeat':run['repeat'],'mode':run['mode'],'source_commit':run.get('source_commit'),
   'request_sha256':hashlib.sha256(request.read_bytes()).hexdigest(),'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
   'projection':projection,'schema':'not_applicable','binding':'not_applicable','coverage':'not_applicable','semantic':'not_applicable',
   'retrospective_only':True,'changes_actual_selection':False}
  try:
   value=json.loads(record.get('text',''),object_pairs_hook=_object_pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
   plan=value.get('plan') if value.get('type')=='response_plan' else None
   if plan is not None:
    entry['raw_plan']=plan;entry['schema']='reject'
    validate_arguments(plan,compact_schema() if 'snapshot' in plan else plan_schema());entry['schema']='pass'
    if projection is None:raise ValueError('original_snapshot_unavailable')
    if ('snapshot' in plan and plan['snapshot']!=projection['snapshot']) or ('envelope_fingerprint' in plan and plan['envelope_fingerprint']!=projection['outcome_hash']):
     entry['binding']='reject';raise ValueError('original_snapshot_mismatch')
    expanded=expand(plan,OutcomeEnvelope(encode(projection))) if 'snapshot' in plan else plan;entry['binding']='pass'
    claims={c['id']:c for c in projection['claims']};blocks={b['id']:b for b in projection['protected_blocks']};steps={s['id']:s for s in projection['allowed_next_steps']}
    required=[b['id'] for b in projection['protected_blocks'] if b['required']];used=set();chosen=[];parts=[]
    for segment in expanded['segments']:
     if segment['kind']=='locked':
      ident=segment['block_id'];assert ident in blocks and ident not in chosen
      chosen.append(ident);parts.append(blocks[ident]['text'])
     else:
      assert all(c in claims for c in segment['claim_ids'])
      assert segment['claim_ids'] or segment['intent'] in ('question','recommendation')
      if segment['intent'] in ('question','recommendation'):assert segment.get('next_step_ids') and all(s in steps and steps[s]['intent']==segment['intent'] for s in segment['next_step_ids'])
      used.update(segment['claim_ids']);parts.append(segment['text'])
    omitted=set(expanded['omitted_optional_claim_ids'])
    assert [x for x in chosen if x in required]==required and not used&omitted and used|omitted==set(claims)
    entry['coverage']='pass';entry['candidate_text']='\n\n'.join(parts)
    verdict=SemanticAssessor()(expanded,SimpleNamespace(data=projection));entry['semantic']=verdict['decision'];entry['semantic_details']=verdict
  except Exception as exc:
   entry['validation_error']=str(exc) or type(exc).__name__
   if entry['schema']=='pass' and entry['binding']=='pass' and entry['coverage']=='not_applicable':entry['coverage']='reject'
  result.append(entry)
(TASK/'evidence/model-input-projections.json').write_text(json.dumps({'entries':result,'scope':'only synthetic labels recorded by this fixed benchmark','no_new_hash_binding':True},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'model_requests':len(result),'snapshots':sum(x['projection'] is not None for x in result)}))
