import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-qwen3.8/feishu-bridge'))
from test_reminder import rig,base_rig
from test_gateway import event,drain
from test_group_ledger import Port
from test_am_self_d import Sheet
from group_ledger import GroupLedger
from am_service import AmSelfService


def click(service,g,s,number,action):
 c=s.rows('SELECT * FROM am_cards ORDER BY rowid DESC LIMIT 1')[0]
 payload={'header':{'app_id':'cli_test','tenant_key':'tenant_test','event_id':f'am_card_{number}','event_type':'card.action.trigger'},
          'event':{'operator':{'open_id':'ou_a'},'context':{'open_chat_id':'oc_dm','open_message_id':c['message_id']},'action':{'value':{'flow':'am_self','nonce':c['nonce'],'action':action}}}}
 assert service.ingest(payload)==(True,True);assert service.step();drain(g)
 return c


def test_C_owner_creates_item_then_exact_future_plan_from_private_chat(rig,tmp_path):
 g,s,api,model,clock,e=rig;port=Port();port.authorize_user=lambda _:None
 ledger=GroupLedger(tmp_path,port,lambda *a:None,clock=clock)
 service=AmSelfService(g,ledger,flags={'query':True,'items':True,'scheduler':True})
 assert service.ingest(event('/item 新增 需求75｜提交测试报告｜合成研发群｜工程师甲｜完整报告',number=1))==(True,True)
 service.step();drain(g)
 assert not s.rows('SELECT * FROM action_items')
 click(service,g,s,1,'create')
 item=s.rows('SELECT * FROM action_items')[0]
 assert item['state']=='waiting'
 assert service.ingest(event('/plan 一次 '+item['id']+'｜明天 09:00｜请提交完整测试报告。',number=2))==(True,True)
 service.step();drain(g)
 plan=s.rows('SELECT * FROM reminder_plans')[0];assert plan['state']=='draft'
 click(service,g,s,2,'approve')
 assert service.scheduler.plan(plan['id'])['state']=='active'
 assert not s.rows('SELECT * FROM reminder_occurrences') and not model.prompts
 ledger.close()


def test_D_owner_exact_diff_approval_cannot_enable_disabled_write(rig,tmp_path):
 g,s,api,model,clock,e=rig;port=Port();port.authorize_user=lambda _:None
 ledger=GroupLedger(tmp_path,port,lambda *a:None,clock=clock)
 service=AmSelfService(g,ledger,flags={'query':True,'progress_collection':True,'ledger_write':False})
 sheet=Sheet();service.updates.port=sheet
 assert service.ingest(event('/update 需求75：上电测试今天完成，报告明天下午提交，低温复测还没做。',number=1))==(True,True)
 service.step();drain(g)
 p=s.rows('SELECT * FROM ledger_proposals')[0]
 assert p['state']=='proposed'
 c=click(service,g,s,1,'approve:项目进展')
 assert service.updates.proposal(p['id'])['state']=='approved' and not sheet.calls
 click(service,g,s,2,'approve:项目进展')
 assert len(s.rows('SELECT * FROM ledger_approval_snapshots'))==1
 ledger.close()
