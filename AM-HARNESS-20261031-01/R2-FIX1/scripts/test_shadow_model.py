"""One real-Qwen offline replay of a native shadow capture, after the fixed batch."""
from pathlib import Path
import hashlib,json,time
from am_response.pipeline import ResponsePipeline
from am_response.evaluation import replay_frozen
from am_response.semantics import PROFILE
from model_proxy import OriginalCoordinatorProxy
from test_harness_response_v2 import presentations
from test_harness_host import harness,convo,ux,service,am_rig,base_rig,incoming,execute,call,answer,project
TASK=Path(__file__).resolve().parents[1]

def test_real_offline_shadow(harness):
    files=list((TASK/'evidence/full-model').glob('*.json'))
    assert len(files)==288,'Do not add a model call during the timed batch'
    conv,h=harness
    agent=h.bridge.agent
    from types import SimpleNamespace,MethodType
    from am_information import AMInformation
    am=conv[0][0];project_id=project(conv)
    facts=[{'fact_id':'shadow-fact','subject_id':project_id,'field':'progress','value':'预计明天完成，尚未验收。','assertion_type':'reported','evidence':{'source_id':'synthetic-shadow-source','object_id':'1','version':'1'}}]
    info=SimpleNamespace(am=am,store=SimpleNamespace(access_version=lambda:'synthetic-shadow-v1'),query=lambda row,subject:{'facts':facts,'coverage':{'processing_pending':False,'sources':[]},'gaps':[],'version':'1'})
    info.evidence_bundle=MethodType(AMInformation.evidence_bundle,info);am.information=info
    question='读取需求75信息并解释完成与验收状态'
    def original_turns():return [call('read_information',{'project_id':project_id,'limit':6}),answer('预计明天完成，尚未验收。')]
    agent.response_pipeline=ResponsePipeline({'mode':'legacy'},binding=h.bridge.response_binding,targets=lambda c:h.bridge._current(c)['project_catalog'],clock=h.s.clock)
    n0=len(conv[1].prompts);execute(harness,question,original_turns())
    legacy=conv[0][3].sent[-1]['body'];legacy_calls=len(conv[1].prompts)-n0
    agent.response_pipeline=ResponsePipeline({'mode':'shadow','profile_version':PROFILE,'families':['analysis']},binding=h.bridge.response_binding,targets=lambda c:h.bridge._current(c)['project_catalog'],clock=h.s.clock)
    n0=len(conv[1].prompts);execute(harness,question,original_turns())
    shadow=conv[0][3].sent[-1]['body'];shadow_calls=len(conv[1].prompts)-n0
    stored=presentations(h)[-1];record=stored['replay_input']
    assert legacy==shadow and legacy_calls==shadow_calls and stored['observation_kind']=='offline_replay_pending'
    before=len(conv[0][3].sent);frozen_hash=hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    proxy=OriginalCoordinatorProxy('SYN-ANA-02');started=time.monotonic()
    try:
        result=replay_frozen(proxy,record,settings={'mode':'enforce','profile_version':PROFILE,'families':['analysis']},clock=h.s.clock)
    except Exception as exc:
        result={'observation_kind':'offline_replay','attempted':bool(proxy.records),'candidate':None,'accepted':False,'adopted':False,'reason':type(exc).__name__+': '+str(exc),'actual_delivery':False,'business_calls':0}
    assert len(conv[0][3].sent)==before
    assert hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True).encode()).hexdigest()==frozen_hash
    assert result['observation_kind']=='offline_replay' and result['attempted'] and not result['adopted']
    out={'source_commit':json.loads((TASK/'input/evaluation-lock.json').read_text())['source_commit'],'layer':'native_shadow_capture_synthetic_business_real_qwen_offline_replay','freeze_hash':frozen_hash,'record':record,'legacy_display':legacy,'shadow_display':shadow,'legacy_main_calls':legacy_calls,'shadow_main_calls':shadow_calls,'offline_model_calls':proxy.records,'seconds':time.monotonic()-started,'result':result,'business_calls_during_replay':0,'deliveries_during_replay':len(conv[0][3].sent)-before,'actual_platform_delivery':False,'naturalness':'not_evaluated'}
    (TASK/'evidence/shadow-offline-original.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
