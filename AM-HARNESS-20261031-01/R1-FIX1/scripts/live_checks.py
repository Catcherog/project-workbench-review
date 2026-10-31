"""Owner-only real validation using the existing authenticated send/probe path.

No consumer or provider is started. Real text/IDs remain in the original private
validation directory. Export only counts, hashes, state and exact-match booleans.
"""
import argparse,hashlib,json,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-HARNESS-20261031-01/R1-FIX1'
private=Path.home()/'.local/share/local-qwen-feishu'
settings=json.loads((private/'config.json').read_text());pc=json.loads(Path(settings['poc_config']).read_text());service_root=Path(pc['service']['root_directory']);state=service_root/'state'
folder=private/'validation/am-harness-r1';probe=ROOT/'am-harness-r1/scripts/live_probe.py'
p=argparse.ArgumentParser();p.add_argument('mode',choices=('conversation','followup','cleanup-note'));p.add_argument('--prefix',required=True);args=p.parse_args()
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
          'cases':results,'real_qwen':True,'real_feishu':True,'colleague_or_group_tests':False,
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
        return {'actual_owned_qwen_request_observed':True,'previous_assistant_exact_in_prompt':
                any(m['role']=='assistant' and m['content']==prior for m in messages) if prior else None,
                'request_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
    except (OSError,ValueError,KeyError):return None

def wait(label,mid,text,prior=None):
    observation=None;end=time.monotonic()+160
    while time.monotonic()<end:
        observation=observation or model_observation(text,prior)
        inbox=rows('SELECT state,error FROM am_inbox WHERE id=?',(mid,))
        outs=rows('SELECT o.state FROM outbox o JOIN am_outbox_events e ON e.outbox_id=o.id WHERE e.event_id=?',(mid,))
        if inbox and inbox[0]['state'] not in ('received','harness_admitting','harness_queued','processing'):
            if outs and all(o['state'] in ('sent','rejected','unknown') for o in outs):break
        time.sleep(.12)
    checked=invoke('check',label,verify=True)
    stored=rows('SELECT reply,project_refs,scope FROM am_conversation_outputs WHERE event_id=?',(mid,))
    result=dict(checked,**(observation or {'actual_owned_qwen_request_observed':False,'previous_assistant_exact_in_prompt':False if prior else None}))
    result['business_reply_verified']=checked['independent_text_readback'] and bool(stored) and checked['state']=='done'
    result['project_ref_hashes']=[hashlib.sha256(p.encode()).hexdigest() for o in stored for p in json.loads(o['project_refs'])]
    results.append(result);save();print(json.dumps({k:result[k] for k in ('label','state','error','business_reply_verified','previous_assistant_exact_in_prompt','publication_seconds')}),flush=True)
    return result, (json.loads(stored[0]['reply'])['text'] if stored and 'text' in json.loads(stored[0]['reply']) else ''),stored

def query(suffix,text,prior=None):
    label=args.prefix+'-'+suffix;mid=submitted(label,text)
    return wait(label,mid,text,prior)

if args.mode=='conversation':
    a,body,_=query('first','AM Harness FIX1 自测：请用一句话回答，合成校验词“青岚三号”只是本轮测试标记，不是业务事实。')
    b,body2,_=query('next','AM Harness FIX1 续接自测：把你上一条回答展开成两句，保留那个合成校验词。',body)
    b['test_marker_returned']='青岚三号' in body2;save()
    a,_,_=query('project-a','需求75谁负责')
    b,_,pb=query('project-b','请分析需求76的进展并提出一个建议，保留当前来源的待核条件。')
    c,body3,pc=query('pronoun','那负责人呢？')
    c['follows_project_b']=bool(pb and pc and set(json.loads(pb[0]['project_refs'])) & set(json.loads(pc[0]['project_refs'])))
    c['not_stale_project_a']=bool(c['follows_project_b'] and not set(c['project_ref_hashes']) & set(a['project_ref_hashes']))
    save();print(json.dumps({'cross_project_b':c['follows_project_b'],'not_stale_a':c['not_stale_project_a']}),flush=True)
elif args.mode=='followup':
    marker='AM-HARNESS-FIX1-'+args.prefix
    created,_,_=query('create','在需求75下创建一条AM跟进事项，负责人为我本人，事项描述原样填写“'+marker+'”。这是一条跟进事项，不是工作笔记；不要设提醒或发送通知。')
    items=rows('SELECT id,version,state,paused FROM action_items WHERE description LIKE ?',('%'+marker+'%',))
    if len(items)!=1 or not created['business_reply_verified']:raise RuntimeError('EXACT_TEST_FOLLOWUP_NOT_CREATED')
    ident=items[0]['id']
    paused,_,_=query('pause','暂停需求75下这条本人自测跟进事项，事项编号 '+ident+'；先核对当前版本。')
    before=rows('SELECT version,state,paused FROM action_items WHERE id=?',(ident,))[0]
    if before['paused']!=1 or not paused['business_reply_verified']:raise RuntimeError('TEST_FOLLOWUP_NOT_PAUSED')
    label=args.prefix+'-resume';text='恢复需求75下这条本人自测跟进事项，事项编号 '+ident+'；先读取当前状态和版本再恢复。'
    mid=submitted(label,text);deadline=time.monotonic()+75;owned=False;run=None
    while time.monotonic()<deadline:
        candidates=rows('SELECT id,state FROM am_harness_runs WHERE event_id=?',(mid,))
        if candidates:
            run=candidates[0]
            if run['state'] in ('failed','unknown','succeeded','expired'):break
            if model_observation(text):owned=True;break
        time.sleep(.06)
    if not owned:raise RuntimeError('RESUME_MODEL_NOT_OBSERVED')
    control_label=args.prefix+'-stop';command='取消任务 '+run['id'];control_mid=submitted(control_label,command)
    control,_,_=wait(control_label,control_mid,command)
    deadline=time.monotonic()+145
    while time.monotonic()<deadline:
        lane=rows('SELECT state FROM am_harness_lane')[0]['state']
        if lane=='idle':break
        if lane=='quarantined':break
        time.sleep(.12)
    after=rows('SELECT version,state,paused FROM action_items WHERE id=?',(ident,))[0]
    actual=rows('SELECT state,error FROM am_harness_runs WHERE id=?',(run['id'],))[0]
    results.append({'label':label,'actual_owned_qwen_request_observed':True,'state':actual['state'],'error':actual['error'],
        'before':before,'after':after,'business_state_unchanged':before==after,'lane_state':lane,
        'reservation_count':rows('SELECT count(*) AS n FROM am_harness_reservations WHERE run_id=?',(run['id'],))[0]['n'],
        'control_independent_readback':control['independent_text_readback'],'passed':actual['state']=='cancelled' and before==after and lane=='idle'})
    save();print(json.dumps(results[-1]),flush=True)
    query('cleanup','取消需求75下这条本人自测跟进事项，事项编号 '+ident+'；不修改其他事项。')
    query('recovery','AM Harness FIX1 恢复自测：只用一句话说明计划日期和完成证据的区别。')

else:
    previous=json.loads((folder/'hfix1-f2-create.json').read_text())['message_id']
    run=rows('SELECT id,revision FROM am_harness_runs WHERE event_id=?',(previous,))[0]
    eid='harness:'+run['id']+':v'+str(run['revision'])
    with sqlite3.connect('file:'+str(state/'am-conversation-r1/conversation.sqlite3')+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        notes=[dict(n) for n in conn.execute('SELECT id,status,version FROM conversation_tasks WHERE event_id=?',(eid,))]
    if len(notes)!=1:raise RuntimeError('EXACT_TEST_NOTE_NOT_FOUND')
    note=notes[0]
    query('close','关闭需求75下本次自测产生的工作笔记，工作笔记编号 '+note['id']+'，当前版本 '+str(note['version'])+'。只结束这条测试工作笔记，不改其他事项。')
    with sqlite3.connect('file:'+str(state/'am-conversation-r1/conversation.sqlite3')+'?mode=ro',uri=True) as conn:
        after=conn.execute('SELECT status,version FROM conversation_tasks WHERE id=?',(note['id'],)).fetchone()
    results[-1]['test_note_closed']=after[0]=='closed';save();print(json.dumps({'test_note_closed':after[0]=='closed'}),flush=True)
