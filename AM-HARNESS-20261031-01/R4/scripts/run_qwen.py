"""Frozen synthetic expression calls through the ORIGINAL consumer's probe queue."""
from pathlib import Path
import hashlib,json,os,sys,time,uuid
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1]
sys.path.insert(0,str(TASK/'worktree/am-conversation-r1/src'))
from am_style.contracts import SpeechFrame,StylePolicy,ModelRequest,canonical,digest,ModelResult
from am_style.prompt import build_messages,RESPONSE_SCHEMA
from am_style.render import render_canonical
from am_style.verify import BoundedVerifier, CompositeVerifier, parse_candidate
from am_style.natural import NaturalSurfaceVerifier, with_natural_surfaces
from am_style.synthetic import generate_r4_projected_seeds
from am_style.prompt import coordinator_messages
from am_style.render import make_frame

policy=StylePolicy(version='muyi-style/4.0-experiment.1',realization='free')
cases_path=TASK/'input/frozen-comparison.json'
if not cases_path.exists():
    cases=[]
    for source in generate_r4_projected_seeds(policy):
        frame=with_natural_surfaces(SpeechFrame.freeze(source['frame']))
        cases.append({'case_id':source['id'],'group_id':source['group_id'],'split':source['split'],
                      'frame':frame.data,'new_development_observation':True,'human_approval_inherited':False})
    extra=[
      ('negative',[{'id':'x','kind':'progress','subject':'演示项目丙','value':'测试尚未完成'}],[],[]),
      ('estimated',[{'id':'x','kind':'date','subject':'演示项目丙完成测试','value':'2026年11月20日','modality':'estimated'}],[],[]),
      ('scope',[{'id':'x','kind':'statement','value':'仅试制阶段由林工负责；量产阶段负责人尚未确认'}],[],[]),
      ('unverified-owner',[{'id':'x','kind':'owner','subject':'演示项目丁','value':'王工','modality':'unverified'}],[],[]),
      ('missing-receipt',[],[{'id':'send','kind':'send_message','object':'通知','state':'unknown'}],[]),
      ('start-time',[],[],[{'id':'gap','slot':'start_time','object':'测试'}]),
      ('duration',[],[],[{'id':'gap','slot':'duration','object':'测试'}]),
      ('exact-preview',[],[],[]),
    ]
    for name,facts,effects,gaps in extra:
        ident='R4-BOUNDARY-'+name
        previews=[{'id':'preview','text':'待确认正文：请在 2026.11.20 前核对版本 A-2；此消息尚未发送。'}] if name=='exact-preview' else []
        frame=make_frame(binding={'turn_id':ident,'scope_id':'synthetic-r4-boundaries',
              'outcome_hash':digest({'facts':facts,'effects':effects,'gaps':gaps,'previews':previews}),
              'source_revision':'r4/1','revision':0,'cancel_epoch':0},expires_at=time.time()+86400,
              question='请说明已知结果或所缺信息。',family='query',facts=facts,effects=effects,gaps=gaps,previews=previews,policy=policy)
        cases.append({'case_id':ident,'group_id':ident,'split':'challenge','frame':with_natural_surfaces(frame).data,
                      'new_development_observation':True,'human_approval_inherited':False})
    for c in cases:c['frame']['expires_at']=time.time()+86400
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
        label='r4-'+uuid.uuid4().hex
        job={'operation':'task_model_probe','case':'SYN-QRY-01','expires_at':time.time()+150,
             'model_request':{'prompt':canonical({'messages':messages,'tools':[]}), 'json_schema':RESPONSE_SCHEMA,'max_tokens':650,'timeout':90}}
        capsule={'case_id':case['case_id'],'label':label,'request':job,'frame':frame.data,'policy':policy.as_dict(),'logical_messages':messages,'student_wire_messages':coordinator_messages(messages),'model_digest':poc['provider']['model_digest'],'enqueued_at':time.time()}
        (out/(str(i+1).zfill(2)+'-request.json')).write_text(json.dumps(capsule,ensure_ascii=False,indent=2))
        target=queue/'requests'/(label+'.json');temp=target.with_suffix('.tmp')
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(canonical(job))
        temp.replace(target);start=time.monotonic();row.update(attempted=True,label=label)
        result_path=queue/'results'/(label+'.json')
        while time.monotonic()-start<140 and not result_path.exists():time.sleep(.2)
        if result_path.exists():
            result=json.loads(result_path.read_text());row['coordinator_record']=result
            row['duration_ms']=(time.monotonic()-start)*1000;row['received_at']=time.time();row['latency_scope']='enqueue_to_result_readback';row['queue_ms']=None;row['inference_ms']=None
            if result.get('ok'):
                candidate=parse_candidate(result['text']);row.update(status='completed',raw_text=result['text'],candidate_text=candidate,
                    model=result['model'],model_digest=result['model_digest'],provider='original-coordinator',schema_pass=candidate is not None)
                if candidate is not None:
                    v=CompositeVerifier(NaturalSurfaceVerifier()).verify(frame,candidate,policy)
                    row.update(semantic_pass=v.decision=='pass',bounded_decision=v.decision,bounded_reason=v.reason)
            else:
                row.update(status='failed',error=result.get('error'))
                if result.get('error') in ('STOP_UNKNOWN','MODEL_PAUSED'):
                    stopped=True;row['status']='stop_unconfirmed'
        else:
            stopped=True;row.update(status='stop_unconfirmed',error='ORIGINAL_CONSUMER_RESULT_MISSING',duration_ms=(time.monotonic()-start)*1000)
    rows.append(row);rows.append(dict(common,arm='codex',status='blocked',reason='Actual empty tools proof and catalog/request artifacts not established',candidate_text=None));record.write_text(json.dumps({'rows':rows},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'index':i+1,'case':case['case_id'],'status':row['status'],'candidate':row.get('candidate_text'),'ms':row.get('duration_ms')},ensure_ascii=False),flush=True)
print('BATCH_FINISHED',flush=True)
