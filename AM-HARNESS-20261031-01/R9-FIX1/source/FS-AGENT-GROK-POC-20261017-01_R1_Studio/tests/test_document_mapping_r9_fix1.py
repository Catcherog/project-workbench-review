import json,time
from types import SimpleNamespace as NS
import pytest
from fs_agent.config import BoundaryError
from fs_agent.document_mapping import map_facts
from fs_agent.document_delivery import discover_targets,render_targets
from fs_agent.document_trace import DocumentTrace
from fs_agent.document_standards import SharedProvider,ProviderControlError
from am_doc_engine.models import AccessContext
from test_document_shared_evidence_r9 import profile,bundle,fact,PROJECT
from test_gateway import rig


def mapped(response):
    return map_facts(profile(),project={'id':'project','title':PROJECT['title'],'code':'IRAD-2099-001'},
        sources=[bundle().document_source(uri='https://example.com/ledger')],
        access=AccessContext('tenant','owner',('project',)),
        session=NS(complete_json=lambda *a:response),source_uri='https://example.com/ledger',
        source_revision='v1',supplied_type='IRAD',compact=True)


def test_compact_mapping_restores_whole_original_and_trusted_qualifiers():
    snapshot=mapped({'complete':True,'matches':[{'f':0,'s':0}]})
    e=next(e for e in snapshot.evidence if e.key=='slot.field')
    assert e.value==fact()['evidence']['quote']
    assert e.source_id=='chat-source' and e.source_revision=='message-v3'
    assert e.state=='reported' and e.qualifiers['attribution']=='工程师反馈'


@pytest.mark.parametrize('response',[
    {'complete':False,'matches':[]},
    {'complete':True,'matches':[{'f':0,'s':99}]},
    {'complete':True,'matches':[{'f':True,'s':0}]},
    {'complete':True,'matches':[{'f':0,'s':0,'quote':'通过'}]},
    {'matches':[]}])
def test_compact_mapping_rejects_incomplete_or_unbound_selection(response):
    with pytest.raises(BoundaryError):mapped(response)


@pytest.mark.parametrize('phase',['resolve','document_identity'])
def test_delivery_diagnostic_names_stage_and_original_code(phase):
    def reject(*a):raise BoundaryError('BUSINESS_DOCUMENT_IDENTITY_UNVERIFIED')
    business=NS(settings={'targets':{'synthetic':{}}},resolve=reject if phase=='resolve' else lambda *a:{'id':'synthetic'},document_identity=reject)
    result=discover_targets(business,{},project_code='IRAD-2099-001',doc_type='charter',guard=lambda:True,deadline=time.monotonic()+2)
    assert result['state']=='unresolved' and result['targets']==[]
    assert result['diagnostics']==[{'alias':'synthetic','stage':phase,'status':'unresolved','error_code':'BUSINESS_DOCUMENT_IDENTITY_UNVERIFIED'}]
    assert '文种' in render_targets(result)


def test_failed_model_call_has_content_free_timing_and_original_error(rig):
    g,s,api,p,clock=rig
    task={'run_id':'a'*32,'expires':clock()+60};d={'id':'d','expires':clock()+60}
    trace=DocumentTrace(s,task,d,{'revision':1},time.monotonic()+10)
    trace.phase('fact_mapping')
    def fail(*a,**kw):raise BoundaryError('MODEL_PAUSED')
    provider=SharedProvider(NS(complete=fail,last_timing=[{'stage':'model_queue_and_locks','seconds':.1}]),
        deadline=time.monotonic()+10,guard=lambda:True,trace=trace)
    with pytest.raises(ProviderControlError) as error:provider.complete('SYNTHETIC_PRIVATE_SOURCE',timeout=120,max_tokens=1536)
    trace.finish(error.value)
    saved=s.rows('SELECT trace FROM amdoc_attempt_traces')[0]['trace']
    assert 'SYNTHETIC_PRIVATE_SOURCE' not in saved
    payload=json.loads(saved);event=next(e for e in payload['events'] if e.get('event')=='model_call')
    assert event['error']=='MODEL_PAUSED' and 0<event['timeout_seconds']<=10
    assert event['max_tokens']==1536 and event['authorization_seconds']>=0
