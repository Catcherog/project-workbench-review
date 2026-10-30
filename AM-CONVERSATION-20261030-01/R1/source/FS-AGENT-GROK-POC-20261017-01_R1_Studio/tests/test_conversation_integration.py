"""Original AM routing/store/ports with synthetic model and Feishu endpoints."""
import json,sys
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'am-conversation-r1/src'))
from test_am_ux1 import ux,service,am_rig,base_rig
from test_gateway import event,drain
from am_conversation.legacy import LegacyConversationBridge
from fs_agent.model_coordinator import ModelCoordinator
from fs_agent.feishu import SendUnknown

class JsonProvider:
    def __init__(self):self.outputs=[];self.prompts=[]
    def complete(self,prompt,**kw):
        self.prompts.append(prompt)
        assert self.outputs,'unexpected extra model call'
        return SimpleNamespace(text=json.dumps(self.outputs.pop(0),ensure_ascii=False),model='synthetic-json',elapsed=.01)

def call(name,args):return {'type':'tool_calls','tool_calls':[{'id':'c1','name':name,'arguments':args}]}
def answer(text):return {'type':'answer','text':text}

@pytest.fixture
def convo(ux):
    am,g,s,api,clock,port=ux;p=JsonProvider();g.provider=ModelCoordinator(p,s,g.config.root/'state')
    port.disclosure={'oc_reminder':['*']};port.filter_projects=lambda chat,projects:projects if chat in port.disclosure else []
    remote={};send=api.send;api.verify_allowed=True
    def save(row,guard):
        mid=send(row,guard);remote[mid]=dict(row);return mid
    api.send=save
    api.verify_text=lambda mid,row:api.verify_allowed and row.get('_query_readback_guard',lambda:True)() and mid in remote and remote[mid]['body']==row['body'] and remote[mid]['chat']==row['chat']
    am.conversation=LegacyConversationBridge(am,{'enabled':True,'business_actions':True,'text_previews':True,'verify_previews':True,'group_conversations':True,
      'runtime':{'allow_external_actions':True,'prefetch_projects':True,'trusted_write_replies':True}})
    am.snapshots.refresh().result(2)
    yield ux,p
    am.conversation.close();am.conversation=None

def speak(convo,text,outputs=(),*,actor='ou_a',n=None,verify=True):
    ux,p=convo;am,g,s,api,clock,port=ux;p.outputs.extend(outputs)
    n=n or len(s.rows('SELECT id FROM am_inbox'))+1
    payload=event(text,number=n,user=actor,chat='oc_dm' if actor=='ou_a' else 'oc_'+actor);payload['event']['message']['create_time']=str(int(clock()*1000))
    assert am.ingest(payload)==(True,True);assert am.step();drain(g)
    if verify:
        for o in s.rows("SELECT outbox_id FROM am_conversation_outputs WHERE state='awaiting_verification'"):am.conversation.verify_presentation(o['outbox_id'])
    return s.rows('SELECT * FROM am_inbox ORDER BY rowid DESC LIMIT 1')[0],api.sent[-1]['body']

def project(convo):return convo[0][0].snapshots.get()['rows'][0]['key']

def test_natural_query_plain_text_and_legacy_command_remain(convo):
    row,text=speak(convo,'需求75谁负责',[answer('记录的负责人是 AR1测试甲。')])
    assert row['state']=='done' and row['kind']=='conversation'
    assert convo[0][3].sent[-1]['kind']=='text' and not convo[0][2].rows('SELECT 1 FROM am_cards')
    am,g,s,api,clock,port=convo[0]
    payload=event('/project 需求75',number=90);payload['event']['message']['create_time']=str(int(clock()*1000))
    assert am.ingest(payload)==(True,True);am.step();drain(g)
    assert s.rows('SELECT 1 FROM am_cards')

def test_create_followup_and_pause_use_original_item_store(convo):
    row,text=speak(convo,'登记需求75报告跟进',[call('create_followup',{'project_id':project(convo),'description':'跟进报告','deadline_kind':'estimate','deadline':'预计11月2日'})])
    assert row['state']=='done' and '已登记' in text
    items=convo[0][2].rows('SELECT * FROM action_items');assert len(items)==1 and items[0]['deadline_kind']=='estimate'
    row,text=speak(convo,'这项先暂停',[call('change_followup',{'item_id':items[0]['id'],'version':items[0]['version'],'operation':'pause'})])
    assert convo[0][0].items.get(items[0]['id'])['paused']==1
    assert not convo[0][2].rows('SELECT * FROM reminder_plans') and not convo[0][1].reminders.port.sent

def test_group_send_waits_for_exact_text_readback_and_natural_confirmation(convo):
    ux,p=convo;api=ux[3];api.verify_allowed=False
    args={'target':'group','group_id':'oc_reminder','recipient_ids':['ou_engineer_a'],'body':'合成验证：请核对报告。'}
    row,text=speak(convo,'准备向工程师甲发这条消息',[call('send_message',args)],verify=False)
    assert row['state']=='done' and '确认第1项' in text and 'action_' not in text and not ux[1].reminders.port.sent
    row,text=speak(convo,'按这个发')
    assert not ux[1].reminders.port.sent and '预览' in text
    api.verify_allowed=True
    for o in ux[2].rows("SELECT outbox_id FROM am_conversation_outputs WHERE state='awaiting_verification'"):ux[0].conversation.verify_presentation(o['outbox_id'])
    row,text=speak(convo,'确认执行')
    assert row['state']=='done' and len(ux[1].reminders.port.sent)==1 and '已发送' in text
    speak(convo,'按这个发')
    assert len(ux[1].reminders.port.sent)==1

def test_unknown_send_never_repeats_and_can_reconcile(convo):
    ux,p=convo;port=ux[1].reminders.port
    args={'target':'group','group_id':'oc_reminder','recipient_ids':['ou_engineer_a'],'body':'合成验证正文'}
    speak(convo,'准备发送',[call('send_message',args)])
    port.error=SendUnknown('synthetic response lost')
    speak(convo,'确认第1项');assert len(port.sent)==1
    speak(convo,'按这个发');assert len(port.sent)==1
    ident=ux[2].rows('SELECT action_id FROM am_conversation_sends')[0]['action_id'];port.error=None
    speak(convo,'核对刚才的发送结果',[call('reconcile_send',{'action_id':ident}),answer('消息已发送，接收对象和正文已回读核对。')])
    assert ux[2].rows('SELECT state FROM am_conversation_sends')[0]['state']=='verified' and len(port.sent)==1

def test_schedule_activation_cancel_and_no_early_send(convo):
    ux,p=convo;at=datetime.fromtimestamp(ux[4](),ZoneInfo('Asia/Shanghai'))+timedelta(days=1)
    args={'target':'self','body':'合成测试：检查报告','frequency':'once','at':at.isoformat()}
    speak(convo,'请在'+at.isoformat()+'提醒我检查报告',[call('schedule_reminder',args)])
    assert not ux[2].rows('SELECT * FROM reminder_plans')
    row,text=speak(convo,'确认第1项');assert row['state']=='done',row
    plans=ux[2].rows('SELECT * FROM reminder_plans');assert len(plans)==1 and plans[0]['state']=='active'
    assert json.loads(plans[0]['target'])['chat']=='oc_dm'
    row,text=speak(convo,'取消这个提醒',[call('control_reminder',{'plan_id':plans[0]['id'],'version':plans[0]['version'],'operation':'cancel'})])
    assert ux[0].scheduler.plan(plans[0]['id'])['state']=='cancelled'
    assert not ux[2].rows('SELECT * FROM reminder_occurrences')

def test_teaching_natural_approval_is_scoped_and_delivered(convo):
    ux,p=convo
    speak(convo,'以后先核实测试与报告是否分别完成',[call('propose_knowledge',{'kind':'rule','scope':'private','content':'先核实测试与报告是否分别完成。'})])
    row,text=speak(convo,'采用第1条');assert row['state']=='done' and '批准' in text
    assert not ux[2].rows('SELECT 1 FROM ledger_write_attempts')


def test_large_information_result_is_projected_with_coverage(convo):
    ux,p=convo
    ux[0].information=SimpleNamespace(query=lambda row,key:{'version':'v1','facts':[{'fact_id':'f1','field':'system_record','assertion_type':'source_statement','value':{'basic':{'name':'合成记录','status':'待核'},'large_unread_field':'源'*30000},'evidence':{'version':'v1','object_id':'synthetic','quote':'文'*20000}}],
       'coverage':{'processing_pending':True,'needs_refresh_or_review':True,'sources':[{'source_id':'source1','stale':True}]}})
    row,text=speak(convo,'需求75现在怎样',[answer('当前记录仍待核，另有资料待处理。')])
    assert row['state']=='done' and '待核' in text
    prompt=p.prompts[-1];assert len(prompt)<30000 and 'large_unread_field' in prompt and '源'*100 not in prompt
    assert 'processing_pending' in prompt and 'selection_note' in prompt


def test_new_document_does_not_cancel_earlier_draft(convo):
    row,text=speak(convo,'新建一份测试报告',[call('edit_document',{'operation':'create','kind':'test'})])
    assert row['state']=='done',row
    first=convo[0][2].rows('SELECT * FROM logic_drafts')[0]
    row,text=speak(convo,'再新建一份项目章程',[call('edit_document',{'operation':'create','kind':'charter'})])
    assert row['state']=='done',row
    assert len(convo[0][2].rows('SELECT * FROM logic_drafts'))==2
    assert convo[0][2].rows('SELECT state FROM logic_drafts WHERE id=?',(first['id'],))[0]['state']=='collecting'


def test_project_feedback_flows_to_owner_without_ledger_write(convo):
    ux,p=convo;ux[0].query_scope={'users':{'ou_staff':['需求75']}}
    row,text=speak(convo,'同步项目反馈：报告已提交，尚未验收。',[call('submit_project_update',{'project_id':project(convo),'content':'报告已提交，尚未验收。'})],actor='ou_staff')
    assert row['state']=='done',row
    report=ux[2].rows('SELECT * FROM progress_collections')[0]
    assert not report['reporter_confirmed'] and not ux[2].rows('SELECT * FROM ledger_write_attempts')
    row,text=speak(convo,'采用这条项目反馈',[call('adopt_project_update',{'report_id':report['id'],'version':report['version']})])
    assert row['state']=='done' and '不自动分享' in text
    row,text=speak(convo,'确认第1项');assert row['state']=='done',row
    assert not ux[2].rows('SELECT * FROM ledger_write_attempts')


def test_change_reminder_time_requires_new_preview_and_keeps_plan_identity(convo):
    ux,p=convo;at=datetime.fromtimestamp(ux[4](),ZoneInfo('Asia/Shanghai'))+timedelta(days=1)
    speak(convo,'在'+at.isoformat()+'提醒我合成验证',[call('schedule_reminder',{'target':'self','body':'合成验证','frequency':'once','at':at.isoformat()})])
    speak(convo,'确认第1项');plan=ux[2].rows('SELECT * FROM reminder_plans')[0]
    newer=at+timedelta(days=2)
    row,text=speak(convo,'把这条提醒改到'+newer.isoformat(),[call('revise_reminder',{'plan_id':plan['id'],'version':plan['version'],'at':newer.isoformat()})])
    assert row['state']=='done',row
    assert ux[0].scheduler.plan(plan['id'])['next_at']==at.timestamp()
    speak(convo,'确认第1项');after=ux[0].scheduler.plan(plan['id'])
    assert after['next_at']==newer.timestamp() and after['version']>plan['version'] and after['state']=='active'
    assert len(ux[2].rows('SELECT * FROM reminder_plans'))==1


def test_natural_group_quote_is_actor_scoped_and_has_no_management_tools(convo):
    ux,p=convo;am,g,s,api,clock,port=ux;port.disclosure={'oc_reminder':['需求75']}
    def ask_group(body,actor,n,parent=None):
        payload=event(body,number=n,user=actor,chat='oc_reminder',group=True);payload['event']['message'].update(create_time=str(int(clock()*1000)),parent_id=parent)
        p.outputs.append(answer('合成项目仍待核对。'))
        assert am.ingest(payload)==(True,True);am.step();drain(g)
        return s.rows('SELECT * FROM am_inbox ORDER BY rowid DESC LIMIT 1')[0]
    assert ask_group('需求75进展','ou_staff',101)['state']=='done'
    ref=s.rows('SELECT * FROM am_group_refs ORDER BY rowid DESC LIMIT 1')[0]
    assert ask_group('那谁负责','ou_other',102,ref['message_id'])['state']=='done'
    prompt=p.prompts[-1];assert 'quoted_project_ids' in prompt and 'send_message' not in prompt
    assert ask_group('那谁负责','ou_third',103)['state']=='done'
    payload=json.loads(p.prompts[-1].split('（JSON数据）：\n',1)[1])
    current=json.loads(payload['messages'][1]['content'].split('\n',1)[1])
    assert current['current_project_id'] is None and not current.get('fresh_project_sources')
    assert all(row['kind']=='text' and row['chat_type']=='group' for row in api.sent)


def test_briefing_subscription_is_confirmed_and_cancellable(convo):
    ux,p=convo;until=datetime.fromtimestamp(ux[4](),ZoneInfo('Asia/Shanghai'))+timedelta(days=4)
    row,text=speak(convo,'每天09:30给我简报，截止'+until.isoformat(),[call('subscribe_briefing',{'frequency':'daily','time':'09:30','until':until.isoformat()})])
    assert row['state']=='done' and '固定规则' in text and not ux[2].rows('SELECT * FROM am_subscriptions')
    row,text=speak(convo,'确认第1项');assert row['state']=='done',row
    plan=ux[2].rows('SELECT * FROM reminder_plans')[0];assert plan['state']=='active' and plan['kind']=='briefing'
    assert json.loads(plan['target'])['conversation_text'] is True
    speak(convo,'取消这个订阅',[call('control_reminder',{'plan_id':plan['id'],'version':plan['version'],'operation':'cancel'})])
    assert ux[0].scheduler.plan(plan['id'])['state']=='cancelled'


def test_expired_rendered_reply_is_removed_with_raw_history(convo):
    ux,p=convo;speak(convo,'需求75现在怎样',[answer('这段临时回答到期应清除。')])
    ux[4].now+=86401;ux[0].conversation.cleanup()
    row=ux[2].rows('SELECT * FROM am_conversation_outputs')[0]
    assert row['rendered_text'] is None and row['reply']=='{}' and row['context']=='{}' and row['state']=='expired'


def test_consumed_once_reminder_can_still_be_listed_and_cancelled(convo):
    ux,p=convo;at=datetime.fromtimestamp(ux[4](),ZoneInfo('Asia/Shanghai'))+timedelta(minutes=5)
    speak(convo,'在'+at.isoformat()+'提醒我合成验证',[call('schedule_reminder',{'target':'self','body':'合成验证','frequency':'once','at':at.isoformat()})])
    speak(convo,'确认第1项');plan=ux[2].rows('SELECT * FROM reminder_plans')[0]
    ux[4].now=at.timestamp();ux[0].scheduler.scan()
    assert ux[0].scheduler.plan(plan['id'])['next_at']==float('inf')
    row,text=speak(convo,'查看我的提醒',[call('list_reminders',{}),answer('已经生成本次发送任务，没有下一次安排。')])
    assert row['state']=='done' and 'schedule_exhausted' in p.prompts[-1] and 'Infinity' not in p.prompts[-1]
    row,text=speak(convo,'取消这条提醒',[call('control_reminder',{'plan_id':plan['id'],'version':plan['version'],'operation':'cancel'})])
    assert row['state']=='done' and ux[0].scheduler.plan(plan['id'])['state']=='cancelled'


def test_estimated_afternoon_is_not_an_invented_clock_time(convo):
    when=datetime.fromtimestamp(convo[0][4](),ZoneInfo('Asia/Shanghai'))+timedelta(days=1)
    base={'project_id':project(convo),'description':'核对报告'}
    wrong=dict(base,next_check=when.replace(hour=14).isoformat())
    precise_date=when.strftime('%Y.%m.%d')
    right=dict(base,deadline='明天下午',deadline_kind='estimate')
    row,text=speak(convo,'给需求75登记报告跟进，预计明天下午处理，不用发消息。',[call('create_followup',wrong),call('create_followup',right)])
    assert row['state']=='done';items=convo[0][2].rows('SELECT * FROM action_items')
    assert len(items)==1 and items[0]['next_check'] is None and items[0]['deadline_kind']=='estimate'
    assert when.strftime('%Y-%m-%d') in items[0]['deadline'] and '明天' not in items[0]['deadline'] and '预计时间' in text
