import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from datetime import datetime
import pytest
from fs_agent.action_items import ActionItems
from fs_agent.scheduler import Scheduler,Calendar,parse_time,TZ
from fs_agent.store import Store
from fs_agent.config import BoundaryError
from fs_agent.feishu import SendRejected,SendUnknown

class Port:
 def __init__(self):self.calls=[];self.error=None;self.found=False;self.before=lambda:None
 def refresh(self,p):self.before()
 def send(self,p,key,guard):
  if not guard():raise SendRejected('GUARD')
  if isinstance(self.error,SendRejected):raise self.error
  self.calls.append(key)
  if self.error:raise self.error
  return {'message_id':'om_'+key}
 def reconcile(self,p,key,started,mid):return {'verified':True,'message_id':mid or 'om_'+key} if self.found else None

@pytest.fixture
def rig(tmp_path):
 now=[datetime(2026,10,29,8,0,tzinfo=TZ).timestamp()]
 s=Store(tmp_path/'am.db',lambda:now[0]);items=ActionItems(s,'ou_owner');port=Port()
 item=items.create('ou_owner','create',project_ref='project',description='提交报告',requirements='完整材料待核验',assignees=['ou_assignee'],source={'kind':'explicit_owner_request'})
 scheduler=Scheduler(s,items,'ou_owner',port,enabled=lambda:True)
 yield s,items,port,item,scheduler,now
 s.close()

def plan(rig,*,kind='once',policy='fixed_rule',at=None):
 s,items,port,item,sch,now=rig
 rule={'at':at or now[0]+60} if kind=='once' else {'time':'09:00','timezone':'Asia/Shanghai'}
 p=sch.create('ou_owner','create_plan',item_id=item['id'],kind=kind,rule=rule,target={'kind':'group','payload':{'synthetic':True}},template='请提交报告。',policy=policy,valid_until=now[0]+3*86400,window_seconds=60)
 return sch.approve_plan('ou_owner',p['id'],p['version'],p['hash'])


def test_C01_C02_feedback_identity_versions_idempotency(rig):
 s,items,port,item,sch,now=rig
 with pytest.raises(BoundaryError,match='NOT_ASSIGNEE'):items.feedback('ou_other','bad',item['id'],1,'received','',{})
 a=items.feedback('ou_assignee','ack',item['id'],1,'received','',{})
 assert a['item']['state']=='waiting'
 assert items.feedback('ou_assignee','ack',item['id'],1,'received','',{})==a
 late=items.feedback('ou_assignee','late',item['id'],1,'submitted','报告',{})
 assert late['late_evidence'] and items.get(item['id'])['state']=='waiting'
 b=items.feedback('ou_assignee','submit',item['id'],2,'submitted','报告',{})
 assert b['item']['state']=='submitted'
 c=items.feedback('ou_assignee','notmine',item['id'],3,'not_mine','请核对',{})
 assert json.loads(c['item']['assignees'])==['ou_assignee'] and c['item']['state']=='submitted'
 with pytest.raises(BoundaryError):items.change('ou_assignee','close',item['id'],4,'close',evidence='self reported')
 done=items.change('ou_owner','close',item['id'],4,'close',evidence='已核对合成报告内容')
 assert done['state']=='closed'


def test_C03_scans_unique_and_restart_unknown(rig):
 s,items,port,item,sch,now=rig;p=plan(rig);now[0]+=60
 with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:sch.scan(),range(2)))
 assert len(s.rows('SELECT * FROM reminder_occurrences'))==1
 o=s.rows('SELECT * FROM reminder_occurrences')[0]
 s.execute("UPDATE reminder_occurrences SET state='sending' WHERE id=?",(o['id'],))
 Scheduler(s,items,'ou_owner',port,enabled=lambda:True)
 assert sch.occurrence(o['id'])['state']=='unknown';assert not sch.dispatch() and not port.calls

@pytest.mark.parametrize('action',['pause','cancel','close'])
def test_C04_latest_item_state_checked_after_preflight(rig,action):
 s,items,port,item,sch,now=rig;p=plan(rig);now[0]+=60;sch.scan()
 port.before=lambda:items.change('ou_owner','change',item['id'],1,action,evidence='明确核验结果' if action=='close' else None)
 sch.dispatch();assert not port.calls


def test_C05_calendar_missing_and_no_catchup_burst(rig):
 s,items,port,item,sch,now=rig
 with pytest.raises(BoundaryError,match='CALENDAR'):sch.create('ou_owner','work',item_id=item['id'],kind='workdays',rule={'time':'09:00','timezone':'Asia/Shanghai'},target={'kind':'group','payload':{'synthetic':True}},template='提醒',valid_until=now[0]+5*86400)
 p=plan(rig,kind='daily');now[0]+=2*86400+3600+120
 sch.scan();assert not s.rows('SELECT * FROM reminder_occurrences')
 assert sch.plan(p['id'])['next_at']>now[0]
 calendar=Calendar({'source':'synthetic confirmed calendar','version':'v1','verified_at':now[0],'start':'2026-10-29','end':'2026-10-31','days':{'2026-10-29':True,'2026-10-30':False,'2026-10-31':True}})
 late=datetime(2026,10,29,19,tzinfo=TZ).timestamp()
 assert datetime.fromtimestamp(calendar.next_work_morning(late),TZ).isoformat()=='2026-10-31T09:00:00+08:00'


def test_C06_per_occurrence_preview_required(rig):
 s,items,port,item,sch,now=rig;p=plan(rig,policy='preview_each');now[0]+=60;sch.scan()
 o=s.rows('SELECT * FROM reminder_occurrences')[0]
 assert o['state']=='awaiting_confirmation' and not sch.dispatch()
 sch.approve_occurrence('ou_owner',o['id'],o['hash']);assert sch.dispatch() and len(port.calls)==1
 assert sch.scan() is False


def test_C07_definite_failure_retry_same_key_unknown_never_resends(rig):
 s,items,port,item,sch,now=rig;plan(rig);now[0]+=60;sch.scan()
 port.error=SendRejected('TEMPORARILY_REJECTED');sch.dispatch()
 o=s.rows('SELECT * FROM reminder_occurrences')[0];assert o['state']=='confirmed_not_sent'
 now[0]+=3;port.error=SendUnknown('lost');sch.dispatch()
 assert len(port.calls)==1 and sch.occurrence(o['id'])['state']=='unknown'
 now[0]+=3;assert not sch.dispatch()
 port.found=True;assert sch.reconcile(o['id'],manual=True)
 assert sch.occurrence(o['id'])['readback_state']=='verified' and len(port.calls)==1


def test_C08_chat_cleanup_does_not_delete_long_lived_items(rig):
 s,items,port,item,sch,now=rig;p=plan(rig,kind='daily');now[0]+=86401;s.cleanup()
 assert items.get(item['id'])['state']=='waiting' and sch.plan(p['id'])['state']=='active'


def test_C09_briefing_unknown_restart_keeps_event_cursor(rig):
 s,items,port,item,sch,now=rig
 sch.briefing=lambda p:('合成变化简报',['event1'])
 p=sch.create('ou_owner','briefing',item_id=None,kind='briefing',rule={'time':'09:00','timezone':'Asia/Shanghai'},target={'kind':'owner','user':'ou_owner'},template='',policy='owner_subscription',valid_until=now[0]+3*86400)
 sch.approve_plan('ou_owner',p['id'],p['version'],p['hash'])
 s.execute("INSERT INTO am_subscriptions VALUES('sub','ou_owner',?,'active')",(p['id'],))
 now[0]+=3600;sch.scan();port.error=SendUnknown('lost');sch.dispatch()
 o=s.rows('SELECT * FROM reminder_occurrences')[0]
 assert s.rows('SELECT state FROM am_briefing_deliveries')[0]['state']=='pending'
 Scheduler(s,items,'ou_owner',port,enabled=lambda:True,briefing=sch.briefing)
 assert not sch.scan() and not sch.dispatch() and len(port.calls)==1
 port.found=True;sch.reconcile(o['id'],manual=True)
 assert s.rows('SELECT state FROM am_briefing_deliveries')[0]['state']=='verified'


def test_C04_body_revision_invalidates_old_rule_and_occurrence(rig):
 s,items,port,item,sch,now=rig;p=plan(rig,kind='daily');now[0]+=3600;sch.scan()
 old=s.rows('SELECT * FROM reminder_occurrences')[0]
 changed=sch.revise('ou_owner','edit',p['id'],1,template='请提交修订后的报告。')
 assert changed['version']==2 and changed['state']=='draft' and changed['approval_id'] is None
 assert sch.occurrence(old['id'])['state']=='cancelled' and not sch.dispatch()


def test_C08_terminal_cleanup_keeps_idempotency_tombstones(rig):
 s,items,port,item,sch,now=rig
 items.change('ou_owner','close',item['id'],1,'close',evidence='明确核验')
 now[0]+=31*86400
 preview=items.cleanup_preview();assert len(preview)==1
 result=items.apply_cleanup('ou_owner','clean',preview)
 assert result['archived_count']==1 and items.get(item['id'])['description']=='已归档'
 with pytest.raises(BoundaryError,match='OPERATION_EXPIRED'):
  items.create('ou_owner','create',project_ref='project',description='提交报告',requirements='完整材料待核验',assignees=['ou_assignee'],source={'kind':'explicit_owner_request'})
