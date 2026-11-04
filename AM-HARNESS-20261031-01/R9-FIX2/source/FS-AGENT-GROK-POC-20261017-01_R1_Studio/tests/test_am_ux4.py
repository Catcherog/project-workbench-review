"""UX4 observable isolation, latency and transport contracts."""
import json
import threading
import time
import pytest
from test_am_ux1 import ux,service,am_rig,base_rig,click,latest,text
from test_am_ux3 import ask
from test_gateway import event,drain
from am_query import QueryIdentityCache
from group_ledger import LedgerError,FeishuLedgerPort


def group_ask(ux,q='需求75谁负责',user='ou_staff',n=1,parent=None,thread=None):
    am,g,s,api,clock,port=ux
    port.disclosure={'oc_group':['需求75']}
    p=event(q,user=user,number=n)
    p['event']['message'].update(chat_id='oc_group',chat_type='group',parent_id=parent,thread_id=thread,
        create_time=str(int(clock()*1000)),content=json.dumps({'text':'@_user_1 '+q}),
        mentions=[{'key':'@_user_1','id':{'open_id':g.config.bot_open_id}}])
    assert am.ingest(p)==(True,True);am.step();drain(g)
    return s.rows('SELECT * FROM am_inbox ORDER BY rowid DESC LIMIT 1')[0]


def group_open(ux,user,n=10,c=None):
    am,g,s,api,clock,port=ux
    c=c or s.rows('SELECT * FROM am_group_cards ORDER BY rowid DESC LIMIT 1')[0]
    p={'header':{'app_id':g.config.app_id,'tenant_key':g.config.tenant_key,'event_id':'open'+str(n),'event_type':'card.action.trigger'},
       'event':{'operator':{'open_id':user},'context':{'open_chat_id':c['chat'],'open_message_id':c['message_id']},'action':{'value':{'flow':'am_group_open','nonce':c['nonce']}}}}
    assert am.ingest(p)==(True,True);am.step();drain(g)
    return latest(ux)


def bind_dm(ux,user,c):
    ux[1].reminders.port.read=lambda mid:{'chat_id':'oc_'+user,'sender_id':ux[1].config.bot_open_id}
    click(ux,'project',actor=user,chat='oc_'+user,c=c,overrides={'section':'people'})


def test_same_lease_and_snapshot_group_explicit_queries_no_model(ux):
    am,g,s,api,clock,port=ux;calls=[]
    port.authorize_user=lambda u:calls.append(u)
    am.query_identity.close();am.query_identity=QueryIdentityCache(port.authorize_user,600)
    group_ask(ux)
    assert 'AR1测试甲' in text(ux) and '需求76' not in text(ux)
    assert '私聊继续' in text(ux) and '发起跟进' not in text(ux)
    group_ask(ux,q='需求75下一步',n=2)
    assert len(calls)==1 and port.reads==1 and port.guards==0 and not g.provider.prompts
    assert all(r['chat_type']=='group' for r in api.sent)


def test_cross_actor_quote_uses_public_bot_reference_not_others_focus(ux):
    group_ask(ux)
    ref=ux[2].rows('SELECT message_id FROM am_group_refs')[0]['message_id']
    group_ask(ux,q='那谁负责',user='ou_other',n=2,parent=ref,thread='thread_b')
    assert 'AR1测试甲' in text(ux)
    group_ask(ux,q='那谁负责',user='ou_third',n=3)
    assert 'AR1测试甲' not in text(ux)
    group_ask(ux,q='那谁负责',user='ou_other',n=4,parent='om_unknown')
    assert 'AR1测试甲' not in text(ux)


def test_group_private_continuation_per_actor_retains_source_scope(ux):
    group_ask(ux)
    public=ux[2].rows('SELECT * FROM am_group_cards')[0]
    original=ux[3].sent[0]['body']
    a=group_open(ux,'ou_staff',10,public);bind_dm(ux,'ou_staff',a)
    assert 'AR1测试甲' in text(ux)
    click(ux,'projects',actor='ou_staff',chat='oc_ou_staff')
    assert '共 1 项' in text(ux) and '需求76' not in text(ux)
    a_view=latest(ux)
    b=group_open(ux,'ou_other',11,public);bind_dm(ux,'ou_other',b)
    assert a_view['actor']=='ou_staff' and latest(ux)['actor']=='ou_other'
    assert ux[3].sent[0]['body']==original
    assert len([r for r in ux[3].sent if r['chat_type']=='group'])==1
    assert not ux[2].rows('SELECT * FROM action_items')
    ux[-1].disclosure.clear()
    before=len(ux[3].sent)
    click(ux,'projects',actor='ou_other',chat='oc_ou_other')
    assert not any('需求75' in r['body'] for r in ux[3].sent[before:])


def test_transient_refresh_keeps_original_deadline_but_negative_revokes():
    error=[None]
    def check(u):
        if error[0]:raise LedgerError(error[0])
    cache=QueryIdentityCache(check,600)
    try:
        cache.verify('ou_a');deadline=cache.entries['ou_a']
        error[0]='PLATFORM_READ_UNAVAILABLE'
        with pytest.raises(LedgerError):cache._refresh('ou_a')
        assert cache.entries['ou_a']==deadline;cache.verify('ou_a')
        cache.entries['ou_a']=time.monotonic()-1
        with pytest.raises(LedgerError):cache.verify('ou_a')
        cache.entries['ou_a']=deadline;error[0]='QUESTIONER_NOT_ACTIVE'
        with pytest.raises(LedgerError):cache._refresh('ou_a')
        assert not cache.valid('ou_a')
    finally:cache.close()


def test_root_identity_no_tree_and_subtree_lease_does_not_stack():
    port=FeishuLedgerPort(None,app_id='a',tenant_key='t',bot_open_id='b',department_root_id='od-root')
    department=['od-root'];calls=[]
    def get(uri,q):
        calls.append(uri)
        if '/users/' in uri:return {'user':{'open_id':'ou_a','status':{'is_activated':True},'department_ids':department}}
        return {'items':[{'open_department_id':'od-child'}]}
    port.get=get;cache=QueryIdentityCache(port.authorize_private_user,600)
    try:
        cache.verify('ou_a');assert len(calls)==1
        department[:]=['od-child'];cache.entries.clear();port.prewarm_directory().result(2)
        port.directory['valid_until']=time.monotonic()+400
        cache.verify('ou_a');assert cache.entries['ou_a']<=port.directory['valid_until']
    finally:cache.close();port.identity_pool.shutdown(wait=True)


def test_outbox_wakes_only_after_commit_and_rollback_never_wakes(ux):
    am,g,s,api,clock,port=ux;events=[]
    s.outbox_wakeup=lambda:events.append(len(s.rows('SELECT * FROM outbox')))
    row={'app':'a','tenant':'t','user':'u','chat':'c','chat_type':'p2p','expires':clock()+100}
    with s.tx() as c:
        s.add_outbox(row,text='test',conn=c);assert not events
    assert events==[1]
    with pytest.raises(ValueError),s.tx() as c:
        s.add_outbox(row,text='rollback',conn=c);raise ValueError()
    assert events==[1]


def test_loading_not_yet_published_is_coalesced(ux):
    am,g,s,api,clock,port=ux
    am.query_scope={'users':{'ou_staff':['需求75']}}
    entered=threading.Event();release=threading.Event();read=port.read
    def slow():entered.set();assert release.wait(3);return read()
    port.read=slow;am.background_enabled=True
    try:
        ask(ux,deliver=False);assert entered.wait(1)
        release.set();am.snapshots.future.result(2);am.step();drain(g)
        assert len(api.sent)==1 and '资料读取中' not in text(ux)
        assert s.rows("SELECT 1 FROM outbox WHERE error='LOADING_COALESCED'")
    finally:release.set();am.background_enabled=False


def direct_payload(ux,c,page,event_id,**match):
    actions=json.loads(c['snapshot'])['actions'];action=next(k for k,v in actions.items() if v['page']==page and all(v.get(a)==b for a,b in match.items()))
    return {'header':{'app_id':ux[1].config.app_id,'tenant_key':ux[1].config.tenant_key,'event_id':event_id,'event_type':'card.action.trigger'},
      'event':{'operator':{'open_id':c['actor']},'context':{'open_chat_id':c['chat'],'open_message_id':c['message_id']},'action':{'value':{'flow':'am_self','nonce':c['nonce'],'action':action}}}}


def test_direct_return_is_local_and_next_nonce_proves_applied(ux):
    am,g,s,api,clock,port=ux;am.query_scope={'users':{'ou_staff':['需求75']}}
    am.query_identity.close();am.query_identity=QueryIdentityCache(port.authorize_user,600)
    am.query_settings['direct_return_enabled']=True
    ask(ux);old=latest(ux);before=len(api.sent)
    port.authorize_user=lambda u:pytest.fail('hot callback must not read identity')
    port.read=lambda:pytest.fail('hot callback must not read source')
    p=direct_payload(ux,old,'project','direct1');reply=am.direct_query_response(p)
    assert reply['card']['type']=='raw';drain(g);assert len(api.sent)==before
    assert s.rows("SELECT 1 FROM outbox WHERE state='unknown' AND error='CALLBACK_APPLICATION_UNKNOWN'")
    assert am.direct_query_response(p)==reply
    new=latest(ux);p2=direct_payload(ux,new,'project','direct2',section='people')
    second=am.direct_query_response(p2);assert 'AR1测试甲' in json.dumps(second,ensure_ascii=False)
    assert s.rows("SELECT 1 FROM am_latency_anchors WHERE client IS NOT NULL AND verify_state='observed_next_nonce'")
    assert 'card' not in am.direct_query_response(p)  # Never replace a later page with replay.
    assert len(api.sent)==before


def test_direct_return_cold_identity_and_public_button_stay_async(ux):
    am=ux[0];am.query_scope={'users':{'ou_staff':['需求75']}};am.query_settings['direct_return_enabled']=True
    ask(ux);payload=direct_payload(ux,latest(ux),'project','cold')
    assert am.direct_query_response(payload) is None
    assert not ux[2].rows("SELECT 1 FROM am_inbox WHERE id='cold'")


def test_group_action_word_never_becomes_project_query(ux):
    group_ask(ux,q='发送需求75进展给工程师')
    assert '操作请求' in text(ux) and 'AR1测试甲' not in text(ux)
    assert ux[-1].reads==0 and not ux[1].provider.prompts


def test_create_receipt_binds_group_private_view_without_second_read(ux):
    group_ask(ux)
    send=ux[3].send
    def actual(row,guard):
        mid=send(row,guard)
        if row['chat_type']=='p2p':row['_delivered_chat_id']='oc_ou_staff'
        return mid
    ux[3].send=actual
    c=group_open(ux,'ou_staff')
    assert c['chat']=='oc_ou_staff'
    ux[1].reminders.port.read=lambda mid:pytest.fail('binding is already in the CREATE receipt')
    click(ux,'project',actor='ou_staff',chat='oc_ou_staff',c=c,overrides={'section':'people'})
    assert 'AR1测试甲' in text(ux)


def test_refresh_existing_page_sends_only_final_result(ux):
    am,g,s,api,clock,port=ux;am.query_scope={'users':{'ou_staff':['需求75']}}
    ask(ux);count=len(api.sent);entered=threading.Event();release=threading.Event();read=port.read
    def slow():entered.set();assert release.wait(3);return read()
    port.read=slow;am.background_enabled=True
    try:
        click(ux,'refresh',actor='ou_staff',chat='oc_ou_staff')
        assert entered.wait(1) and len(api.sent)==count
        release.set();am.snapshots.future.result(2);am.step();drain(g)
        assert len(api.sent)==count+1 and '资料读取中' not in text(ux)
    finally:release.set();am.background_enabled=False
