"""Regressions discovered by R9 native validation; synthetic platform/model I/O."""
from types import SimpleNamespace
import time
from fs_agent.document_standards import SharedProvider
from test_harness_host import harness,convo,ux,service,am_rig,base_rig,incoming
from test_gateway import drain


def test_document_uses_native_transport_without_extending_remaining_budget():
    calls=[]
    def complete(prompt,**options):
        calls.append(options)
        return SimpleNamespace(text='{}',elapsed=.01)
    provider=SharedProvider(SimpleNamespace(complete=complete),guard=lambda:True,
                            deadline=time.monotonic()+10)
    provider.complete('synthetic',run_id='a'*32,timeout=120,max_tokens=4096,json_schema={})
    assert calls[0]['native_chat'] is True
    assert 0<calls[0]['timeout']<=10
    assert calls[0]['max_tokens']==4096 and calls[0]['run_id']=='a'*32


def test_pause_notice_names_the_model_without_replaying_or_rewriting_unknown(harness):
    conv,h=harness;am,g,s,api,clock,port=conv[0]
    s.set_meta('provider_pause','STOP_UNKNOWN')
    row=incoming(harness,'请解释合成测试条件')
    ident=h.admit(row);result=h.run_once()
    assert result.status=='unknown'
    saved=s.rows('SELECT * FROM am_harness_runs WHERE id=?',(ident,))[0]
    assert saved['error']=='MODEL_PAUSED'
    drain(g)
    assert any('模型暂时不可用' in (r['body'] or '') for r in s.rows('SELECT body FROM outbox'))
    assert s.rows('SELECT state FROM am_harness_runs WHERE id=?',(ident,))[0]['state']=='unknown'
    assert not conv[1].prompts
