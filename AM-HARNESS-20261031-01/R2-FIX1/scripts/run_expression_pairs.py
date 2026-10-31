"""Corrected 12-pair expression precheck using captured PRODUCTION adapters."""
from pathlib import Path
import sys,json,time,hashlib
from dataclasses import asdict
TASK=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TASK/'worktree/am-conversation-r1/src'))
from model_proxy import OriginalCoordinatorProxy
from am_conversation.model import CoordinatorModel,validate_arguments
from am_response.pipeline import ResponsePipeline
from am_response.schema import project,compact_schema,PROMPT
from am_response.semantics import PROFILE
from am_outcome.types import OutcomeEnvelope,encode
FAMILIES=['query','analysis','followup','worknote','knowledge','document','approval','sending','schedule','control','partial','unknown']
PREFIX=['QRY','ANA','FUP','NOT','KNW','DOC','APR','OUT','REM','CAN','PAR','ERR']
out=TASK/'evidence/model-pairs';out.mkdir(exist_ok=True)
for index,family in enumerate(FAMILIES):
 target=out/(family+'.json')
 if target.exists():continue
 source=TASK/'input/production-outcomes'/(family+'.json');captured=json.loads(source.read_text());e=OutcomeEnvelope(encode(captured['outcome']));data=e.data
 result={'family':family,'layer':'L2_captured_production_adapter_expression_only','question':captured['question'],
    'input_hash':hashlib.sha256(source.read_bytes()).hexdigest(),'outcome':data,'actual_business_actions':0,'actual_delivery':False,'naturalness':'not_evaluated','variants':{}}
 for variant in (('legacy','response') if index%2==0 else ('response','legacy')):
  proxy=OriginalCoordinatorProxy('SYN-'+PREFIX[index]+'-01');model=CoordinatorModel(proxy,response_protocol=variant=='response',max_tokens=1024)
  messages=[{'role':'user','content':captured['question']},{'role':'system','content':
     PROMPT+'\nhost_outcome='+encode(project(e)) if variant=='response' else '请根据以下真实工具返回的合成结果直接回答，保留所有限定和未完成事项：'+encode({'results':[u['result'] for u in data['work_units']],'claims':data['claims'],'protected_blocks':data['protected_blocks']})}]
  start=time.monotonic();entry={}
  try:
   turn=model.complete(messages,[],request_id='r2-fix1-'+family);entry['turn']=asdict(turn)
   if variant=='response':
    pipe=ResponsePipeline({'mode':'enforce','profile_version':PROFILE,'families':data['families']})
    candidate,reason=pipe.validate(turn.response_plan or {},e,6000)
    entry.update(candidate_text=candidate,validation_reason=reason,would_select_free=reason=='candidate',actual_adopted=False)
    try:validate_arguments(turn.response_plan,compact_schema());entry['schema']='pass'
    except Exception:entry['schema']='reject'
    entry['coverage']='pass' if candidate is not None or reason in ('semantic_indeterminate_or_rejected','family_unvalidated','semantic_profile_unavailable') else 'not_passed'
    entry['semantic']='pass' if reason=='candidate' else 'not_required_projection' if reason in ('protected_projection','source_projection') else reason
  except Exception as exc:entry.update(error_type=type(exc).__name__,error=str(exc),schema='not_completed')
  if entry.get('error') in ('STOP_UNKNOWN','MODEL_PAUSED','EVALUATION_MODEL_RESULT_UNKNOWN'):
   result['variants'][variant]=entry;target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');raise SystemExit('Original model requires reconciliation')
  entry.update(seconds=time.monotonic()-start,model_calls=proxy.records)
  result['variants'][variant]=entry
 target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'family':family,'legacy_seconds':result['variants']['legacy']['seconds'],'response_seconds':result['variants']['response']['seconds'],'reason':result['variants']['response'].get('validation_reason'),'error':result['variants']['response'].get('error')},ensure_ascii=False),flush=True)
