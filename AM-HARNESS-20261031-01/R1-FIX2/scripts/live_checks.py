"""Owner-only real validation using the existing authenticated send/probe path.

No consumer or provider is started. Real text/IDs remain in the original private
validation directory. Export only counts, hashes, state and exact-match booleans.
"""
import argparse,hashlib,json,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-HARNESS-20261031-01/R1-FIX2'
private=Path.home()/'.local/share/local-qwen-feishu'
settings=json.loads((private/'config.json').read_text());pc=json.loads(Path(settings['poc_config']).read_text());service_root=Path(pc['service']['root_directory']);state=service_root/'state'
folder=private/'validation/am-harness-r1';probe=ROOT/'am-harness-r1/scripts/live_probe.py'
p=argparse.ArgumentParser();p.add_argument('mode',choices=('dynamic','knowledge','note'));p.add_argument('--prefix',required=True);args=p.parse_args()
output=TASK/'evidence'/('live-'+args.prefix+'.json');results=[]

def rows(sql,params=()):
    with sqlite3.connect('file:'+str(state/'gateway.sqlite3')+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row;return [dict(x) for x in c.execute(sql,params)]

def invoke(action,label,prompt=None,verify=False):
    command=[sys.executable,str(probe),action,'--label',label]
    if prompt:command+=['--prompt',prompt]
    if verify:command+=['--verify']
    r=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
    if r.returncode:raise RuntimeError('LIVE_PROBE_'+action.upper()+'_FAILED')
    return json.loads(r.stdout)

def save():
    data={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
          'scope':'original owner AM DM only','r2_mode':settings['am_conversation']['output_rewrite']['mode'],
          'cases':results,'real_qwen_observed':any(c.get('actual_owned_qwen_request_observed') for c in results),'real_feishu':True,'colleague_or_group_tests':False,
          'cloud_documents_or_mounts':False,'ledger_write':False,'updated_at':time.time()}
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def submitted(label,text):
    invoke('submit',label,text)
    return json.loads((folder/(label+'.json')).read_text())['message_id']

def model_observation(text,prior=None):
    try:
        status=json.loads((state/'model-coordinator.json').read_text())
        if status['state']!='running':return None
        request=json.loads((service_root/'tasks'/status['run_id']/'request.json').read_text())
        prompt=request.get('prompt','')
        if text not in prompt:return None
        split='当前上下文和工具目录如下（JSON数据）：\n'
        messages=json.loads(prompt.split(split,1)[1])['messages'] if split in prompt else []
        codes=[]
        for message in messages:
            if message.get('role')=='tool':
                try:value=json.loads(message['content'])
                except (ValueError,TypeError):continue
                code=value.get('code') if isinstance(value,dict) else None
                if isinstance(code,str) and __import__('re').fullmatch('[A-Z][A-Z0-9_]{0,79}',code):codes.append(code)
        return {'observed_tool_error_codes':sorted(set(codes)), 'actual_owned_qwen_request_observed':True,'previous_assistant_exact_in_prompt':
                any(m['role']=='assistant' and m['content']==prior for m in messages) if prior else None,
                'request_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
    except (OSError,ValueError,KeyError):return None

def wait(label,mid,text,prior=None):
    observation=None;tool_errors=set();end=time.monotonic()+160
    while time.monotonic()<end:
        latest=model_observation(text,prior)
        if latest:
            tool_errors.update(latest.get('observed_tool_error_codes',[]))
            observation=observation or latest
        inbox=rows('SELECT state,error FROM am_inbox WHERE id=?',(mid,))
        outs=rows('SELECT o.state FROM outbox o JOIN am_outbox_events e ON e.outbox_id=o.id WHERE e.event_id=?',(mid,))
        if inbox and inbox[0]['state'] not in ('received','harness_admitting','harness_queued','processing'):
            if outs and all(o['state'] in ('sent','rejected','unknown') for o in outs):break
        time.sleep(.12)
    checked=invoke('check',label,verify=True)
    stored=rows('SELECT reply,project_refs,scope FROM am_conversation_outputs WHERE event_id=?',(mid,))
    result=dict(checked,**(observation or {'actual_owned_qwen_request_observed':False,'previous_assistant_exact_in_prompt':False if prior else None}))
    result['observed_tool_error_codes']=sorted(tool_errors)
    result['business_reply_verified']=checked['independent_text_readback'] and bool(stored) and checked['state']=='done'
    result['project_ref_hashes']=[hashlib.sha256(p.encode()).hexdigest() for o in stored for p in json.loads(o['project_refs'])]
    results.append(result);save();print(json.dumps({k:result[k] for k in ('label','state','error','business_reply_verified','previous_assistant_exact_in_prompt','publication_seconds')}),flush=True)
    return result, (json.loads(stored[0]['reply'])['text'] if stored and 'text' in json.loads(stored[0]['reply']) else ''),stored

def query(suffix,text,prior=None):
    label=args.prefix+'-'+suffix;mid=submitted(label,text)
    return wait(label,mid,text,prior)


def event(label):
    return json.loads((folder/(label+'.json')).read_text())['message_id']


def run_for(label):
    return rows('SELECT * FROM am_harness_runs WHERE event_id=?',(event(label),))[0]


def knowledge_for(label):
    run=run_for(label);eid='harness:'+run['id']+':v'+str(run['revision'])
    with sqlite3.connect('file:'+str(state/'am-conversation-r1/knowledge.sqlite3')+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        return [dict(x) for x in db.execute("SELECT id,version,status,kind,scope FROM knowledge_records WHERE json_extract(source,'$.uri')=?",('feishu-message:'+eid,))]


def provenance(label):
    run=run_for(label);eid='harness:'+run['id']+':v'+str(run['revision'])
    saved=rows('SELECT * FROM am_harness_context_sources WHERE event_id=?',(eid,))
    out=rows('SELECT project_refs FROM am_conversation_outputs WHERE event_id=?',(event(label),))
    deps=json.loads(saved[0]['dependencies']) if saved else {}
    expiries=json.loads(saved[0]['expiries']) if saved else {}
    refs=json.loads(out[0]['project_refs']) if out else []
    run_ref=hashlib.sha256(run['id'].encode()).hexdigest()[:24]
    traces=[json.loads(line) for line in (state/'am-harness-r1/trace.jsonl').read_text().splitlines()]
    contexts=[t for t in traces if t.get('run_ref')==run_ref and t.get('phase')=='context' and t.get('event')=='span_end']
    return {'initial_context_source_count':contexts[0].get('source_count') if contexts else None,
            'project_ref_count':len(refs),'dependency_count':len(deps),'catalog_dependency_present':'ledger-catalog' in deps,
            'known_projects_fully_covered':all('ledger:'+p in deps for p in refs),
            'dependency_versions':sorted(set(deps.values())),
            'source_expiries':sorted(set(expiries.values())),
            'permission_fingerprint':saved[0]['permission'] if saved else None,
            'dependencies_use_original_ttl':bool(saved and expiries and max(expiries.values())<=run['expires_at'])}


if args.mode=='dynamic':
    first,body,_=query('read','AM Harness FIX2 动态取数自测：请先调用 list_projects 列出项目目录，再用 read_project 读取目录中第一个可访问项目，用一句话概括当前记录，保留待核条件。末尾附合成校验词“青舟二号”，它仅是本次测试标记。')
    first['provenance']=provenance(args.prefix+'-read');save()
    second,_,_=query('follow','AM Harness FIX2 续接自测：请展开你上一条回答中的判断依据，不要把计划说成完成。',body)
    second['provenance']=provenance(args.prefix+'-follow');save()
    # Use the original active-source refresh schedule; do not edit the ledger
    # or create a synthetic production revision. Work in other tools continues.
    deadline=time.monotonic()+65
    print(json.dumps({'phase':'waiting_for_original_source_refresh','maximum_seconds':65}),flush=True)
    while time.monotonic()<deadline:time.sleep(.5)
    third,_,_=query('refreshed','AM Harness FIX2 来源刷新后的续接自测：基于当前可用资料，说明之前那条项目回答现在还能依据什么；需要时重新读取项目。',body)
    third['provenance']=provenance(args.prefix+'-refreshed')
    third['observed_new_source_version']=bool(third['provenance']['dependency_versions'] and first['provenance']['dependency_versions'] and third['provenance']['dependency_versions']!=first['provenance']['dependency_versions'])
    third['old_answer_excluded_from_actual_prompt']=third.get('actual_owned_qwen_request_observed') and third.get('previous_assistant_exact_in_prompt') is False
    save();print(json.dumps({'phase':'dynamic_complete','first_provenance':first['provenance'],'refresh_provenance':third['provenance'],'old_answer_excluded':third['old_answer_excluded_from_actual_prompt']}),flush=True)

elif args.mode=='knowledge':
    created,_,_=query('candidate','AM Harness FIX2 本人知识链路自测：请用 propose_knowledge 建立一条待批准候选，kind=case、scope=private，内容为“AM-HARNESS-FIX2-'+args.prefix+'：这是本轮合成验证案例，仅用于核对保存、批准和取消状态，不是正式项目事实或工作规则。”现在只保存候选，不批准。')
    records=knowledge_for(args.prefix+'-candidate')
    created['candidate_count']=len(records);created['candidate_metadata']=[{k:v for k,v in r.items() if k!='id'} for r in records];save()
    if not created['business_reply_verified'] or len(records)!=1 or records[0]['status']!='candidate' or records[0]['scope']!='private':raise RuntimeError('EXACT_PRIVATE_CANDIDATE_NOT_VERIFIED')
    record=records[0]
    block_label=args.prefix+'-ordering';block_text='AM Harness FIX2 控制时序自测：请用六个完整段落、合成例子解释计划、预计、实际完成和验收的区别，保留各自前提，不操作任何业务事项。'
    block_mid=submitted(block_label,block_text);deadline=time.monotonic()+80;owned=False
    while time.monotonic()<deadline:
        if model_observation(block_text):owned=True;break
        pending=rows('SELECT state FROM am_harness_runs WHERE event_id=?',(block_mid,))
        if pending and pending[0]['state'] not in ('queued','running'):break
        time.sleep(.08)
    if not owned:raise RuntimeError('ORDERING_MODEL_NOT_OBSERVED')
    approval_label=args.prefix+'-approve-cancel';approval_text='批准知识 '+record['id']+' v'+str(record['version']);mid=submitted(approval_label,approval_text)
    deadline=time.monotonic()+35;queued=None
    while time.monotonic()<deadline:
        matches=rows('SELECT id,state FROM am_harness_runs WHERE event_id=?',(mid,))
        if matches:queued=matches[0];break
        time.sleep(.08)
    if queued is None:raise RuntimeError('APPROVAL_ADMISSION_NOT_OBSERVED')
    if queued['state']=='queued':
        label=args.prefix+'-stop';command='取消任务 '+queued['id'];control=submitted(label,command);wait(label,control,command)
    wait(block_label,block_mid,block_text)
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if rows('SELECT state FROM am_harness_lane')[0]['state']=='idle':break
        time.sleep(.1)
    actual=knowledge_for(args.prefix+'-candidate')[0]
    run=rows('SELECT state,error FROM am_harness_runs WHERE id=?',(queued['id'],))[0]
    item={'label':approval_label,'state_at_control_admission':queued['state'],'run':run,'knowledge_status_after_stop':actual['status'],
          'local_database_reservations':rows("SELECT state,kind FROM am_harness_reservations WHERE run_id=? AND kind='local_database'",(queued['id'],)),
          'candidate_preserved_when_cancel_preceded_dispatch':run['state']=='cancelled' and actual['status']=='candidate',
          'lane_state':rows('SELECT state FROM am_harness_lane')[0]['state']}
    results.append(item);save();print(json.dumps(item),flush=True)
    if actual['status']=='candidate':
        approved,_,_=query('approve','批准知识 '+record['id']+' v'+str(record['version']))
        actual=knowledge_for(args.prefix+'-candidate')[0];approved['approved_private_case_verified']=actual['status']=='approved' and actual['scope']=='private';approved['knowledge_status']=actual['status'];save()
        print(json.dumps({'approved_private_case_verified':approved['approved_private_case_verified']}),flush=True)

else:
    previous=json.loads((folder/'hfix1-f2-create.json').read_text())['message_id']
    old=rows('SELECT id,revision FROM am_harness_runs WHERE event_id=?',(previous,))
    if len(old)!=1:raise RuntimeError('ORIGINAL_TEST_NOTE_EVENT_UNAVAILABLE')
    eid='harness:'+old[0]['id']+':v'+str(old[0]['revision'])
    with sqlite3.connect('file:'+str(state/'am-conversation-r1/conversation.sqlite3')+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;notes=[dict(n) for n in db.execute('SELECT id,status,version FROM conversation_tasks WHERE event_id=?',(eid,))]
    if len(notes)!=1:raise RuntimeError('EXACT_ORIGINAL_TEST_NOTE_NOT_FOUND')
    note=notes[0]
    checked,_,_=query('close','AM Harness FIX2 原测试笔记的准确参数清理：请调用 update_work_note，task_id='+note['id']+'，expected_version='+str(note['version'])+'，status=closed。请提交这个有版本条件的操作，由原服务执行当前来源、权限和版本校验；若被拒绝，明确保留错误原因，不改变校验，不直接改库，也不改其他事项。')
    with sqlite3.connect('file:'+str(state/'am-conversation-r1/conversation.sqlite3')+'?mode=ro',uri=True) as db:
        after=db.execute('SELECT status,version FROM conversation_tasks WHERE id=?',(note['id'],)).fetchone()
    checked['note_before']={k:v for k,v in note.items() if k!='id'};checked['note_after']={'status':after[0],'version':after[1]};checked['test_note_closed']=after[0]=='closed';save();print(json.dumps({'note_closed':checked['test_note_closed'],'note_after':checked['note_after']}),flush=True)
