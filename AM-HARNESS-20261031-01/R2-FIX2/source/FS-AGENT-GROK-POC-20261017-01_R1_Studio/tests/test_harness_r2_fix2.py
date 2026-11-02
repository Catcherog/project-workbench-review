"""The six FIX2 audit behaviors with the real R2 finalizer, synthetic I/O."""
import json
from types import SimpleNamespace
import pytest
from test_harness_host import harness, convo, ux, service, am_rig, base_rig
from am_conversation.rewrite_host import OwnerPrivateRewrite
import test_history_dynamic_dependency as history
import test_knowledge_unknown_commit as knowledge
import test_running_expiry_notice as timeout

CASES=[('history_prefetch',history.test_project_answer_source_versions_cover_dynamic_reads,{'mode':'prefetch'}),
       ('history_dynamic',history.test_project_answer_source_versions_cover_dynamic_reads,{'mode':'dynamic'}),
       ('propose_unknown',knowledge.test_unknown_knowledge_commit_preserves_quarantine,{'tool':'propose_knowledge'}),
       ('report_unknown',knowledge.test_unknown_knowledge_commit_preserves_quarantine,{'tool':'record_report'}),
       ('direct_approval',knowledge.test_direct_knowledge_approval_is_fenced_at_commit,{}),
       ('running_timeout',timeout.test_running_task_is_not_reported_as_unstarted_queue_timeout,{})]

@pytest.mark.parametrize('mode',['off','enforce'])
@pytest.mark.parametrize('label,case,options',CASES,ids=[x[0] for x in CASES])
def test_fix2_with_r2(harness,monkeypatch,mode,label,case,options):
    conv,h=harness;h.bridge.agent.output_finalizer=OwnerPrivateRewrite(h.bridge,{'mode':mode,'max_seconds':30.0})
    original=conv[1].complete
    def complete(prompt,**kw):
        if 'contract_fingerprint' in kw.get('json_schema',{}).get('properties',{}):
            payload=json.loads(prompt.split('数据如下：\n',1)[1])
            candidate={'contract_fingerprint':payload['contract_fingerprint'],'lead_in':'record','groups':[
                {'joiner':'semicolon','items':[{'claim_id':c['claim_id'],'variant':min(1,len(c['variants'])-1)} for c in payload['claims']]}]}
            conv[1].prompts.append(prompt)
            return SimpleNamespace(text=json.dumps(candidate,ensure_ascii=False),model='synthetic-json',elapsed=.01)
        return original(prompt,**kw)
    monkeypatch.setattr(conv[1],'complete',complete)
    args=dict(options)
    if label in ('propose_unknown','report_unknown','direct_approval'):args['monkeypatch']=monkeypatch
    case(harness,**args)
