from pathlib import Path
import json,sqlite3,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-HARNESS-20261031-01/R1-FIX1';private=Path.home()/'.local/share/local-qwen-feishu'
cfg=json.loads((private/'config.json').read_text());pc=json.loads(Path(cfg['poc_config']).read_text());state=Path(pc['service']['root_directory'])/'state'
def rows(sql,args=()):
    with sqlite3.connect('file:'+str(state/'gateway.sqlite3')+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;return [dict(x) for x in db.execute(sql,args)]
items=rows("SELECT id,version,state,paused FROM action_items WHERE description LIKE '%AM-HARNESS-FIX1-hfix1-f3%'")
assert len(items)==1 and items[0]['state']=='waiting' and items[0]['paused']==1
item=items[0]
label='hfix1-item-close'
text='AM Harness FIX1 本人实测收尾：请用 change_followup 取消这条AM跟进事项，item_id='+item['id']+'，version='+str(item['version'])+'，operation=cancel。这是取消跟进事项，不是停止会话任务；不修改其他事项，也不要仅回复说明。'
probe=ROOT/'am-harness-r1/scripts/live_probe.py'
def invoke(mode,extra=()):
    p=subprocess.run([sys.executable,str(probe),mode,'--label',label,*extra],capture_output=True,text=True,cwd=ROOT)
    if p.returncode:raise RuntimeError('EXACT_CLEANUP_PROBE_FAILED')
    return json.loads(p.stdout)
invoke('submit',['--prompt',text]);mid=json.loads((private/'validation/am-harness-r1'/(label+'.json')).read_text())['message_id']
end=time.monotonic()+155
while time.monotonic()<end:
    output=rows('SELECT o.state FROM outbox o JOIN am_outbox_events e ON e.outbox_id=o.id WHERE e.event_id=?',(mid,))
    if output and all(o['state'] in ('sent','unknown','rejected') for o in output):break
    time.sleep(.2)
verified=invoke('check',['--verify'])
after=rows('SELECT version,state,paused FROM action_items WHERE id=?',(item['id'],))[0]
result={'label':label,'source_commit':verified['source_commit'],'input_kind':'explicit tool diagnostic on exact self-test item and observed version','owner_private_only':True,'before':{k:v for k,v in item.items() if k!='id'},'after':after,'item_cancelled':after['state']=='cancelled','verification':verified}
(TASK/'evidence/live-test-item-cleanup.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'item_cancelled':result['item_cancelled'],'after':after,'reply_readback':verified['independent_text_readback']}),flush=True)
