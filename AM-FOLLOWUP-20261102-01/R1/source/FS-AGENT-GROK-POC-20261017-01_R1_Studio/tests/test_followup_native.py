"""Native SQLite/services and real SDK request construction; simulated platform only."""
import copy
import json
from dataclasses import replace
from types import SimpleNamespace as NS
from concurrent.futures import ThreadPoolExecutor
import pytest

from test_am_self_fix1 import service, am_rig, base_rig
from test_gateway import event,drain
from fs_agent.business_port import BusinessPort
from fs_agent.config import BoundaryError
from fs_agent.feishu import SendRejected, SendUnknown
from fs_agent.project_catalog import canonical,digest
from am_followup.followup import FollowupError, ApprovalRequest
from am_info_sync.models import Source,Observation
from am_info_sync.store import Store as InfoStore
from am_info_sync.facts import FactEngine


@pytest.fixture
def native(service,tmp_path):
    am,g,s,api,clock,ledger_port=service
    f=am.followup
    f.port=BusinessPort(g,am.ledger);am.scheduler.port=f.port;f.port.followup_resolver=f.refresh_p2p
    row={'id':'om_owner','app':g.config.app_id,'tenant':g.config.tenant_key,'user':g.config.owner,
         'chat':'oc_dm','chat_type':'p2p','created':clock(),'expires':clock()+86400,'kind':'text','body':'/followup'}
    project=am.projects(row)[0]
    reader=InfoStore(tmp_path/'information.db',clock=lambda:int(clock()*1000));facts=FactEngine(reader)
    source=Source('th2-ledger','ledger_snapshot','ledger-demo',g.config.tenant_key,g.config.owner,
        output_chats=('oc_reminder',),enabled=True,start_ms=0,settings={'subject_id':project['key'],
        'fact_mappings':{'ledger_record':{'value_path':['record'],'quote_path':['quote']}}})
    reader.register_source(source)
    obs=Observation(source.source_id,project['key'],'v1',int(clock()*1000),text='样机已到仓，计划开测，尚未核实实际开测。',
        payload={'record':{'todo':'确认开测'},'quote':'样机已到仓，计划开测，尚未核实实际开测。'})
    reader.record(obs);facts.process(obs,[])
    am.information=NS(store=reader,service=NS(facts=facts,sync_engine=NS(adapters={})),ledger=NS(read=lambda **kw:None))
    target={'bot':g.reminders.port.bot_info,'group':g.reminders.port.group_info,'people':g.reminders.port.people[:1]}
    item=am.items.create(am.owner,'native-item',project_ref=project['key'],description='确认开测',requirements='实际开测证据',assignees=['ou_engineer_a'],source={'target':target})
    members=copy.deepcopy(g.reminders.port.people)
    def get(uri,query=None):
        if uri.endswith('/members'):return {'items':[{'member_id':p['id'],'member_id_type':'open_id','tenant_key':g.config.tenant_key,'name':p['name']} for p in members],'has_more':False}
        user=uri.rsplit('/',1)[-1]
        return {'user':{'open_id':user,'name':'工程师甲' if user=='ou_engineer_a' else '本人','department_ids':['od-demo'],'status':{'is_activated':True}}}
    ledger_port.get=get
    remote={};calls=[];fault={'send':False,'read':False,'wrong_id':False}
    inbound={'message_id':'om_engineer','chat_id':'oc_engineer','sender_id':'ou_engineer_a','sender_type':'user','msg_type':'text','content':{'text':'hello'},'deleted':False,'created_at':clock()}
    remote['om_engineer']=inbound
    s.execute("INSERT INTO am_inbox VALUES(?,?,?,?,?,?,?,?,?,?,'done',NULL)",('om_engineer',g.config.app_id,g.config.tenant_key,'ou_engineer_a','oc_engineer','p2p',clock(),clock()+86400,'hello','text'))
    def create(req):
        p=req.request_body;mid='om_send_'+p.uuid
        calls.append((p.receive_id,p.msg_type,json.loads(p.content),p.uuid))
        remote[mid]={'message_id':mid,'chat_id':'oc_engineer' if p.receive_id=='ou_engineer_a' else p.receive_id,
            'sender_id':g.config.bot_open_id,'sender_type':'app','msg_type':p.msg_type,'content':json.loads(p.content),
            'mentions':[],'deleted':False,'created_at':clock()}
        if fault['send']:raise TimeoutError('synthetic response loss')
        return NS(success=lambda:True,data=NS(message_id=mid))
    api.client=NS(im=NS(v1=NS(message=NS(create=create))))
    def read(mid):
        if fault['read']:raise RuntimeError('synthetic read failure')
        if mid in remote:
            result=copy.deepcopy(remote[mid])
            if fault['wrong_id']:result['message_id']='om_wrong'
            return result
        out=s.rows('SELECT * FROM outbox WHERE message_id=?',(mid,))[0]
        return {'message_id':mid,'chat_id':out['chat'],'sender_id':g.config.bot_open_id,'sender_type':'app','msg_type':'interactive',
            'content':json.loads(out['body']),'deleted':False,'created_at':out['created']}
    g.reminders.port.read=read;g.reminders.port.read_card=read
    yield NS(am=am,g=g,s=s,api=api,clock=clock,f=f,row=row,item=item,reader=reader,facts=facts,source=source,obs=obs,calls=calls,remote=remote,fault=fault,members=members)
    reader.close()


def preview(n,channel='group'):
    nonce=n.f.preview_card(n.row,n.item['id'],channel);drain(n.g)
    return n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]

def click(n,c,action='confirm_send_once',**overrides):
    row=dict(n.row,id='callback_'+str(len(n.s.rows('SELECT * FROM followup_audit'))),kind='card')
    row.update(overrides)
    row['body']=canonical({'value':{'flow':'am_self','nonce':c['nonce'],'action':action},'source_message':c['message_id']})
    card,a=n.am.validate_card(row)
    return n.am.handle_business_card(row,card,a)


def test_actual_card_one_confirmation_native_occurrence_and_replay(native):
    n=native;c=preview(n)
    assert not n.calls and not n.s.rows('SELECT * FROM reminder_occurrences')
    assert '已确认' in click(n,c)
    click(n,c)
    assert len(n.s.rows('SELECT * FROM reminder_plans'))==1
    assert len(n.s.rows('SELECT * FROM reminder_occurrences'))==1
    n.am.scheduler.dispatch();n.am.scheduler.dispatch()
    o=n.s.rows('SELECT * FROM reminder_occurrences')[0]
    assert o['state']=='sent' and o['readback_state']=='verified' and len(n.calls)==1
    assert n.am.items.get(n.item['id'])['state']=='waiting'
    assert n.s.rows('SELECT state FROM followup_intents')[0]['state']=='confirmed'


def test_p2p_and_group_share_business_attention(native):
    n=native;first=preview(n);click(n,first);n.am.scheduler.dispatch()
    second=preview(n,'recipient_p2p');assert '未发送' in click(n,second)
    n.am.scheduler.dispatch();assert len(n.calls)==1


def test_recipient_p2p_preserves_owner_and_exact_chat(native):
    n=native;c=preview(n,'recipient_p2p');click(n,c);n.am.scheduler.dispatch()
    assert n.calls[0][0]=='ou_engineer_a' and n.g.config.owner=='ou_a'
    o=n.s.rows('SELECT * FROM reminder_occurrences')[0];assert o['readback_state']=='verified'
    payload=json.loads(o['payload']);m=copy.deepcopy(n.remote[o['message_id']]);m['chat_id']='oc_wrong'
    assert not n.f.port.verify(payload,m)
    with pytest.raises(BoundaryError,match='OWNER_TARGET_CHANGED'):n.f.port.refresh({'target':{'kind':'owner','user':'ou_engineer_a'}})


@pytest.mark.parametrize('change',['source','acl','policy','item','audience','body'])
def test_precise_dependency_changes_stop_approved_action(native,change):
    n=native;c=preview(n);click(n,c)
    if change=='source':n.reader.record(replace(n.obs,version='v2',occurred_at_ms=n.obs.occurred_at_ms+1,text='新的依据'),authoritative=True)
    if change=='acl':n.reader.register_source(replace(n.source,readers=('user:ou_other',)))
    if change=='policy':n.s.execute('UPDATE followup_disclosures SET revision=revision+1')
    if change=='item':n.am.items.change(n.am.owner,'pause',n.item['id'],1,'pause')
    if change=='audience':n.members.append({'id':'ou_new','name':'新成员'})
    if change=='body':
        o=n.s.rows('SELECT * FROM reminder_occurrences')[0];p=json.loads(o['payload']);p['body']='篡改正文'
        n.s.execute('UPDATE reminder_occurrences SET payload=? WHERE id=?',(canonical(p),o['id']))
    n.am.scheduler.dispatch();assert not n.calls


def test_unrelated_source_does_not_cancel(native):
    n=native;c=preview(n);click(n,c)
    n.reader.register_source(replace(n.source,source_id='unrelated',remote_id='other',settings={'subject_id':'other'}))
    n.am.scheduler.dispatch();assert len(n.calls)==1


@pytest.mark.parametrize('action',['view','modify','stop'])
def test_nonsend_actions_never_approve(native,action):
    n=native;c=preview(n);click(n,c,action)
    assert not n.s.rows('SELECT * FROM followup_intents') and not n.calls
    if action!='view':
        with pytest.raises(FollowupError):click(n,c)


@pytest.mark.parametrize('field,value',[('user','ou_other'),('chat','oc_wrong'),('tenant','other'),('app','other')])
def test_callback_scope_rejected(native,field,value):
    n=native;c=preview(n)
    with pytest.raises((BoundaryError,FollowupError)):click(n,c,**{field:value})
    assert not n.calls and not n.s.rows('SELECT * FROM followup_intents')


def test_preview_without_delivery_cannot_confirm(native):
    n=native;nonce=n.f.preview_card(n.row,n.item['id']);c=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    with pytest.raises(BoundaryError):click(n,c)
    assert not n.calls


def test_returned_wrong_message_id_is_unknown(native):
    n=native;c=preview(n);click(n,c);n.fault['wrong_id']=True;n.am.scheduler.dispatch()
    assert len(n.calls)==1 and n.s.rows('SELECT state FROM followup_intents')[0]['state']=='unknown'


def test_timeout_and_next_round_blocked_no_new_uuid(native):
    n=native;c=preview(n);click(n,c);n.fault['send']=True;n.am.scheduler.dispatch()
    assert len(n.calls)==1 and n.s.rows('SELECT state FROM followup_intents')[0]['state']=='unknown'
    n.fault['send']=False
    # A second backend-approved episode cannot bypass the unresolved send.
    p,t=n.f.prepare(n.row,n.item['id'],'recipient_p2p')
    episode=n.f.coordinator.register_episode(tenant_id=n.f.tenant,task_id=p.draft.task_id,purpose=p.draft.purpose,trigger_key='verified_new_request')
    p=n.f.coordinator.create_preview(n.f.actor(n.row),replace(p.draft,episode_id=episode))
    with pytest.raises(FollowupError,match='prior_delivery_uncertain'):n.f.coordinator.approve(n.f.actor(n.row),p.preview_id,p.token,p.content_hash)
    n.am.scheduler.dispatch();assert len(n.calls)==1


def test_accepted_read_failure_then_exact_reconcile(native):
    n=native;c=preview(n);click(n,c)
    original=n.f.port.reconcile;n.f.port.reconcile=lambda *a:None
    n.am.scheduler.dispatch();o=n.s.rows('SELECT * FROM reminder_occurrences')[0]
    assert o['state']=='sent' and n.s.rows('SELECT state FROM followup_intents')[0]['state']=='unknown'
    n.f.port.reconcile=original;n.am.scheduler.reconcile(o['id'],manual=True)
    assert n.s.rows('SELECT state FROM followup_intents')[0]['state']=='confirmed' and len(n.calls)==1


def test_guard_order_one_shot_and_final_old_guard_rejection(native):
    n=native;t=n.f.p2p('ou_engineer_a');p={'target':t,'body':'合成正文'};order=[]
    n.f.port.send(p,'fixed',lambda:order.append('old') or True,before_send=lambda:order.append('new'))
    assert order==['old','old','new'] and len(n.calls)==1
    order=[]
    def guard():order.append('old');return len(order)==1
    with pytest.raises(SendRejected):n.f.port.send(p,'fixed2',guard,before_send=lambda:order.append('new'))
    assert order==['old','old'] and len(n.calls)==1


def test_context_delivery_does_not_submit_execution_item(native):
    n=native;n.f.bind(n.row,n.item['id']);refs=json.loads(n.f.semantic(n.item['id'])['refs']);ids=[r['fact_id'] for r in refs]
    n.f.record_claim(n.row,n.item['id'],'plan_delivery','delivered',ids)
    view=n.f.view(n.item['id'])
    assert view['fields']['plan_delivery']=='delivered' and not view['business_completed'] and view['business_state']=='waiting'
    with pytest.raises(BoundaryError,match='DELIVERABLE_MISMATCH'):n.f.record_claim(n.row,n.item['id'],'delivery','delivered',ids,subject_key='plan')
    assert n.am.items.get(n.item['id'])['state']=='waiting'


def test_missing_import_fields_retained_as_candidate(native):
    n=native;payload={'producer':'personal','external_id':'one','identity':{},'item':{'description':'记录估时'},'fact_ids':[],'history':[],'history_complete':False}
    ident=n.f.import_candidate(n.row,payload)
    with pytest.raises(BoundaryError):n.f.adopt_candidate(n.row,ident)
    assert n.s.rows('SELECT state FROM followup_candidates')[0]['state']=='candidate'
    assert len(n.s.rows('SELECT * FROM action_items'))==1 and not n.calls


def test_native_legacy_unknown_blocks_even_changed_channel(native):
    n=native;n.f.bind(n.row,n.item['id'])
    n.s.execute('UPDATE action_semantics SET legacy_history=? WHERE item_id=?',(canonical([{'state':'legacy_unknown','action':'old-attempt'}]),n.item['id']))
    with pytest.raises(FollowupError,match='evidence_blocked'):n.f.prepare(n.row,n.item['id'],'recipient_p2p')
    assert not n.calls


def test_original_ingress_and_service_handle_confirmation(native):
    n=native;c=preview(n,'recipient_p2p')
    value={'header':{'app_id':n.g.config.app_id,'tenant_key':n.g.config.tenant_key,'event_id':'native-callback','event_type':'card.action.trigger'},
      'event':{'operator':{'open_id':n.am.owner},'context':{'open_chat_id':'oc_dm','open_message_id':c['message_id']},
               'action':{'value':{'flow':'am_self','nonce':c['nonce'],'action':'confirm_send_once'}}}}
    assert n.am.ingest(value)==(True,True)
    assert n.am.ingest(value)==(True,False)
    n.am.step();assert n.s.rows("SELECT state,error FROM am_inbox WHERE id='native-callback'")==[{'state':'done','error':None}]
    n.am.scheduler.step();assert len(n.calls)==1


def test_recipient_exact_reply_acknowledges_but_never_completes(native):
    n=native;c=preview(n,'recipient_p2p');click(n,c);n.am.scheduler.dispatch()
    o=n.s.rows('SELECT * FROM reminder_occurrences')[0]
    e=event('收到',number=123,user='ou_engineer_a',chat='oc_engineer')
    e['event']['message'].update(parent_id=o['message_id'],create_time=str(int(n.clock()*1000)))
    assert n.am.ingest(e)==(True,True)
    assert n.am.ingest(e)==(True,False)
    n.am.step()
    assert n.s.rows('SELECT kind FROM followup_reply_links')==[{'kind':'acknowledged'}]
    assert n.am.items.get(n.item['id'])['state']=='waiting'
    e=event('已交付全部完成',number=124,user='ou_engineer_a',chat='oc_engineer')
    e['event']['message'].update(parent_id=o['message_id'],create_time=str(int(n.clock()*1000)))
    n.am.ingest(e);n.am.step()
    assert n.am.items.get(n.item['id'])['state']=='waiting'


def test_same_item_second_alias_retains_new_unknown_history(native):
    n=native;n.f.bind(n.row,n.item['id'])
    n.f.bind(n.row,n.item['id'],producer='personal',external_id='external',history=[{'state':'legacy_unknown'}])
    assert len(n.s.rows('SELECT * FROM action_items'))==1
    with pytest.raises(FollowupError):n.f.prepare(n.row,n.item['id'])


def test_p2p_read_access_does_not_grant_disclosure(native):
    n=native;n.reader.register_source(replace(n.source,output_chats=()))
    with pytest.raises(BoundaryError,match='DISCLOSURE_NOT_GRANTED'):n.f.prepare(n.row,n.item['id'],'recipient_p2p')


def test_native_plan_pause_between_approval_and_boundary(native):
    n=native;c=preview(n);click(n,c)
    p=n.s.rows('SELECT * FROM reminder_plans')[0]
    n.am.scheduler.control(n.am.owner,'pause-native',p['id'],p['version'],'pause')
    n.am.scheduler.dispatch();assert not n.calls


def test_expired_actual_card_rejected(native):
    n=native;c=preview(n);n.s.execute('UPDATE am_cards SET expires=? WHERE nonce=?',(n.clock()-1,c['nonce']))
    with pytest.raises(BoundaryError):click(n,c)


def test_unknown_restart_does_not_reset_or_resend(native):
    n=native;c=preview(n);click(n,c);n.fault['send']=True;n.am.scheduler.dispatch()
    from am_followup_host import FollowupHost
    restarted=FollowupHost(n.am)
    restarted.recover_adoptions();n.am.scheduler.dispatch()
    assert len(n.calls)==1 and n.s.rows('SELECT state FROM followup_intents')[0]['state']=='unknown'


def test_stopped_unsent_can_only_resume_with_new_exact_preview(native):
    n=native;c=preview(n);click(n,c);click(n,c,'stop')
    n.am.scheduler.dispatch();assert not n.calls
    newer=preview(n);click(n,newer);n.am.scheduler.dispatch()
    assert len(n.calls)==1
    assert len(n.s.rows('SELECT * FROM reminder_occurrences'))==2


def test_full_exact_new_request_can_follow_confirmed_but_not_repeat_old_round(native):
    n=native;c=preview(n);click(n,c);n.am.scheduler.dispatch()
    nonce=n.f.preview_card(dict(n.row,id='new-owner-request'),n.item['id'],'recipient_p2p',new_round=True)
    drain(n.g);new=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    click(n,new);n.am.scheduler.dispatch();assert len(n.calls)==2


def test_followup_does_not_authorize_ledger_write_or_model_tools(native):
    n=native;before=dict(n.am.flags);c=preview(n);click(n,c);n.am.scheduler.dispatch()
    assert n.am.flags==before and not n.am.flags['ledger_write']
    assert not n.s.rows('SELECT * FROM ledger_write_attempts')
    assert not n.s.rows('SELECT * FROM tasks')


def test_explicit_system_validation_stays_out_of_real_project(native):
    n=native
    from am_info_sync.ingest import record_offline
    n.am.information.service.offline=lambda *a,**kw:record_offline(n.reader,*a,**kw)
    item=n.f.validation_item(n.row,'oc_reminder','ou_engineer_a','group')
    again=n.f.validation_item(n.row,'oc_reminder','ou_engineer_a','group')
    assert item['id']==again['id'] and item['project_ref'].startswith('validation:')
    assert item['project_ref']!=n.item['project_ref']
    n.f.preview_card(n.row,item['id'],body='[AM联调测试] 不涉及真实业务。')
    assert not n.calls and not n.s.rows('SELECT * FROM followup_intents')


@pytest.mark.parametrize('body',['请提交 {测试报告}，参数 {"version": 2}。','请保留双括号 {{样例}}。'])
def test_exact_body_never_interpolated_after_confirmation(native,body):
    n=native;nonce=n.f.preview_card(n.row,n.item['id'],'recipient_p2p',body=body);drain(n.g)
    c=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0];click(n,c);n.am.scheduler.dispatch()
    assert n.calls[0][2]=={'text':body}


def test_disabled_feature_rejects_old_preview(native):
    n=native;c=preview(n);n.am.flags['scheduler']=False
    with pytest.raises(BoundaryError):click(n,c)
    n.am.scheduler.dispatch();assert not n.calls


def test_atomic_adoption_failure_recovers_original_identity(native):
    import sqlite3
    n=native;c=preview(n)
    with n.s.lock:n.s.conn.execute("CREATE TRIGGER fail_adoption BEFORE INSERT ON followup_adoptions BEGIN SELECT RAISE(ABORT,'synthetic interruption'); END")
    with pytest.raises(sqlite3.IntegrityError):click(n,c)
    original=n.s.rows('SELECT request_uuid FROM followup_intents')[0]['request_uuid']
    assert not n.s.rows('SELECT * FROM reminder_occurrences') and not n.s.rows('SELECT * FROM reminder_plans')
    with n.s.lock:n.s.conn.execute('DROP TRIGGER fail_adoption')
    n.f.recover_adoptions();n.f.recover_adoptions();n.am.scheduler.dispatch()
    assert len(n.calls)==1 and n.calls[0][3]==original


def test_native_double_confirmation_concurrent_maps_once(native):
    n=native;c=preview(n)
    with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:click(n,c),range(2)))
    n.am.scheduler.dispatch()
    assert len(n.calls)==1 and len(n.s.rows('SELECT * FROM reminder_occurrences'))==1


def test_expired_private_anchor_is_not_reread_or_revived(native):
    n=native;n.s.execute("UPDATE am_inbox SET expires=? WHERE id='om_engineer'",(n.clock()-1,))
    n.g.reminders.port.read=lambda mid:pytest.fail('must not re-read expired original content')
    with pytest.raises(BoundaryError,match='PRIVATE_CHAT_UNVERIFIED'):n.f.p2p('ou_engineer_a')


def test_redacted_contact_name_uses_verified_member_id_not_guess(native):
    n=native;old=n.am.ledger.port.get
    def get(uri,query=None):
        result=old(uri,query)
        if 'user' in result:result['user'].pop('name',None)
        return result
    n.am.ledger.port.get=get
    p=n.f.profile('ou_engineer_a')
    assert p['name']=='工程师甲' and p['name_source']=='verified_existing_group_member'
    with pytest.raises(BoundaryError,match='NAME_UNVERIFIED'):n.f.profile('ou_not_a_group_member')


def test_followup_preview_uses_original_platform_preserved_render_binding(native):
    from fs_agent.card_ui import bind_rendered_card
    n=native;c=preview(n)
    out=n.s.rows('SELECT body FROM outbox WHERE id=?',(c['outbox_id'],))[0]
    rendered=json.loads(out['body'])
    assert rendered['schema']=='2.0' and rendered==bind_rendered_card(rendered)
    assert rendered['body']['elements'][0]['element_id'].startswith('uxv_')
