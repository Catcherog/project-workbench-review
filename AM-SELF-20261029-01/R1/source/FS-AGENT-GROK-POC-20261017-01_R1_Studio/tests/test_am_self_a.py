"""AM-SELF A acceptance: deterministic concurrency and code-owned boundaries."""
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-qwen3.8/feishu-bridge'))
from group_ai import QwenGroupAssistant,GroupAIError,validate_grounded,Reply
from group_ledger import GroupLedger,FeishuLedgerPort,LedgerError,parse_rows
from test_group_ai import Provider,intent
from test_group_ledger import VALUES,Port
import test_group_ledger as ledger_tests
from test_reminder import rig,base_rig,receive,prepare,generate,card,FIELDS
from fs_agent.config import BoundaryError
from fs_agent.model_coordinator import ModelCoordinator
from fs_agent.provider import Result
from fs_agent.store import Store

@pytest.mark.parametrize('source,bad',[
 ('交付100台。','交付10台。'),
 ('A项测试已通过；B项测试未通过。','B项测试已通过；A项测试未通过。'),
 ('A项目预计2026.11.1交付；B项目预计2026.11.2交付。','A项目预计2026.11.2交付。'),
 ('样机预计完成。','样机已完成。'),
 ('A扭矩-1.5N·m；B扭矩2.5N·m。','A扭矩2.5N·m。'),
 ('质量10公斤。','质量10克。'),
 ('A负责人AR1甲；B负责人AR2乙。','A负责人AR2乙。')])
def test_A01_bound_facts_reject_wrong_rewrite(source,bad):
 with pytest.raises(GroupAIError):validate_grounded({'paragraphs':[{'text':bad,'evidence':['s1']}]},{'progress':source},'合成项目')
 validate_grounded({'paragraphs':[{'text':source,'evidence':['s1']}]},{'progress':source},'合成项目')


def test_A02_identifier_explanation_and_multiple_ids(tmp_path):
 p=Provider([]);ai=QwenGroupAssistant(p,tmp_path)
 r=ai.reply('RA-2026-003 这样的编号格式是什么意思？',[],None,lambda:pytest.fail('not a lookup'))
 assert r.mode=='general' and not p.calls
 r=ai.reply('查询需求75和需求999进展',[],None,lambda:parse_rows(VALUES))
 assert '实际收货尚未核实' in r.text and '未找到编号：需求999' in r.text and not p.calls
 r=ai.reply('发送需求75进展给工程师',[],None,lambda:pytest.fail('action must not query'))
 assert '操作请求' in r.text


def event(clock,mid,text,**kwargs):
 return ledger_tests.LedgerTests.event(clock,mid,text,**kwargs)


def test_A02_clarification_survives_restart(tmp_path):
 now=SimpleNamespace(now=2_000_000_000);port=Port();sent=[]
 route=GroupLedger(tmp_path,port,lambda *a:sent.append(a),clock=lambda:now.now)
 assert route.ingest(event(now,'om_1','刹车项目进度'))
 route.step();assert '1. ' in sent[-1][1] and '2. ' in sent[-1][1]
 route.close();route=GroupLedger(tmp_path,port,lambda *a:sent.append(a),clock=lambda:now.now)
 assert route.ingest(event(now,'om_2','第二个'));route.step()
 assert 'eRob70FV4' in sent[-1][1] and 'eRob80' not in sent[-1][1]
 route.close()


def test_A03_threads_and_explicit_quote_are_scoped(tmp_path):
 now=SimpleNamespace(now=2_000_000_000);sent=[]
 route=GroupLedger(tmp_path,Port(),lambda mid,t:sent.append((mid,t)) or 'om_reply_'+mid,clock=lambda:now.now)
 def ask(mid,q,thread='',parent=None,user='ou_member'):
  e=event(now,mid,q,user=user);e['event']['message'].update(thread_id=thread,parent_id=parent)
  assert route.ingest(e);route.step();return sent[-1][1]
 ask('om_1','需求75进展','omt_A');ask('om_2','RA-2026-003进展','omt_B')
 assert 'AR1测试甲' in ask('om_3','那谁负责','omt_A')
 assert 'AR1测试甲' in ask('om_4','那谁负责','omt_B','om_reply_om_1')
 assert 'AR1测试甲' not in ask('om_5','那谁负责','omt_B','om_1','ou_other')
 route.close()


def test_A04_known_object_model_failure_and_paused_fast_query(tmp_path):
 ai=QwenGroupAssistant(Provider([intent(reference='数字孪生'),{'match':'one','ids':[2]},BoundaryError('STOP_UNKNOWN')]),tmp_path)
 values=[r[:] for r in VALUES];values[2][0]='RA-2026-003\nDigital Twin开发项目'
 r=ai.reply('数字孪生进展',[],None,lambda:parse_rows(values))
 assert r.project and 'Digital Twin' in r.text and '设计中' in r.text and '可查询：' not in r.text
 ai.paused=lambda:True
 r=ai.reply('需求75进展',[],None,lambda:parse_rows(VALUES))
 assert '实际收货尚未核实' in r.text


def test_A05_late_unrelated_does_not_erase_new_edit(rig):
 g,s,api,p,clock,e=rig;row,d=prepare(rig)
 receive(rig,'好的',2)
 started,release=threading.Event(),threading.Event()
 def complete(*args,**kw):
  started.set();assert release.wait(3)
  return Result(json.dumps(dict(FIELDS,intent='unrelated')),'isolated',.01)
 p.complete=complete;task=s.claim(1)
 with ThreadPoolExecutor(1) as pool:
  f=pool.submit(g.run_task,task);assert started.wait(3)
  receive(rig,'改成18点前交报告。',3);release.set();f.result(3)
 current=g.reminders.get(row)
 assert '改成18点前交报告。' in json.loads(current['turns'])
 assert current['revision']>d['revision'] and current['state']=='collecting'


def test_A05_ordinary_ok_and_duplicate_regenerate_preview(rig):
 g,s,api,p,clock,e=rig;row,d=prepare(rig)
 receive(rig,'好的',2);new=generate(rig,dict(FIELDS,intent='unrelated'))
 assert new['state']=='awaiting_confirmation' and new['revision']>d['revision']
 receive(rig,'好的',3);latest=generate(rig)
 assert latest['state']=='awaiting_confirmation'
 assert '好的' in json.loads(latest['turns'])


def test_A06_atomic_preview_and_late_receipt(rig):
 g,s,api,p,clock,e=rig;row,d=prepare(rig)
 old_out=s.rows('SELECT * FROM outbox WHERE id=?',(d['preview_outbox'],))[0]
 receive(rig,'改成18点前交报告。',2);current=generate(rig,dict(FIELDS,body='今天18点前交报告。'))
 with s.tx() as c:g.reminders.delivered(c,old_out,'om_late')
 assert g.reminders.get(row)['preview_message']==current['preview_message']
 snapshot=s.rows('SELECT * FROM reminder_preview_snapshots WHERE outbox_id=?',(current['preview_outbox'],))
 assert len(snapshot)==1 and snapshot[0]['content_hash']==current['content_hash']
 # Layout does not own approval: rearrange UI elements after delivery.
 out=s.rows('SELECT * FROM outbox WHERE id=?',(current['preview_outbox'],))[0];body=json.loads(out['body']);body['elements'].reverse()
 s.execute('UPDATE outbox SET body=? WHERE id=?',(json.dumps(body),out['id']))
 card(rig,current,number=3)
 assert g.reminders.get(row)['state']=='approved'
 assert len(s.rows('SELECT * FROM reminder_approvals'))==1


def test_A07_preflight_crossing_window_cannot_send_or_extend_retry(rig):
 g,s,api,p,clock,e=rig;row,d=prepare(rig);card(rig,d)
 g.reminders.port.before=lambda:setattr(clock,'now',clock()+61)
 assert g.reminders.dispatch_one();assert not g.reminders.port.sent
 receive(rig,'/remind 重试 R-'+d['marker'],3)
 assert not g.reminders.dispatch_one() and not g.reminders.port.sent


def test_A08_shared_stop_unknown_and_restart(tmp_path):
 store=Store(tmp_path/'store.db');calls=[]
 def complete(*a,**k):calls.append(1);raise BoundaryError('STOP_UNKNOWN')
 coordinator=ModelCoordinator(SimpleNamespace(complete=complete),store,tmp_path)
 with pytest.raises(BoundaryError,match='STOP_UNKNOWN'):coordinator.chat([{'role':'user','content':'hi'}])
 with pytest.raises(BoundaryError,match='MODEL_PAUSED'):coordinator.complete('doc',run_id='0'*32)
 ModelCoordinator(SimpleNamespace(complete=complete),store,tmp_path)
 assert store.meta('provider_pause')=='ORPHAN_STOP_UNKNOWN' and len(calls)==1
 store.close()


def test_A10_disclosure_does_not_leak_candidate_names():
 p=FeishuLedgerPort(None,app_id='cli_test',tenant_key='tenant',bot_open_id='ou_bot',department_root_id='od-test',disclosure={'oc_one':['需求75']})
 with pytest.raises(LedgerError,match='GROUP_DISCLOSURE_NOT_APPROVED'):p.guard('oc_other','ou_member')
 projects=parse_rows(VALUES);visible=p.filter_projects('oc_one',projects)
 assert len(visible)==1 and '需求75' in visible[0]['title']
 p.disclosure['oc_one']=[]
 with pytest.raises(LedgerError,match='PROJECT_DISCLOSURE_CHANGED'):p.guard_disclosure('oc_one',visible)


def test_A09_worker_error_does_not_silently_discard_next_input(tmp_path):
 from bridge import Bridge
 calls=[]
 def step():
  calls.append(1)
  if len(calls)==1:raise RuntimeError('injected worker failure')
  return True
 route=SimpleNamespace(assistant=None,step=step,ingest=lambda p:True)
 b=Bridge({'app_id':'cli_test','state_directory':str(tmp_path),'access_mode':'all_private_users'},lambda *a:None,group_ledger=route)
 b.process_cycle()
 assert b.ingest({'event':{'message':{'chat_type':'group'}}})
 b.process_cycle();assert len(calls)==2 and not b.group_ledger_suspended
 b.db.close()


def test_A11_existing_data_survives_repeated_migration(rig,tmp_path):
 from am_service import AmSelfService
 g,s,api,p,c,e=rig;row,d=prepare(rig);old=dict(d)
 port=Port();port.authorize_user=lambda _:None
 ledger=GroupLedger(tmp_path,port,lambda *a:None,clock=c)
 AmSelfService(g,ledger,flags={'query':True});AmSelfService(g,ledger,flags={'query':True})
 assert g.reminders.get(row)['id']==old['id'] and g.reminders.get(row)['payload']==old['payload']
 assert s.rows('SELECT * FROM am_migrations') and s.rows('SELECT * FROM business_migrations')
 ledger.close()
