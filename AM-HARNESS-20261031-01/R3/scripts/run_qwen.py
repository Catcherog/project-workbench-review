"""Frozen synthetic expression calls through the ORIGINAL consumer's probe queue."""
from pathlib import Path
import hashlib,json,os,sys,time,uuid
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1]
sys.path.insert(0,str(ROOT/'am-conversation-r1/src'))
from am_style.contracts import SpeechFrame,StylePolicy,ModelRequest,canonical,digest,ModelResult
from am_style.prompt import build_messages,RESPONSE_SCHEMA
from am_style.render import render_canonical
from am_style.verify import BoundedVerifier,parse_candidate

policy=StylePolicy(realization='free')
cases_path=TASK/'input/frozen-comparison.json'
if not cases_path.exists():
    cases=[json.loads(s) for s in (TASK/'input/AM-HARNESS-20261031-01_R3/data/generated/comparison-cases.jsonl').read_text().splitlines() if s.strip()]
    for c in cases:
        c['frame']['expires_at']=time.time()+86400
    cases_path.write_text(json.dumps({'cases':cases,'policy':policy.as_dict(),'arms':['legacy','host_canonical','qwen','codex'],
        'legacy_boundary':'No matching historical legacy response exists for these new frozen outcomes; unavailable stays in denominator.',
        'business_execution':'fictional frozen host outcomes; no real business effects or messages'},ensure_ascii=False,indent=2)+'\n')
frozen=json.loads(cases_path.read_text());cases=frozen['cases']
cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text());poc=json.loads(Path(cfg['poc_config']).read_text())
queue=Path(poc['service']['root_directory'])/'state/am-conversation-r2'
out=TASK/'private/qwen-comparison';out.mkdir(exist_ok=True)
stopped=False
for i,case in enumerate(cases):
    record=out/(str(i+1).zfill(2)+'.json')
    if record.exists():raise RuntimeError('DO_NOT_REPLAY_EXISTING_BATCH')
    frame=SpeechFrame.freeze(case['frame']);messages=build_messages(frame,policy)
    request=ModelRequest(canonical(messages),frame.fingerprint,digest(policy.as_dict()),90,650)
    common={'case_id':case['case_id'],'frame_sha256':frame.fingerprint,'prompt_sha256':digest(messages),
        'policy_sha256':digest(policy.as_dict()),'eligible':True,'attempted':False,'adopted':False,
        'delivered':False,'human_review':None,'delivery':'none','naturalness':'not_evaluated'}
    rows=[dict(common,arm='legacy',status='unavailable',reason='No matching historical legacy response to this frozen outcome',candidate_text=None),
          dict(common,arm='host_canonical',status='deterministic',candidate_text=render_canonical(frame),schema_pass=True,semantic_pass=True)]
    row=dict(common,arm='qwen',status='skipped_stop_unconfirmed',candidate_text=None)
    if not stopped:
        label='r3-'+uuid.uuid4().hex
        job={'operation':'task_model_probe','case':'SYN-QRY-01','expires_at':time.time()+150,
             'model_request':{'prompt':canonical({'messages':messages,'tools':[]}), 'json_schema':RESPONSE_SCHEMA,'max_tokens':650,'timeout':90}}
        capsule={'case_id':case['case_id'],'label':label,'request':job,'frame':frame.data,'policy':policy.as_dict()}
        (out/(str(i+1).zfill(2)+'-request.json')).write_text(json.dumps(capsule,ensure_ascii=False,indent=2))
        target=queue/'requests'/(label+'.json');temp=target.with_suffix('.tmp')
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(canonical(job))
        temp.replace(target);start=time.monotonic();row.update(attempted=True,label=label)
        result_path=queue/'results'/(label+'.json')
        while time.monotonic()-start<140 and not result_path.exists():time.sleep(.2)
        if result_path.exists():
            result=json.loads(result_path.read_text());row['coordinator_record']=result
            row['duration_ms']=(time.monotonic()-start)*1000
            if result.get('ok'):
                candidate=parse_candidate(result['text']);row.update(status='completed',raw_text=result['text'],candidate_text=candidate,
                    model=result['model'],model_digest=result['model_digest'],provider='original-coordinator',schema_pass=candidate is not None)
                if candidate is not None:
                    v=BoundedVerifier().verify(frame,candidate,policy)
                    row.update(semantic_pass=v.decision=='pass',bounded_decision=v.decision,bounded_reason=v.reason)
            else:
                row.update(status='failed',error=result.get('error'))
                if result.get('error') in ('STOP_UNKNOWN','MODEL_PAUSED'):
                    stopped=True;row['status']='stop_unconfirmed'
        else:
            stopped=True;row.update(status='stop_unconfirmed',error='ORIGINAL_CONSUMER_RESULT_MISSING',duration_ms=(time.monotonic()-start)*1000)
    rows.append(row);record.write_text(json.dumps({'rows':rows},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'index':i+1,'case':case['case_id'],'status':row['status'],'candidate':row.get('candidate_text'),'ms':row.get('duration_ms')},ensure_ascii=False),flush=True)
print('BATCH_FINISHED',flush=True)
