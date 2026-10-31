"""Nonempty native tool paths keep their original rounds, effects and display."""
from pathlib import Path
from dataclasses import replace
import json
import pytest
from test_harness_host import harness,convo,ux,service,am_rig,base_rig,incoming,execute,call,project
from test_harness_response_v2 import presentations
from am_response.pipeline import ResponsePipeline

@pytest.mark.parametrize('mode',['legacy','shadow'])
def test_native_write_trajectory(harness,mode):
    conv,h=harness;native=[];tool=h.bridge.registry._tools['create_followup'];handler=tool.handler
    def observed(*args):
        result=handler(*args);native.append({'operation':'create_followup','result':result});return result
    h.bridge.registry._tools['create_followup']=replace(tool,handler=observed)
    h.bridge.agent.config=replace(h.bridge.agent.config,goal_tracking=True)
    h.bridge.agent.response_pipeline=ResponsePipeline({'mode':mode},binding=h.bridge.response_binding,targets=lambda c:h.bridge._current(c)['project_catalog'],clock=h.s.clock)
    p=project(conv)
    execute(harness,'为需求75分别登记跟进：确认油脂交期；核对测试排期',[
        call('create_followup',{'project_id':p,'description':'确认油脂交期'}),
        call('create_followup',{'project_id':p,'description':'核对测试排期'})])
    shown=conv[0][3].sent[-1]['body'];expected='\n'.join(x['result']['message'] for x in native)
    assert len(native)==len(conv[1].prompts)==2
    assert len(h.s.rows('SELECT * FROM action_items'))==2
    assert shown==expected
    if mode=='shadow':
        observation=presentations(h)[-1]
        assert observation['replay_input']['legacy_text']==shown
        assert observation['observation_kind']=='offline_replay_pending' and observation['presentation_calls']==0
    out={'mode':mode,'layer':'native_tools_synthetic_model_and_platform','tool_sequence':[x['operation'] for x in native],'main_model_rounds':len(conv[1].prompts),'business_objects':2,'shown_body':shown,'exact_original_tool_reply':shown==expected,'live_qwen_calls':0,'actual_platform_delivery':False}
    folder=Path(__file__).resolve().parents[1]/'evidence/shadow-parity';folder.mkdir(exist_ok=True)
    (folder/(mode+'.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
