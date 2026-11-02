import json
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from am_conversation.engine import ConversationAgent
from am_conversation.model import ScriptedModel
from am_conversation.store import ConversationStore
from am_conversation.tools import Tool,ToolRegistry,obj
from am_conversation.types import AccessContext,AgentReply,ModelTurn,ToolCall,ConversationError
from am_conversation.terminal import TerminalExpression,coordinator_provider
from am_response.pipeline import ResponsePipeline
from am_style.contracts import ModelResult,ModelRequest,canonical
from am_style.runtime import StopUnconfirmed


class Presenter:
    def __init__(self):self.calls=[]
    def generate(self,request):
        self.calls.append(request)
        # Explicit fixture; infer no quality conclusion from it.
        return ModelResult('{"text":"林工负责演示项目。"}','fixture','fixture',1)


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=ConversationStore(Path(self.tmp.name)/'db')
        self.ctx=AccessContext('t','a','u','c',is_owner=True,all_projects=True,
                               content_expires_at=time.time()+600,source_access_version='v1')
        self.fence={'revision':1,'cancel_epoch':0,'generation':1}
        self.binding=lambda ctx,event:dict(kind='run',scope=list(ctx.scope),engine_event_id=event,
            origin_event_id=event,source_access_version=ctx.source_access_version,run_id='r',**self.fence)
        self.registry=ToolRegistry();self.provider=Presenter();self.observations=[]
        self.registry.register(Tool('read_project','fixture',obj({}),lambda *a:{'id':'p','title':'演示项目','fields':{'负责人':'林工'},'has_more':False}))
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def agent(self,mode='shadow',turns=None,fastpath=None):
        model=ScriptedModel(turns or [ModelTurn(tool_calls=(ToolCall('1','read_project',{}),)),ModelTurn(text='旧回复')])
        model.protocol=[]
        model.set_response_protocol=lambda x:model.protocol.append(x) or 't'
        model.reset_response_protocol=lambda t:None
        terminal=TerminalExpression({'mode':mode},binding=self.binding,provider=self.provider,observer=self.observations.append)
        agent=ConversationAgent(model,self.store,self.registry,response_pipeline=ResponsePipeline({'mode':'legacy'}),
                                terminal_expression=terminal,fastpath=fastpath)
        return agent,model,terminal
    def test_legacy_collector_does_not_enable_task_protocol_and_shadow_keeps_text(self):
        a,m,t=self.agent();r=a.handle(self.ctx,'e','演示项目谁负责？')
        self.assertEqual(r.text,'旧回复');self.assertEqual(m.protocol,[False])
        self.assertEqual(len(m.calls),2);self.assertEqual(len(self.provider.calls),1)
        self.assertIsNone(t.collector.state());self.assertIsNone(a.response_pipeline.state())
        self.assertTrue(json.loads(r.terminal_json)['outcome']['claims'])
        self.assertFalse(any('host_outcome=' in str(x) for x in m.calls))
    def test_enforce_once_before_history_and_replay_no_calls(self):
        a,m,t=self.agent('enforce');r=a.handle(self.ctx,'e','演示项目谁负责？')
        self.assertEqual('林工负责演示项目。',r.text)
        old=a.handle(self.ctx,'e','演示项目谁负责？')
        self.assertTrue(old.replayed);self.assertEqual(old.terminal_json,r.terminal_json)
        self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(self.store.history(self.ctx)[-1]['content'],r.text)
    def test_off_has_no_collector_or_model_and_preserves_serialization(self):
        a,m,t=self.agent('off');r=a.handle(self.ctx,'e','演示项目谁负责？')
        self.assertEqual(r.text,'旧回复');self.assertIsNone(r.terminal_json)
        self.assertNotIn('terminal_json',r.to_dict());self.assertFalse(self.provider.calls)
    def test_inline_fastpath_zero_model_calls(self):
        a,m,t=self.agent('enforce',fastpath=lambda ctx,event,text:AgentReply(event,'已知结果','fastpath_answered'))
        r=a.handle(self.ctx,'e','谁负责？')
        self.assertEqual(r.text,'已知结果');self.assertEqual(m.calls,[]);self.assertEqual(self.provider.calls,[])
        self.assertEqual(json.loads(r.terminal_json)['prepared']['reason'],'fastpath_no_model')
    def test_independent_fastpath_zero_model_calls(self):
        class Fast:
            def prepare(s,*a):return 'prepared'
            def consume(s,ctx,event,text,p):return AgentReply(event,'已知结果','fastpath_answered')
        a,m,t=self.agent('enforce',fastpath=Fast());r=a.handle_fastpath(self.ctx,'e','谁负责？')
        self.assertEqual(r.text,'已知结果');self.assertEqual(m.calls,[]);self.assertEqual(self.provider.calls,[])
        self.assertIsNone(t.collector.state())
    def test_unknown_scope_qualifier_keeps_legacy(self):
        self.registry._tools['read_project']=replace(self.registry._tools['read_project'],handler=lambda *a:{
            'evidence_bundle':{'claims':[{'id':'f','subject':'p','subject_label':'演示项目','predicate':'负责人','value':'林工','modality':'recorded','scope':'仅试制'}]},'has_more':False})
        a,m,t=self.agent('enforce');r=a.handle(self.ctx,'e','谁负责？')
        self.assertEqual(r.text,'旧回复');self.assertFalse(self.provider.calls)
        self.assertEqual(self.observations[-1]['reason'],'unsupported_qualified_claim')
    def test_gateway_rejects_cancel_fence_after_prepare(self):
        a,m,t=self.agent('enforce');r=a.handle(self.ctx,'e','谁负责？')
        self.assertIsNotNone(t.before_enqueue(a,self.ctx,r));self.fence['cancel_epoch']=1
        with self.assertRaisesRegex(ConversationError,'TERMINAL_FENCE_CHANGED'):t.before_enqueue(a,self.ctx,r)
    def test_gateway_rejects_mutated_text(self):
        a,m,t=self.agent('enforce');r=a.handle(self.ctx,'e','谁负责？')
        with self.assertRaisesRegex(ConversationError,'TERMINAL_HISTORY_MISMATCH'):t.before_enqueue(a,self.ctx,replace(r,text='已经批准'))
    def test_model_stop_unknown_not_fallback_and_context_reset(self):
        def generate(request):raise StopUnconfirmed('STOP_UNKNOWN')
        self.provider.generate=generate;a,m,t=self.agent('enforce')
        with self.assertRaisesRegex(ConversationError,'STOP_UNKNOWN'):a.handle(self.ctx,'e','谁负责？')
        self.assertIsNone(t.collector.state())
    def test_member_never_uses_experimental_presenter(self):
        a,m,t=self.agent('enforce');r=a.handle(replace(self.ctx,is_owner=False),'e','谁负责？')
        self.assertEqual(r.text,'旧回复');self.assertFalse(self.provider.calls)
    def test_callback_uses_original_coordinator_no_tools_and_shared_budget(self):
        calls=[]
        def complete(prompt,**kwargs):
            calls.append((prompt,kwargs));return SimpleNamespace(text='{"text":"结果"}',model='pinned')
        p=coordinator_provider(SimpleNamespace(complete=complete))
        r=p.generate(ModelRequest(canonical([{'role':'user','content':'合成'}]),'f','p',5,120))
        self.assertEqual(r.model,'pinned');self.assertEqual(len(calls),1)
        self.assertEqual(json.loads(calls[0][0])['tools'],[])
        self.assertEqual(calls[0][1]['timeout'],5)
        self.assertEqual(calls[0][1]['max_tokens'],120)
    def test_gateway_rejects_source_revision(self):
        a,m,t=self.agent('enforce');r=a.handle(self.ctx,'e','谁负责？')
        with self.assertRaisesRegex(ConversationError,'TERMINAL_FENCE_CHANGED'):
            t.before_enqueue(a,replace(self.ctx,source_access_version='v2'),r)

    def test_training_wrapper_matches_existing_native_chat_wire_roles(self):
        from am_style.prompt import coordinator_messages
        messages=[{'role':'system','content':'事实合同'},{'role':'user','content':'问题'}]
        wire=coordinator_messages(messages)
        self.assertEqual(len(wire),1);self.assertEqual(wire[0]['role'],'user')
        self.assertEqual(json.loads(wire[0]['content']),{'messages':messages,'tools':[]})

if __name__=='__main__':unittest.main()
