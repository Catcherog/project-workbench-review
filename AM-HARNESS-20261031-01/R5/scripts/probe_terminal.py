"""Actual R5 _finish + original Qwen transport; isolated synthetic business store."""
from pathlib import Path
from types import SimpleNamespace
import json,sys,time,uuid,os,tempfile,hashlib
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1]
sys.path.insert(0,str(TASK/'worktree/am-conversation-r1/src'))
from am_conversation.engine import ConversationAgent
from am_conversation.model import ScriptedModel
from am_conversation.store import ConversationStore
from am_conversation.tools import Tool,ToolRegistry,obj
from am_conversation.types import AccessContext,ModelTurn,ToolCall
from am_conversation.terminal import TerminalExpression,coordinator_provider
from am_response.pipeline import ResponsePipeline
cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text());poc=json.loads(Path(cfg['poc_config']).read_text())
queue=Path(poc['service']['root_directory'])/'state/am-conversation-r2'
calls=[]
class Proxy:
    def complete(self,prompt,**kw):
        label='r5-integrate-'+uuid.uuid4().hex
        request={'operation':'task_model_probe','case':'SYN-QRY-01','expires_at':time.time()+150,
            'model_request':{'prompt':prompt,'json_schema':kw['json_schema'],'max_tokens':kw['max_tokens'],'timeout':kw['timeout']}}
        target=queue/'requests'/(label+'.json');temp=target.with_suffix('.tmp');fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as f:json.dump(request,f,ensure_ascii=False)
        temp.replace(target);start=time.monotonic();result=queue/'results'/(label+'.json')
        while not result.exists() and time.monotonic()-start<130:time.sleep(.2)
        if not result.exists():raise RuntimeError('STOP_UNKNOWN')
        data=json.loads(result.read_text());calls.append({'request':request,'result':data})
        
        expected=json.loads((TASK/'private/run-001/queue.real.json').read_text())
        assert data['original_host_pid']==expected['expected_consumer_pid']
        assert data['label']==label and data['operation']=='task_model_probe'
        assert data['model']==poc['provider']['model'] and data['model_digest']==poc['provider']['model_digest']
        assert data['original_coordinator'] is True and data['synthetic_only'] is True and data['external_business_calls']==0
        if not data['ok']:raise RuntimeError(data['error'])
        return SimpleNamespace(text=data['text'],model=data['model'])
with tempfile.TemporaryDirectory(prefix='r5-engine-') as temp:
    ctx=AccessContext('synthetic-tenant','synthetic-app','owner','dm',is_owner=True,all_projects=True,
                      content_expires_at=time.time()+300,source_access_version='synthetic-v1')
    store=ConversationStore(Path(temp)/'conversation.sqlite3');registry=ToolRegistry()
    registry.register(Tool('read_project','synthetic read',obj({}),lambda *a:{'id':'synthetic-project','title':'演示样件项目','fields':{'负责人':'林工'},'has_more':False}))
    task=ScriptedModel([ModelTurn(tool_calls=(ToolCall('r','read_project',{}),)),ModelTurn(text='旧答复：负责人是林工。')])
    observed=[];terminal=TerminalExpression({'mode':'enforce','generation_budget_s':25},provider=coordinator_provider(Proxy()),observer=observed.append)
    agent=ConversationAgent(task,store,registry,response_pipeline=ResponsePipeline({'mode':'legacy'}),terminal_expression=terminal)
    start=time.monotonic();reply=agent.handle(ctx,'r5-synthetic-normal','演示样件项目谁负责？')
    gateway=terminal.before_enqueue(agent,ctx,reply)
    replay=agent.handle(ctx,'r5-synthetic-normal','演示样件项目谁负责？')
    result={'task_model':'explicit scripted fixture, not a real task-model benchmark','terminal_provider':'real original Qwen coordinator',
        'reply':reply.text,'replay_text_equal':reply.text==replay.text,'real_terminal_calls':len(calls),
        'old_response_mode':agent.response_pipeline.mode,'new_expression_mode':'isolated_enforce_only',
        'collector_reset':terminal.collector.state() is None,'before_enqueue_recheck':gateway is not None,
        'business_delivery':False,'actual_platform_outbox_commit':False,'observations':observed,'calls':calls,
        'elapsed_ms':(time.monotonic()-start)*1000,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (TASK/'evidence/terminal-real-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('observations','calls')},ensure_ascii=False))
    store.close()
