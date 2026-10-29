"""Public synthetic inputs, real pinned Qwen, shared coordinator, zero platform sends."""
import json,sys,time,uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from fs_agent.config import Config
from fs_agent.store import Store
from fs_agent.qwen_provider import LocalQwenProvider
from fs_agent.model_coordinator import ModelCoordinator
from fs_agent.reminder_content import prompt,parse_fields
from fs_agent.doc_logic import read_source,build_prompt,parse_json,validate_analysis
from group_ai import QwenGroupAssistant
from group_ledger import parse_rows
private=Path.home()/'.local/share/local-qwen-feishu';cfg=json.loads((private/'config.json').read_text());c=Config.load(Path(cfg['poc_config']))
s=Store(c.db);provider=ModelCoordinator(LocalQwenProvider(c),s,c.root/'state');pin=provider.pin();out=ROOT/'AM-SELF-20261029-01/R1/evidence/real-qwen.json'
report={'kind':'real_pinned_local_qwen_synthetic_validation','model':pin['model'],'server_version':pin['server_version'],'model_pin_verified':True,'real_platform_sends':0,'real_ledger_writes':0,'cases':[]}
def save():out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
def case(name,fn):
 start=time.monotonic()
 try:
  details=fn();result={'id':name,'status':'passed','elapsed_seconds':round(time.monotonic()-start,2),'details':details}
 except Exception as exc:
  result={'id':name,'status':'failed','elapsed_seconds':round(time.monotonic()-start,2),'error_type':type(exc).__name__,'error_code':str(exc)[:120]}
 report['cases'].append(result);save();print(json.dumps(result,ensure_ascii=False),flush=True)
state=private/'validation/am-self-20261029-r1/model-validation';state.mkdir(exist_ok=True)
ai=QwenGroupAssistant(provider,state,paused=lambda:bool(s.meta('provider_pause')),pause=lambda code:s.set_meta('provider_pause',code))
def intent_case():
 result=ai.intent('RA-2026-003 这样的编号格式是什么意思？',[],None,time.monotonic()+120)
 assert result['route']=='general'
 return {'route':result['route'],'real_calls':ai.total_calls}
case('Q1_identifier_explanation',intent_case)
values=[['项目／需求','关键日期','待办','项目进展','人员与职责'],
 ['需求75:合成刹车A项目','预计2026.11.1','协调报告核对','2026.10.29\nA项完成100台；B项尚未完成。\n要求：验证通过后才可验收。','AR1合成甲'],
 ['RA-2026-003\n合成刹车B项目','','','2026.10.29\n设计中，尚未批准。','AR2合成乙']]
def clarification_case():
 before=ai.total_calls;r=ai.reply('刹车项目进展如何',[],None,lambda:parse_rows(values))
 assert r.mode=='clarify' and len(r.candidates)==2
 return {'mode':r.mode,'candidate_count':len(r.candidates),'real_calls':ai.total_calls-before}
case('Q2_ambiguous_candidates',clarification_case)
def factual_case():
 before=ai.total_calls;p=parse_rows(values)[0]
 r=ai.project_answer('介绍当前进展',{'fields':['progress']},p,time.monotonic()+120,read_at=time.time())
 assert '100台' in r.text and '尚未完成' in r.text
 assert '验证通过后才可验收' in r.text
 return {'grounding':ai.last_grounding,'source_conditions_preserved':True,'real_calls':ai.total_calls-before,'reply':r.text.replace('https://tenant.example.feishu.cn/sheets/SYNTHETIC_LEDGER_TOKEN?sheet=SYNTHETIC_SHEET','[CONFIGURED_SOURCE]')}
case('Q3_subject_bound_facts_or_source_fallback',factual_case)
def reminder_case():
 anchor=datetime(2026,10,29,9,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
 turns=['帮我在合成研发群提醒工程师甲，今天17点前提交合成报告。']
 r=provider.complete(prompt(turns,{},anchor),run_id=uuid.uuid4().hex,native_chat=True,max_tokens=1024)
 fields=parse_fields(r.text,turns,{},anchor)
 turns+=['改成18点前交报告。']
 r2=provider.complete(prompt(turns,fields,anchor),run_id=uuid.uuid4().hex,native_chat=True,max_tokens=1024)
 changed=parse_fields(r2.text,turns,fields,anchor)
 assert changed['group_query']==fields['group_query'] and changed['people_queries']==fields['people_queries']
 assert '18' in changed['body'] and '17' not in changed['body']
 return {'fields':changed,'real_calls':2,'sent':False}
case('Q4_reminder_revision',reminder_case)
def document_case():
 source=read_source('synthetic.txt','合成测试报告。报告版本v1；测试对象为合成样机A。合成验收要求：扭矩不低于10N.m。实测为8N.m，未达到要求；原因尚未明确，不能宣布验证通过。'.encode(),source_id='S01',origin='synthetic')
 text,meta=build_prompt([source],'test',False,{})
 r=provider.complete(text,run_id=uuid.uuid4().hex,native_chat=True,max_tokens=2048)
 value=validate_analysis(parse_json(r.text),[source],stage=False)
 assert '通过' not in value['assessment'] or any(x in value['assessment'] for x in ('未','不能','不'))
 return {'assessment':value['assessment'],'evidence_count':len(value['evidence']),'real_calls':1,'source_scope':'one synthetic text source'}
case('Q5_document_analysis',document_case)
report['provider_pause_after']=s.meta('provider_pause');report['passed']=sum(x['status']=='passed' for x in report['cases']);save();s.close()
