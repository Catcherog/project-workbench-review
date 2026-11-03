"""Five audit behaviors with the actual R2 finalizer present and enabled/off.

The original coordinator remains in place; only its synthetic provider emits
schema-valid test responses. No real model or configuration is touched.
"""
import json
from types import SimpleNamespace
import pytest
from test_harness_host import harness, convo, ux, service, am_rig, base_rig
import test_harness_regressions as cases
from am_conversation.rewrite_host import OwnerPrivateRewrite

CASES=[getattr(cases,name) for name in sorted(dir(cases)) if name.startswith('test_F')]


@pytest.mark.parametrize('mode',['off','enforce'])
@pytest.mark.parametrize('case',CASES,ids=lambda case:case.__name__.split('_')[1])
def test_five_with_r2_finalizer(harness,monkeypatch,mode,case):
    conv,h=harness
    h.bridge.agent.output_finalizer=OwnerPrivateRewrite(h.bridge,{'mode':mode,'max_seconds':30.0})
    original=conv[1].complete
    def complete(prompt,**kw):
        if 'contract_fingerprint' in kw.get('json_schema',{}).get('properties',{}):
            payload=json.loads(prompt.split('数据如下：\n',1)[1])
            candidate={'contract_fingerprint':payload['contract_fingerprint'],'lead_in':'record','groups':[
                {'joiner':'semicolon','items':[{'claim_id':c['claim_id'],'variant':min(1,len(c['variants'])-1)} for c in payload['claims']]}]}
            conv[1].prompts.append(prompt)
            return SimpleNamespace(text=json.dumps(candidate,ensure_ascii=False),model='synthetic-json',elapsed=.01)
        if not conv[1].outputs:
            conv[1].outputs.append({'type':'answer','text':'按当前来源记录说明。'})
        return original(prompt,**kw)
    monkeypatch.setattr(conv[1],'complete',complete)
    case(harness)
