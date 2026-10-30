"""Thirty synthetic UI actions and renderer examples; never connects to Feishu."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from test_am_ux3 import ux,service,am_rig,base_rig,ask,staff_click
from test_am_ux1 import click,latest,text
from test_am_ux2 import form
from test_am_ux2_fix1 import feedback
from am_query import QueryIdentityCache
OUT=Path(__file__).resolve().parents[1]/'evidence'

def test_thirty_actions_and_examples(ux):
    am,g,s,api,clock,port=ux
    am.query_scope={'users':{'ou_staff':['*']}}
    am.query_identity.close();am.query_identity=QueryIdentityCache(port.authorize_user,600)
    port.values += [[f'需求{n}:合成导航项目{n}','','预计下周，待核对','协调报告','尚未验收','AR9合成人员',''] for n in range(80,88)]
    captures={};samples=[]
    def observe(label,action):
        reads=port.reads;models=len(g.provider.prompts);start=time.monotonic();action()
        samples.append({'sequence':len(samples)+1,'action':label,'synthetic_wall_seconds':time.monotonic()-start,'source_reads':port.reads-reads,'model_calls':len(g.provider.prompts)-models,'state':s.rows('SELECT state FROM am_inbox ORDER BY rowid DESC LIMIT 1')[0]['state']})
        assert samples[-1]['state']=='done' and samples[-1]['model_calls']==0
    observe('员工打开目录',lambda:ask(ux))
    captures['employee-directory']=json.loads(text(ux))
    actions=[('打开项目','project',{}),('人员','project',{'section':'people'}),('计划','project',{'section':'dates'}),('待办','project',{'section':'todos'}),('进展','project',{'section':None}),('返回目录','projects',{}),('下一页','projects',{'offset':1}),('上一页','projects',{'offset':0}),('最近查看','recent',{}),('全部项目','projects',{})]
    for n in range(29):
        label,page,overrides=actions[n%len(actions)]
        observe(label,lambda p=page,o=overrides:staff_click(ux,p,overrides=o))
        if n==1:captures['employee-detail']=json.loads(text(ux))
    assert len(samples)==30 and all(r['source_reads']==0 for r in samples[1:])
    ask(ux,user='ou_a',number=2)
    click(ux,'work',chat='oc_ou_a');captures['owner-followups']=json.loads(text(ux))
    click(ux,'projects',chat='oc_ou_a');click(ux,'project',chat='oc_ou_a');click(ux,'remind',chat='oc_ou_a');captures['owner-form']=json.loads(text(ux))
    click(ux,'preview_reminder',chat='oc_ou_a',form=form(ux));captures['owner-preview']=json.loads(text(ux))
    click(ux,'confirm_reminder',chat='oc_ou_a');plan=s.rows('SELECT * FROM reminder_plans')[0]
    clock.now=plan['next_at'];am.scheduler.scan();o=s.rows('SELECT * FROM reminder_occurrences')[0]
    s.execute("UPDATE reminder_occurrences SET state='sent',message_id='om_feedback',readback_state='verified' WHERE id=?",(o['id'],))
    feedback(ux,o,'synthetic-missing-date','eta','合成反馈说明，等待补齐日期')
    captures['employee-feedback']=json.loads(text(ux))
    (OUT/'cards').mkdir(parents=True,exist_ok=True)
    for name,value in captures.items():(OUT/'cards'/f'{name}.json').write_text(json.dumps({'layer':'synthetic_renderer_example','card':value},ensure_ascii=False,indent=2)+'\n')
    (OUT/'synthetic-thirty-actions.json').write_text(json.dumps({'layer':'synthetic_original_code_and_store_fake_platform','sample_count':30,'platform_performance_claim':False,'identity_cache_seconds':600,'observations':samples},ensure_ascii=False,indent=2)+'\n')
