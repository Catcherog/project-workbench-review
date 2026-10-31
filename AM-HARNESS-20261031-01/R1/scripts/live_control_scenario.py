"""Owner-only real control/read scenario; private identities never printed."""
import json,sqlite3,subprocess,sys,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
mode=sys.argv[1]
assert mode in ('cancel','revise')
private=Path.home()/'.local/share/local-qwen-feishu'
cfg=json.loads((private/'config.json').read_text());pc=json.loads(Path(cfg['poc_config']).read_text())
service_root=Path(pc['service']['root_directory']);dbpath=service_root/'state/gateway.sqlite3'
folder=private/'validation/am-harness-r1';tag=sys.argv[2] if len(sys.argv)>2 else 'full';assert __import__('re').fullmatch('[a-z0-9-]{1,20}',tag);label=tag+'-'+mode
probe=ROOT/'am-harness-r1/scripts/live_probe.py'
def invoke(action,label,prompt=None,verify=False):
 cmd=[sys.executable,str(probe),action,'--label',label]
 if prompt:cmd+=['--prompt',prompt]
 if verify:cmd+=['--verify']
 run=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
 if run.returncode:raise RuntimeError('PROBE_FAILED_'+action)
 return json.loads(run.stdout)
def rows(sql,args=()):
 with sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True) as c:
  c.row_factory=sqlite3.Row;return [dict(x) for x in c.execute(sql,args)]
marker='AM Harness '+label+' 自测'
start=time.time();invoke('submit',label,marker+'：请用六个完整段落说明如何区分项目计划、预测和完成证据，全部使用合成例子。')
mid=json.loads((folder/(label+'.json')).read_text())['message_id']
end=time.monotonic()+50;owned=False;run=None;provider_run=None
while time.monotonic()<end:
 matches=rows('SELECT * FROM am_harness_runs WHERE event_id=?',(mid,))
 if matches:
  run=matches[0]
  if run['state'] in ('failed','unknown','expired','succeeded'):break
  coordinator=json.loads((service_root/'state/model-coordinator.json').read_text())
  if coordinator['state']=='running':
   request=service_root/'tasks'/coordinator['run_id']/'request.json'
   if request.exists():
    try:owned=marker in json.loads(request.read_text()).get('prompt','')
    except (ValueError,FileNotFoundError):owned=False
    if owned:provider_run=coordinator['run_id'];break
 time.sleep(.1)
if not owned:raise RuntimeError('MODEL_OWNERSHIP_NOT_OBSERVED_'+str(run.get('state') if run else 'missing'))
model_seen=time.time()
if mode=='cancel':
 invoke('submit',label+'-read','需求75谁负责')
 command='取消任务 '+run['id']
else:command='更正任务 '+run['id']+'：请只用一句话说明计划日期不能当作完成证据。'
invoke('submit',label+'-control',command)
control_received=time.time()
control_mid=json.loads((folder/(label+'-control.json')).read_text())['message_id']
end=time.monotonic()+145
while time.monotonic()<end:
 now=rows('SELECT state,revision,error,lease_generation FROM am_harness_runs WHERE id=?',(run['id'],))[0]
 lane=rows('SELECT state FROM am_harness_lane')[0]['state']
 wanted='cancelled' if mode=='cancel' else 'succeeded'
 if now['state']==wanted and lane=='idle':break
 if now['state'] in ('unknown','failed','expired'):break
 time.sleep(.25)
else:raise RuntimeError('SCENARIO_DEADLINE')
original=rows('SELECT count(*) AS n FROM am_conversation_outputs WHERE event_id=?',(mid,))[0]['n']
current=rows('SELECT reply,outbox_id FROM am_conversation_outputs WHERE event_id=?',(control_mid,))
delivery_end=time.monotonic()+30
while time.monotonic()<delivery_end:
 delivered=rows('SELECT o.state FROM outbox o JOIN am_outbox_events e ON e.outbox_id=o.id WHERE e.event_id=?',(control_mid,))
 required=1 if mode=='cancel' else 2
 ready=len(delivered)==required and all(r['state']=='sent' for r in delivered)
 if ready and (mode=='cancel' or current and rows('SELECT verified FROM am_harness_outbox WHERE outbox_id=?',(current[0]['outbox_id'],))[0]['verified']):break
 if any(r['state'] in ('rejected','unknown') for r in delivered):break
 time.sleep(.2)
control=invoke('check',label+'-control',verify=True)
summary={'mode':mode,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
 'actual_owned_model_observed':owned,'old_original_reply_count':original,'final_state':now['state'],
 'final_revision':now['revision'],'lane_state':lane,'error':now['error'],
 'control_received_after_model_seconds':round(control_received-model_seen,4),
 'control_readback':control['independent_text_readback'],'control_publication_seconds':control['publication_seconds'],
 'current_revision_reply_count':len(current),'old_reply_suppressed':original==0,'duration_seconds':round(time.time()-start,4)}
if mode=='cancel':
 read=invoke('check',label+'-read',verify=True);summary['independent_read']=read
 ref=hashlib.sha256(run['id'].encode()).hexdigest()[:24]
 usage=[json.loads(line) for line in (service_root/'state/am-harness-r1/trace.jsonl').read_text().splitlines() if json.loads(line).get('run_ref')==ref and json.loads(line).get('phase')=='model' and 'input_tokens' in json.loads(line)]
 timing=rows('SELECT actionable FROM am_request_timings WHERE event_id=?',(json.loads((folder/(label+'-read.json')).read_text())['message_id'],))[0]
 summary['verification_method']='durable task-bound provider completion observation'
 summary['original_model_return_observed_at']=usage[0]['time'] if usage else None
 summary['read_published_at']=timing['actionable']
 summary['read_published_before_original_model_return']=bool(timing['actionable'] and usage and timing['actionable']<usage[0]['time'])
else:
 summary['correction_engine_event_is_revision_2']=len(current)==1 and json.loads(current[0]['reply'])['event_id'].endswith(':v2')
 summary['correction_bound_to_real_control']=len(current)==1
 summary['verified_outbox']=bool(current and rows('SELECT verified FROM am_harness_outbox WHERE outbox_id=?',(current[0]['outbox_id'],))[0]['verified'])
summary['passed']=summary['old_reply_suppressed'] and summary['control_readback'] and now['state']==wanted and lane=='idle' and (mode=='cancel' and summary['read_published_before_original_model_return'] or mode=='revise' and summary['verified_outbox'] and summary['correction_engine_event_is_revision_2'])
out=ROOT/'AM-HARNESS-20261031-01/R1/verification'/('live-'+mode+'.json');out.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False))
