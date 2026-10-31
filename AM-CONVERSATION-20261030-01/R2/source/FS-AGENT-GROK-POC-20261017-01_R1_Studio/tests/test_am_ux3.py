"""UX3 observable contracts through real routing, storage and synthetic transports."""
import json
import threading
import time
from dataclasses import replace
import pytest
from test_am_ux1 import ux, service, am_rig, base_rig, click, latest, text
from test_gateway import event, drain
from fs_agent.config import BoundaryError
from fs_agent.feishu import SendUnknown
from test_am_ux2 import start,form,confirm_plan


def ask(ux, body='项目', user='ou_staff', number=1, deliver=True):
    am,g,s,api,clock,port=ux
    e=event(body,user=user,number=number)
    e['event']['message'].update(chat_id='oc_'+user,create_time=str(int(clock()*1000)))
    assert am.ingest(e)==(True,True)
    am.step()
    if deliver:drain(g)
    return s.rows('SELECT * FROM am_inbox WHERE id=?',(e['event']['message']['message_id'],))[0]


@pytest.fixture
def staff(ux):
    ux[0].query_scope={'users':{'ou_staff':['需求75']}}
    assert 'ou_staff' not in ux[1].config.users
    return ux


def staff_click(ux,page,**kw):
    return click(ux,page,actor='ou_staff',chat='oc_ou_staff',**kw)


def test_staff_complete_path_and_delivery_independent_of_poc(staff):
    am,g,s,api,clock,port=staff
    ask(staff)
    assert '需求75' in text(staff) and '需求76' not in text(staff)
    assert '共 1 项' in text(staff)
    staff_click(staff,'project');staff_click(staff,'project',overrides={'section':'people'})
    assert 'AR1测试甲' in text(staff) and '实际收货尚未核实' not in text(staff)
    assert not any(a['page'] in ('remind','collect','more') for a in json.loads(latest(staff)['snapshot'])['actions'].values())
    assert not g.authorized({'app':g.config.app_id,'tenant':g.config.tenant_key,'user':'ou_staff','chat':'oc_ou_staff','chat_type':'p2p','expires':clock()+600})
    assert not s.rows('SELECT * FROM tasks') and not g.provider.prompts
    assert port.reads==1


def test_missing_mapping_returns_notice_without_names_or_counts(ux):
    row=ask(ux)
    assert row['error']=='PRIVATE_QUERY_SCOPE_MISSING'
    assert '尚未配置' in text(ux) and '需求75' not in text(ux) and 'http' not in text(ux)
    assert ux[-1].reads==0


def test_revoke_between_build_and_delivery_blocks_every_output(staff):
    ask(staff,deliver=False)
    staff[0].query_scope['users'].clear()
    drain(staff[1])
    assert not staff[3].sent
    assert staff[2].rows("SELECT 1 FROM outbox WHERE state='rejected'")


def test_revoke_with_hot_card_and_recent_never_discloses(staff):
    ask(staff);staff_click(staff,'project');old=latest(staff)
    staff[0].query_scope['users'].clear()
    before=len(staff[3].sent);staff_click(staff,'project',c=old,overrides={'section':'people'})
    assert len(staff[3].sent)==before+1
    assert '需求75' not in text(staff) and 'AR1' not in text(staff)


def test_management_is_denied_and_ordinary_chat_unclaimed(staff):
    r=ask(staff,'/plan 帮助')
    assert r['error']=='OWNER_ONLY' and '管理人' in text(staff)
    assert not staff[2].rows('SELECT * FROM reminder_plans')
    for body in ('如何做番茄炒蛋','今天过得怎么样','介绍一下薛定谔方程'):
        assert staff[0].ingest(event(body,user='ou_staff',number=200))==(False,False)


def test_hot_pages_stable_source_no_model_and_recent_scoped(staff):
    am,g,s,api,clock,port=staff
    ask(staff);first=json.loads(latest(staff)['snapshot'])['data']['snapshot_version']
    staff_click(staff,'project')
    for section in ('people','dates','todos',None):staff_click(staff,'project',overrides={'section':section})
    staff_click(staff,'projects');staff_click(staff,'recent')
    assert '需求75' in text(staff)
    assert json.loads(latest(staff)['snapshot'])['data']['snapshot_version']==first
    assert port.reads==1 and not g.provider.prompts
    ask(staff,user='ou_a',number=2);click(staff,'recent',chat='oc_ou_a')
    assert '暂无最近查看' in text(staff)


def test_snapshot_refresh_failure_keeps_complete_rows(staff):
    ask(staff);am=staff[0];previous=am.snapshots.latest
    staff[-1].fail_read=True
    staff_click(staff,'refresh')
    assert '需求75' in text(staff) and '刷新未成功' in text(staff)
    assert am.snapshots.latest==previous


def test_cross_actor_chat_and_stale_buttons_rejected(staff):
    ask(staff);old=latest(staff)
    click(staff,'project',c=old,actor='ou_a',chat='oc_ou_staff')
    assert staff[2].rows('SELECT * FROM am_inbox ORDER BY rowid DESC LIMIT 1')[0]['state']=='failed'
    staff_click(staff,'project',c=old)
    row=staff_click(staff,'project',c=old)
    assert row['state']=='failed'


def test_slow_source_coalesces_and_returns_loading_state(staff):
    am,g,s,api,clock,port=staff
    entered=threading.Event();release=threading.Event();original=port.read
    def slow():
        entered.set();assert release.wait(3);return original()
    port.read=slow;am.background_enabled=True
    try:
        ask(staff)
        assert entered.wait(1) and '资料读取中' in text(staff)
        assert s.rows("SELECT 1 FROM am_inbox WHERE state='source_wait'")
        same=am.snapshots.refresh();assert same is am.snapshots.future
        release.set();same.result(3)
        am.step();drain(g)
        assert '需求75' in text(staff) and port.reads==1
    finally:
        release.set();am.background_enabled=False


def test_slow_verify_does_not_block_next_page_or_other_user(staff):
    am,g,s,api,clock,port=staff
    am.background_enabled=True
    entered=threading.Event();release=threading.Event();verify=api.verify_card
    try:
        # Warm the common snapshot; synthetic clock remains fixed.
        am.snapshots.refresh().result(3)
        ask(staff)
        def slow(mid,row):entered.set();assert release.wait(3);return verify(mid,row)
        api.verify_card=slow
        g.pump_delivery();assert entered.wait(1)
        staff_click(staff,'project');staff_click(staff,'project',overrides={'section':'people'})
        assert 'AR1测试甲' in text(staff)
        ask(staff,user='ou_a',number=2);assert '需求76' in text(staff)
        release.set()
        for f in g.verification_futures.values():f.result(3)
        assert s.rows("SELECT 1 FROM am_view_verifications WHERE state='superseded'")
        assert not s.rows("SELECT 1 FROM outbox WHERE state='unknown'")
    finally:
        release.set();am.background_enabled=False


def test_single_form_item_only_preserves_edit_and_never_sends(ux):
    start(ux)
    fields=json.loads(latest(ux)['snapshot'])['fields']
    assert {'group','people','body','when','next_check','frequency','until','delivery_mode'}<=set(fields)
    click(ux,'preview_reminder',form=form(ux,delivery_mode='item_only',body='完整事项，等待核验。'))
    old=latest(ux)
    assert '不发送消息' in text(ux) and not ux[2].rows('SELECT * FROM action_items')
    click(ux,'remind')
    assert json.loads(latest(ux)['snapshot'])['fields']['body']['default']=='完整事项，等待核验。'
    assert click(ux,'confirm_reminder',c=old)['state']=='failed'
    # Recover preserved form through its original currently editing card.
    click(ux,'home');click(ux,'project');click(ux,'remind')
    click(ux,'preview_reminder',form=form(ux,delivery_mode='item_only',body='最终事项'))
    current=latest(ux);click(ux,'confirm_reminder');click(ux,'confirm_reminder',c=current)
    assert len(ux[2].rows('SELECT * FROM action_items'))==1
    assert not ux[2].rows('SELECT * FROM reminder_plans') and not ux[2].rows('SELECT * FROM reminder_occurrences')
    assert not ux[0].updates.port.calls


def test_followup_buckets_use_feedback_and_send_evidence(ux):
    from test_am_ux2_fix1 import occurrence,feedback
    o=occurrence(ux);am,g,s,api,clock,port=ux
    item=am.items.get(o['item_id'])
    assert am.followup_state(item)==('waiting','已发送，等待反馈')
    from datetime import datetime
    from fs_agent.scheduler import TZ
    result=feedback(ux,o,'new-eta','eta','正在整理报告',eta=datetime.fromtimestamp(clock()+3600,TZ).strftime('%Y-%m-%d %H:%M'))
    assert result['state']=='done',(result['error'],s.rows('SELECT id,state,error FROM am_inbox'),s.rows('SELECT * FROM item_feedback'))
    assert am.followup_state(am.items.get(item['id']))[0]=='action'
    click(ux,'item');click(ux,'feedback_seen')
    assert am.followup_state(am.items.get(item['id']))[0]=='waiting'
    s.execute("UPDATE reminder_occurrences SET state='unknown' WHERE id=?",(o['id'],))
    assert am.followup_state(am.items.get(item['id']))==('action','发送结果待核对')
    item=am.items.get(item['id']);am.items.change(am.owner,'close-test',item['id'],item['version'],'close',evidence='合成核验依据')
    assert am.followup_state(am.items.get(item['id']))==('closed','已关闭')


def test_slow_publish_different_users_independent(staff):
    am,g,s,api,clock,port=staff
    am.snapshots.refresh().result(3)
    ask(staff,deliver=False)
    entered=threading.Event();release=threading.Event();send=api.send
    def slow(row,guard):
        if row['user']=='ou_staff':entered.set();assert release.wait(3)
        return send(row,guard)
    api.send=slow
    try:
        g.pump_delivery();assert entered.wait(1)
        ask(staff,user='ou_a',number=2,deliver=False);g.pump_delivery()
        g.delivery_futures[(g.config.app_id,g.config.tenant_key,'ou_a')].result(2)
        assert any(r['user']=='ou_a' for r in api.sent)
        assert not any(r['user']=='ou_staff' for r in api.sent)
    finally:
        release.set()
        for f in g.delivery_futures.values():f.result(3)


def test_refresh_new_version_keeps_old_page_stable(staff):
    am,g,s,api,clock,port=staff
    ask(staff);old=am.snapshots.latest
    port.values[1][5]='AR9更新后合成人员';clock.now+=61
    am.snapshots.refresh().result(3)
    assert am.snapshots.latest!=old
    staff_click(staff,'project');staff_click(staff,'project',overrides={'section':'people'})
    assert 'AR1测试甲' in text(staff) and 'AR9' not in text(staff)
    staff_click(staff,'refresh')
    assert 'AR9更新后合成人员' in text(staff)


def test_callback_protocol_roundtrip_and_no_patch(ux):
    import lark_oapi as lark
    from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
    ask(ux,'/query-probe',user='ou_a')
    am,g,s,api,clock,port=ux
    probe=s.rows('SELECT * FROM am_query_probes')[0]
    e={'header':{'app_id':g.config.app_id,'tenant_key':g.config.tenant_key},'event':{'operator':{'open_id':am.owner},'context':{'open_chat_id':'oc_ou_a','open_message_id':probe['message_id']},'action':{'value':{'flow':'am_query_probe','nonce':probe['nonce'],'version':1}}}}
    before=len(api.sent);response=am.query_probe_response(e)
    roundtrip=json.loads(lark.JSON.marshal(P2CardActionTriggerResponse(response)))
    assert roundtrip['card']['type']=='raw' and roundtrip['card']['data']['schema']=='2.0'
    assert am.query_probe_response(e)==response and len(api.sent)==before
    e['event']['operator']['open_id']='ou_staff'
    assert 'card' not in am.query_probe_response(e)


def test_query_identity_reuses_subtree_but_rechecks_employment():
    from group_ledger import FeishuLedgerPort,LedgerError
    port=FeishuLedgerPort(None,app_id='cli_test',tenant_key='tenant',bot_open_id='ou_bot',department_root_id='od-th2')
    calls=[];active=[True]
    def get(uri,query):
        calls.append(uri)
        if '/users/' in uri:return {'user':{'open_id':'ou_staff','status':{'is_activated':active[0]},'department_ids':['od-child']}}
        return {'items':[{'open_department_id':'od-child'}],'has_more':False}
    port.get=get
    try:
        port.authorize_private_user('ou_staff')
        active[0]=False
        with pytest.raises(LedgerError,match='QUESTIONER_NOT_ACTIVE'):port.authorize_private_user('ou_staff')
        assert len(calls)==3
    finally:port.identity_pool.shutdown(wait=True)


def test_unmapped_record_is_readable_but_cannot_start_management(ux):
    ux[-1].values.append(['没有业务编号的合成记录','','','','尚未验收','合成人员',''])
    ask(ux,user='ou_a')
    snap=json.loads(latest(ux)['snapshot']);project=next(a['project'] for a in snap['actions'].values() if a.get('page')=='project' and a['project'] not in [r['id'] for r in ux[0].ledger.db.execute("SELECT id FROM project_refs WHERE identity_status='verified'")])
    click(ux,'project',chat='oc_ou_a',overrides={'project':project})
    assert '项目编号待核对' in text(ux)
    assert all(a['page'] not in ('remind','collect') for a in json.loads(latest(ux)['snapshot'])['actions'].values())


def test_optional_identity_cache_uses_id_expiry_and_current_local_revocation(staff):
    from am_query import QueryIdentityCache
    am,g,s,api,clock,port=staff
    checks=[];active=[True]
    def check(user):
        checks.append(user)
        if not active[0]:raise BoundaryError('QUESTIONER_NOT_ACTIVE')
    port.authorize_user=check
    am.query_identity.close();am.query_identity=QueryIdentityCache(check,60)
    ask(staff);staff_click(staff,'project');staff_click(staff,'project',overrides={'section':'people'})
    assert checks==['ou_staff']
    am.query_settings['denied_users']=['ou_staff']
    staff_click(staff,'project',overrides={'section':'dates'})
    assert '需求75' not in text(staff)
    am.query_settings['denied_users']=[];active[0]=False
    am.query_identity.entries['ou_staff']=time.monotonic()-1
    ask(staff,number=2)
    assert checks==['ou_staff','ou_staff'] and '需求75' not in text(staff)


def test_query_identity_cache_does_not_apply_to_management(ux):
    from am_query import QueryIdentityCache
    am,g,s,api,clock,port=ux;checks=[]
    port.authorize_user=lambda user:checks.append(user)
    am.query_identity.close();am.query_identity=QueryIdentityCache(port.authorize_user,60)
    ask(ux,user=am.owner);before=len(checks)
    click(ux,'work',chat='oc_'+am.owner)
    assert len(checks)>before


def test_reopen_after_long_idle_creates_one_current_navigation(staff):
    ask(staff);old=latest(staff);staff[4].now+=1801
    ask(staff,number=2);fresh=latest(staff)
    assert fresh['message_id']!=old['message_id']
    ask(staff,number=3);assert latest(staff)['message_id']==fresh['message_id']
    assert staff_click(staff,'project',c=old)['state']=='failed'


def test_actual_feishu_readback_uses_independent_staff_query_authority(staff):
    from types import SimpleNamespace as N
    from fs_agent.feishu import Feishu
    ask(staff);am,g,s,api,clock,port=staff
    out=s.rows('SELECT * FROM outbox ORDER BY rowid DESC LIMIT 1')[0]
    message=N(sender=N(open_bot_id=g.config.bot_open_id,id=g.config.bot_open_id,sender_type='app'),chat_id=out['chat'],deleted=False,msg_type='interactive',body=N(content=out['body']))
    client=N(im=N(v1=N(message=N(get=lambda request:N(success=lambda:True,data=N(items=[message]))))))
    real=Feishu(g.config,client=client)
    real.authorized=lambda row:pytest.fail('readback must not fall back to PoC authorization')
    assert real.verify_card(out['message_id'],am.query_readback_row(out))
    am.query_scope['users'].clear()
    assert real.verify_card(out['message_id'],am.query_readback_row(out)) is False


def test_expired_snapshot_has_bounded_recovery_to_current_catalog(staff):
    ask(staff);old=latest(staff);staff[0].snapshots.versions.clear()
    staff_click(staff,'project',c=old);recovery=latest(staff)
    staff_click(staff,'project',c=old)
    assert latest(staff)['message_id']==recovery['message_id']
    staff_click(staff,'projects')
    assert '需求75' in text(staff) and staff[2].rows('SELECT state FROM am_inbox ORDER BY rowid DESC LIMIT 1')[0]['state']=='done'
