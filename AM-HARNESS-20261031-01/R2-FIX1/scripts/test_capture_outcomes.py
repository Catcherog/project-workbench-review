"""Capture only real production tool/adapter results with synthetic external I/O."""
from pathlib import Path
import json
from types import SimpleNamespace
import pytest
from test_harness_response_v2 import response,presentations
from test_harness_host import harness,convo,ux,service,am_rig,base_rig,incoming,execute,call,answer,project

FAMILIES=['query','analysis','followup','worknote','knowledge','document','approval','sending','schedule','control','partial','unknown']

@pytest.mark.parametrize('family',FAMILIES)
def test_capture(response,family):
    conv,h=response;am,g,s,api,clock,port=conv[0];p=project(conv)
    if family=='query':question='需求75关键日期';execute(response,question)
    elif family in ('analysis','partial'):
        facts=[{'fact_id':'synthetic-'+str(i),'subject_id':p,'field':'progress','value':('预计明天完成，尚未验收。' if i==0 else '另一来源的尺寸仍待确认。'), 'assertion_type':'reported','evidence':{'source_id':'synthetic-source','object_id':str(i),'version':'1'}} for i in range(2 if family=='analysis' else 10)]
        info=SimpleNamespace(store=SimpleNamespace(access_version=lambda:'synthetic-info-v1'),query=lambda row,subject:{'facts':facts,'coverage':{'processing_pending':family=='partial','sources':[]},'gaps':[],'version':'1'})
        from types import MethodType
        from am_information import AMInformation
        info.am=am;info.evidence_bundle=MethodType(AMInformation.evidence_bundle,info)
        am.information=info
        question='读取需求75信息并解释覆盖范围'
        execute(response,question,[call('read_information',{'project_id':p,'limit':6}),answer('预计明天完成，尚未验收。')])
    elif family in ('followup','worknote','knowledge'):
        tool,args,question={
          'followup':('create_followup',{'project_id':p,'description':'合成试样确认'},'为需求75登记跟进'),
          'worknote':('save_work_note',{'project_id':p,'title':'合成样品照片'},'为需求75保存笔记'),
          'knowledge':('propose_knowledge',{'kind':'rule','content':'合成包装变更前核对尺寸。'},'把这条合成规则保存为知识候选')
        }[family]
        execute(response,question,[call(tool,args)])
    elif family=='document':
        execute(response,'建立合成章程',[call('edit_document',{'operation':'create','kind':'charter'})]);d=s.rows('SELECT * FROM logic_drafts')[0]
        question='生成这份合成章程'
        execute(response,question,[call('edit_document',{'operation':'generate','draft_id':d['id'],'version':d['revision']})])
    elif family=='schedule':
        from datetime import datetime,timedelta
        from fs_agent.scheduler import TZ
        at=(datetime.fromtimestamp(clock(),TZ)+timedelta(minutes=10)).isoformat()
        question='在'+at+'提醒我合成试样确认'
        execute(response,question,[call('schedule_reminder',{'target':'self','body':'合成试样确认','frequency':'once','at':at})])
        a=s.rows('SELECT id,version FROM am_harness_runs ORDER BY created DESC LIMIT 1') if False else None
        with h.bridge.store._connection() as db:a=dict(db.execute('SELECT * FROM conversation_actions ORDER BY created_at DESC LIMIT 1').fetchone())
        question='确认执行 '+a['id']+' v'+str(a['version']);execute(response,question)
    else:
        question='准备给我发送合成通知'
        execute(response,question,[call('send_message',{'target':'self','body':'合成试样通知'})])
        with h.bridge.store._connection() as db:a=dict(db.execute('SELECT * FROM conversation_actions ORDER BY created_at DESC LIMIT 1').fetchone())
        if family in ('sending','unknown'):
            if family=='unknown':api.verify_allowed=False
            question='确认执行 '+a['id']+' v'+str(a['version']);execute(response,question)
        elif family=='control':question='取消 '+a['id'];execute(response,question)
    out=presentations(h)[-1]
    target=Path(__file__).resolve().parents[1]/'input/production-outcomes';target.mkdir(exist_ok=True)
    path=target/(family+'.json')
    assert not path.exists(),'frozen captured input already exists'
    path.write_text(json.dumps({'family':family,'question':question,'capture':'real_host_tools_synthetic_ports','outcome':out['outcome'],'native_text':conv[0][3].sent[-1]['body'] if conv[0][3].sent else None},ensure_ascii=False,indent=2)+'\n')
