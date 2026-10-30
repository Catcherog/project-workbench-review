"""Owner-only retest after the exhausted-reminder JSON fix. No timer is allowed to fire."""
from pathlib import Path
helper=Path(__file__).with_name('live_business.py')
# Reuse its exact receipt/readback helpers; the earlier live scenario is not run.
setup=helper.read_text().split('plan_id=None\n',1)[0].replace('evidence/live-business.json','evidence/live-control-retest.json')
exec(compile(setup,str(helper),'exec'))
plan_id=None
try:
 send('我的合成提醒还会再发吗？','read_consumed_and_cancelled_plan')
 at=(datetime.now(ZoneInfo('Asia/Shanghai'))+timedelta(minutes=10)).replace(second=0,microsecond=0)
 body='AM-R1 合成取消验证，确认后立即取消，不实际提醒。'
 row,reply=send('请在北京时间'+at.strftime('%Y-%m-%d %H:%M')+'提醒我：'+body+'仅一次，发给我本人。','cancel_test_preview',True)
 assert body in row['body'] and reply['status']=='needs_confirmation'
 send('确认第1项','cancel_test_confirm')
 plans=db.execute('SELECT * FROM reminder_plans WHERE created>=?',(report['started_at'],)).fetchall();assert len(plans)==1;plan_id=plans[0]['id']
 send('取消刚才那条尚未发送的合成提醒。','cancel_test_natural_cancel')
 assert db.execute('SELECT state FROM reminder_plans WHERE id=?',(plan_id,)).fetchone()[0]=='cancelled'
 assert not db.execute('SELECT 1 FROM reminder_occurrences WHERE plan_id=?',(plan_id,)).fetchone()
 report['checks']={'exhausted_plan_query_returned_normally':True,'future_plan_cancelled_by_natural_tool':True,'no_timer_message_sent':True};report['finished_at']=time.time();save()
 print(json.dumps(report['checks']),flush=True)
finally:
 if plan_id:
  current=db.execute('SELECT * FROM reminder_plans WHERE id=?',(plan_id,)).fetchone()
  if current['state']!='cancelled':
   from fs_agent.store import Store
   from fs_agent.action_items import ActionItems
   from fs_agent.scheduler import Scheduler
   store=Store(cfg.db)
   try:Scheduler(store,ActionItems(store,cfg.owner),cfg.owner,None).control(cfg.owner,'validation-cleanup/'+plan_id,plan_id,current['version'],'cancel')
   finally:store.close()
   report['cleanup_cancelled_test_plan']=True;save()
 port.identity_pool.shutdown(wait=True);db.close()
