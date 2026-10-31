"""UX2 observable flows. Synthetic ports, real store/inbox/business services."""
import copy
import json
import time
from datetime import datetime,timedelta
from pathlib import Path
import pytest
from test_am_ux1 import ux,service,am_rig,base_rig,request,click,latest,text
from test_gateway import event,drain
from fs_agent.scheduler import TZ
from fs_agent.project_catalog import digest
from group_ledger import render_project
from source_views import source_blocks,validate_selection


def start(ux):
    request(ux,'/menu',1);click(ux,'project');click(ux,'remind')

def form(ux,**kw):
    return dict({'people':['0'],'body':'请提交测试报告，尚未验收。','when':(datetime.fromtimestamp(ux[4](),TZ)+timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M +0800'),'frequency':'once'},**kw)

def confirm_plan(ux,people=None):
    start(ux);click(ux,'preview_reminder',form=form(ux,people=people or ['0']));click(ux,'confirm_reminder')
    return ux[2].rows('SELECT * FROM reminder_plans')[0]


def test_U01_fields_and_source_are_distinct(ux):
    request(ux,'/menu',1);click(ux,'project');sections=latest(ux)
    for section,expected in [('dates','关键日期'),('people','AR1测试甲'),('todos','待办')]:
        click(ux,'project',c=sections,overrides={'section':section})
        assert expected in text(ux)
        if section=='people':assert '实际收货尚未核实' not in text(ux)
        sections=latest(ux)
    p=ux[0].projects(ux[2].rows('SELECT * FROM am_inbox LIMIT 1')[0])[0]
    assert '项目进展' not in render_project(p,[])
    p['人员与职责']='';assert '未记录' in render_project(p,['people'])


def test_U02_single_and_multiple_people(ux):
    request(ux,'/project 需求75谁负责',1)
    assert 'AR1测试甲' in text(ux) and '实际收货' not in text(ux)
    before=len(ux[3].sent);request(ux,'/project 需求75与需求76谁负责',2)
    assert len(ux[3].sent)==before+1
    assert 'AR1测试甲' in text(ux) and 'AR2乙' in text(ux) and '项目进展' not in text(ux)


def test_U03_complete_blocks_and_bounded_fallback(ux):
    row={'key':'p','title':'合成规格记录','项目进展':'HD14：已完成；HD17：预计11月完成，尚未验收。前提：油脂到货。','关键日期':'','人员与职责':'','待办':'','read_status':'complete','source_revision':'r1'}
    answer=render_project(row)
    assert row['项目进展'] in answer
    row['项目进展']*=20
    answer=render_project(row)
    assert len(answer)<300 and '原文' in answer and 'HD17' not in answer
    am,g,s,api,clock,_=ux
    origin={'app':g.config.app_id,'tenant':g.config.tenant_key,'user':am.owner,'chat':'oc_dm','chat_type':'p2p','expires':clock()+86400,'id':'semantic-scene','kind':'text'}
    am.ux_page(origin,'合成项目短答',answer,[('查看来源',{'page':'home'})]);drain(g)
    blocks=source_blocks(row,['progress'])
    with pytest.raises(ValueError):validate_selection(['invented'],blocks,'p')
    with pytest.raises(ValueError):validate_selection([blocks[0].id],blocks,'another')


def test_U06_real_todo_pagination(ux):
    am=ux[0]
    for n in range(8):
        am.items.create(am.owner,'page-'+str(n),project_ref='synthetic',description='事项'+str(n),requirements='',assignees=['ou_engineer_a'],source={'project_title':'合成项目'})
    request(ux,'/todo',1);first=text(ux);click(ux,'work',overrides={'offset':1});second=text(ux)
    assert '我的跟进' in first and '我的跟进' in second and first!=second
    assert '台账候选' not in first and '台账候选' not in second


def test_U07_once_edit_preview_exact_and_idempotent(ux):
    start(ux);spec=json.loads(latest(ux)['snapshot'])['fields'];assert 'until' in spec and 'policy' in spec and spec['until']['required'] is False
    click(ux,'preview_reminder',form=form(ux));old=latest(ux)
    card=json.loads(text(ux));body=''.join(e.get('text',{}).get('content','') for e in card['body']['elements'])
    assert body.count(form(ux)['body'])==1
    click(ux,'remind');edited=latest(ux)
    assert json.loads(edited['snapshot'])['fields']['body']['default']==form(ux)['body']
    assert click(ux,'confirm_reminder',c=old)['state']=='failed'
    click(ux,'preview_reminder',c=edited,form=form(ux,body='修改后正文 {文字}，仍待验收'))
    current=latest(ux);click(ux,'confirm_reminder');count=len(ux[3].sent);click(ux,'confirm_reminder',c=current)
    assert len(ux[3].sent)==count
    plan=ux[2].rows('SELECT * FROM reminder_plans')[0]
    assert ux[0].scheduler.render(plan,ux[0].items.get(plan['item_id']))['body']=='修改后正文 {文字}，仍待验收'
    assert len(ux[2].rows('SELECT * FROM reminder_plans'))==len(ux[2].rows('SELECT * FROM action_items'))==1


def test_U08_cycle_fields_and_resume_preview(ux):
    start(ux)
    specs=json.loads(latest(ux)['snapshot'])['fields'];assert 'until' in specs and 'policy' in specs
    until=(datetime.fromtimestamp(ux[4](),TZ)+timedelta(days=2)).strftime('%Y-%m-%d %H:%M +0800')
    click(ux,'preview_reminder',form=form(ux,frequency='exact_daily',until=until,policy='fixed_rule'));click(ux,'confirm_reminder')
    click(ux,'plan_control',overrides={'control':'pause'})
    actions=json.loads(latest(ux)['snapshot'])['actions'].values()
    assert any(a.get('control')=='resume' for a in actions) and not any(a.get('control')=='pause' for a in actions)
    click(ux,'plan_control',overrides={'control':'resume'})
    assert '完整预览' in text(ux) and '含休息日' in text(ux)
    assert ux[2].rows('SELECT * FROM reminder_plans')[0]['state']=='draft'


def test_U09_two_actors_feedback_and_notice_dedup(ux):
    p=confirm_plan(ux,['0','1']);am,g,s,api,clock,_=ux
    clock.now=p['next_at'];am.scheduler.scan();o=s.rows('SELECT * FROM reminder_occurrences')[0];payload=json.loads(o['payload'])
    s.execute("UPDATE reminder_occurrences SET state='sent',message_id='om_feedback',readback_state='verified' WHERE id=?",(o['id'],))
    def feedback(actor,event_id,kind='received',detail=None):
        value={'flow':'am_self','feedback':o['id'],'nonce':payload['feedback_nonce'],'action':kind}
        e={'header':{'app_id':g.config.app_id,'tenant_key':g.config.tenant_key,'event_id':event_id,'event_type':'card.action.trigger'},'event':{'operator':{'open_id':actor},'context':{'open_chat_id':'oc_reminder','open_message_id':'om_feedback'},'action':{'value':value}}}
        accepted=am.ingest(e)
        if accepted[1]:am.step();drain(g)
    feedback('ou_engineer_a','f1');n=len(api.sent)
    feedback('ou_engineer_a','f1');feedback('ou_engineer_a','f2')
    assert len(api.sent)==n
    feedback('ou_engineer_b','f3');assert len(api.sent)==n+2
    assert len(am.items.history(o['item_id']))==2
    assert am.items.get(o['item_id'])['decision_version']==1
    assert all('最新反馈：{' not in x['body'] for x in api.sent)


def test_U10_collection_single_result_content_review_is_not_approval(ux):
    request(ux,'/menu',1);click(ux,'project');click(ux,'collect')
    n=len(ux[3].sent);request(ux,'预计明天交报告，尚未验收。',2)
    assert len(ux[3].sent)==n+1
    click(ux,'review_content')
    p=ux[2].rows('SELECT * FROM ledger_proposals')[0]
    assert p['state']=='proposed' and p['approval'] is None and not ux[2].rows('SELECT * FROM ledger_approval_snapshots')
    click(ux,'cancel_collect');e=event('普通聊聊天',number=3)
    assert ux[0].ingest(e)==(False,False)
    assert not ux[0].updates.port.calls


def test_U04_one_navigation_message_preserves_search_and_return(ux):
    request(ux,'/menu',1);click(ux,'search',form={'query':'需求75'});click(ux,'project')
    click(ux,'project',overrides={'section':'dates'});click(ux,'projects')
    assert json.loads(latest(ux)['snapshot'])['fields']['query']['default']=='需求75'
    assert sum(x.get('operation')=='create' for x in ux[3].sent)==1
    assert len(ux[3].updated)==4
    mid=latest(ux)['message_id'];request(ux,'/menu',2)
    assert latest(ux)['message_id']==mid


def test_U05_old_result_does_not_overwrite_new_interaction(ux):
    request(ux,'/menu',1);old=latest(ux)
    click(ux,'project');current=latest(ux);before=text(ux)
    # A stale worker retains its original interaction/version. The CAS rejects
    # it without modifying the current view or delivering to a newer object.
    snap=json.loads(old['snapshot']);row=dict(ux[2].rows('SELECT * FROM am_inbox LIMIT 1')[0],_interaction=snap['interaction_id'],_view_version=snap['view_version'])
    from fs_agent.config import BoundaryError
    with pytest.raises(BoundaryError,match='VIEW_CHANGED'):ux[0].ux_page(row,'旧结果','迟到旧项目')
    assert latest(ux)['nonce']==current['nonce'] and text(ux)==before
    request(ux,'/project 需求76谁负责',2)
    assert latest(ux)['message_id']!=current['message_id']
    assert ux[3].messages[current['message_id']]==before


def test_U11_subscription_contract_fixed_details_and_consumption(ux):
    am,g,s,api,clock,port=ux
    request(ux,'/menu',1);click(ux,'more');click(ux,'subscribe')
    until=(datetime.fromtimestamp(clock(),TZ)+timedelta(days=3)).strftime('%Y-%m-%d %H:%M +0800')
    click(ux,'subscription_preview',form={'frequency':'daily','time':'09:00','until':until});click(ux,'subscription_confirm')
    plan=s.rows('SELECT * FROM reminder_plans')[0]
    port.values[1][4]='预计明日交付，尚未验收。'
    request(ux,'/briefing',2)
    assert not s.rows('SELECT * FROM am_briefing_deliveries')
    clock.now=plan['next_at'];am.scheduler.scan();occ=s.rows('SELECT * FROM reminder_occurrences')[0];payload=json.loads(occ['payload'])
    assert payload['briefing_data']['types']==['changes','todos'] and payload['briefing_data']['todos']
    assert payload['event_ids']==[e['id'] for e in payload['briefing_data']['events']]
    assert payload['card'] and payload['briefing_nonce']
    assert all(r['state']=='pending' for r in s.rows('SELECT * FROM am_briefing_deliveries'))
    s.execute("UPDATE reminder_occurrences SET state='sent',message_id='om_brief',readback_state='verified' WHERE id=?",(occ['id'],))
    body={'value':{'briefing':occ['id'],'nonce':payload['briefing_nonce']},'source_message':'om_brief'}
    row=s.rows('SELECT * FROM am_inbox WHERE id=?',('om2',))[0]
    am.handle_briefing_card(row,body);drain(g);click(ux,'briefing_detail',overrides={'section':'changes'})
    assert '预计明日交付，尚未验收。' in text(ux)
    with s.tx() as c:am.scheduler.sync_deliveries(c)
    assert all(r['state']=='verified' for r in s.rows('SELECT * FROM am_briefing_deliveries'))
    legacy=dict(plan,rule='{}',id='legacy');assert am.briefing_types(legacy)==['changes']


def test_U12_incomplete_precheck_then_supplement_retains_version(ux):
    am,g,s,api,clock,port=ux
    request(ux,'/menu',1);click(ux,'more');click(ux,'targets');click(ux,'precheck_form');click(ux,'start_precheck',form={'kind':'test','requirements':'验收条件\n测试记录'})
    from fs_agent.config import BoundaryError
    def unread(*a,**k):raise BoundaryError('FILE_READ_FAILED')
    api.read_file=unread
    e=event('',number=2);e['event']['message'].update(message_type='file',content=json.dumps({'file_key':'test','file_name':'合成资料.txt'}),create_time=str(int(clock()*1000)))
    assert am.ingest(e)==(True,True);am.step();drain(g)
    assert '材料未完整读取' in text(ux)
    old=json.loads(latest(ux)['snapshot']);assert old['data']['report_snapshot']
    request(ux,'验收条件：待评审\n测试记录：已有合成记录，尚未验收',3)
    assert '材料未完整读取' in text(ux) # Failed original remains evidence, not silently erased.
    assert s.rows('SELECT revision FROM logic_drafts')[0]['revision']>old['data']['report_revision']


def test_U13_document_questions_and_short_result(ux):
    from test_doc_logic_fix1 import two_questions,model_run,update,candidate,OK
    from fs_agent.question_state import question_id
    am,g,s,api,clock,port=ux
    _,_,row,d,qs=two_questions((g,s,api,None,clock))
    drain(g)
    assert '电机A样本编号是什么' in api.messages[latest(ux)['message_id']] and '电机A适用判据是什么' in api.messages[latest(ux)['message_id']]
    assert g.ingest(event('电机A样本编号是 S-A；电机A适用判据无法提供。',number=2));g.receive_one()
    sources=json.loads(g.logic.current(row)['sources'])
    d=model_run(g,s,[{'updates':[update(qs[0],'resolved','样本编号是 S-A','样本 S-A'),update(qs[1],'unavailable','适用判据无法提供','无法提供','判据尚不明确，不能判定通过',ref=next(p['ref'] for p in sources[-1]['segments'] if '无法提供' in p['original']))]},candidate(sources),OK])
    drain(g)
    ledger=json.loads(d['answers'])
    assert ledger[question_id(qs[0])]['status']=='resolved' and ledger[question_id(qs[1])]['status']=='unavailable'
    assert json.loads(d['analysis'])['questions']==[]
    assert '样本编号是什么' not in api.messages[latest(ux)['message_id']]
    assert g.ingest(event('/doc 阶段稿',number=3));g.receive_one()
    d=model_run(g,s,[candidate(sources),OK]);drain(g)
    cards=s.rows("SELECT * FROM am_cards WHERE flow='ux' ORDER BY rowid DESC LIMIT 1")
    assert cards and '阶段稿' in api.messages[cards[0]['message_id']]
    click(ux,'documents',c=cards[0],overrides={'section':'content'})
    assert '判据尚不明确' in text(ux)


def test_U14_exact_mount_preview_and_replay(ux):
    am,g,s,api,clock,port=ux
    row={'app':g.config.app_id,'tenant':g.config.tenant_key,'user':am.owner,'chat':'oc_dm','chat_type':'p2p','expires':clock()+86400,'id':'mount-scene','kind':'text'}
    d=g.logic.create(row,'test');target=g.logic.business.resolve(row,'A')
    from fs_agent.doc_logic import digest as content_hash
    s.execute("UPDATE logic_drafts SET content=?,content_hash=?,state='ready',target=? WHERE id=?",('合成完整稿',content_hash('合成完整稿'),json.dumps(target),d['id']))
    am.ux_documents(row,{'page':'documents','draft':d['id'],'section':'actions'});drain(g)
    click(ux,'documents',overrides={'section':'adopt'});click(ux,'documents',overrides={'section':'mount_preview'});preview=latest(ux)
    assert target['deliverable_id'] in text(ux) and '稿件版本' in text(ux)
    click(ux,'documents',overrides={'section':'mount'});click(ux,'documents',c=preview,overrides={'section':'mount'})
    assert len(g.logic.business.writes)==1 and len(s.rows('SELECT * FROM logic_writes'))==1
    g.logic.select_target(row,d['id'],'B')
    r=click(ux,'documents',c=preview,overrides={'section':'mount'});assert r['state']=='failed'


def test_U15_unknown_update_reconciles_without_create(ux):
    from fs_agent.feishu import SendUnknown
    request(ux,'/menu',1);home=latest(ux);api=ux[3]
    original=api.update_card
    def lost(row,guard):
        original(row,guard);raise SendUnknown('SYNTHETIC_TIMEOUT')
    api.update_card=lost
    click(ux,'recent');unknown=ux[2].rows("SELECT * FROM outbox WHERE state='unknown'")[0]
    ident=json.loads(latest(ux)['snapshot'])['interaction_id']
    verify=api.verify_card;api.verify_card=lambda *a:False
    n=len(api.sent);request(ux,'/menu',2)
    # FIX1 adds one separate status card. It must not republish the unknown view.
    assert len(api.sent)==n+1 and '核对页面状态' in text(ux)
    api.verify_card=verify
    assert ux[0].reconcile_view(ident)
    api.update_card=original
    request(ux,'/menu',3)
    assert sum(x.get('operation')=='create' for x in api.sent)==2
    assert latest(ux)['message_id']==home['message_id']


def test_U16_shared_group_card_does_not_become_private_navigation(ux):
    p=confirm_plan(ux,['0','1']);am,g,s,api,clock,_=ux
    clock.now=p['next_at'];am.scheduler.scan();o=s.rows('SELECT * FROM reminder_occurrences')[0];payload=json.loads(o['payload'])
    assert payload['card']['config']['update_multi'] is True
    shared=json.dumps(payload['card'],ensure_ascii=False)
    assert '我的工作' not in shared and '反馈记录' not in shared
    assert 'ou_engineer_a' in shared and 'ou_engineer_b' in shared
    assert len(json.loads(latest(ux)['snapshot'])['actions'])<=5


@pytest.fixture(autouse=True)
def record_observation(request,ux):
    from fs_agent.presentation import visible_metrics
    api=ux[3];started=time.monotonic();first=[None];deliveries=[];last_delivery=[None]
    send,update=api.send,api.update_card
    def observe(fn,kind):
        def wrapped(row,guard):
            value=fn(row,guard)
            elapsed=time.monotonic()-started;last_delivery[0]=elapsed
            if first[0] is None and row['kind']=='interactive':first[0]=elapsed
            if row['kind']=='interactive':
                view=json.loads(row['body']);info=ux[2].rows('SELECT metrics FROM am_view_outputs WHERE outbox_id=?',(row['id'],))
                deliveries.append(dict(visible_metrics(view),title=view.get('header',{}).get('title',{}).get('content'),elapsed_seconds=elapsed,operation=kind,exception=json.loads(info[0]['metrics']).get('exception') if info else None))
            return value
        return wrapped
    api.send=observe(send,'create');api.update_card=observe(update,'update')
    yield
    folder=Path(__file__).resolve().parents[2]/'AM-SELF-20261029-01/UX3/evidence/scenarios'
    folder.mkdir(exist_ok=True,parents=True)
    code=request.node.name.split('_')[1]
    creates=sum(x['operation']=='create' for x in deliveries);updates=sum(x['operation']=='update' for x in deliveries)
    result={'scenario':code,'test':request.node.name,'layer':'isolated_real_services_synthetic_transport',
        'user_actions':len(ux[2].rows('SELECT id FROM am_inbox'))+len(ux[2].rows('SELECT seq FROM inbox')),
        'new_messages':sum(x.get('operation')=='create' for x in api.sent),'new_text_messages':sum(x.get('operation')=='create' and x['kind']=='text' for x in api.sent),'new_file_messages':sum(x.get('operation')=='create' and x['kind']=='file' for x in api.sent),'new_card_messages':creates,'card_updates':updates,'first_actionable_seconds':first[0],
        'final_result_seconds':last_delivery[0],'clock_basis':'wall time from isolated scenario entry; not Feishu/client/model latency',
        'screens':deliveries,'draft_loss_observed':False if code in ('U07','U08','U15') else None,'mobile_human_acceptance':False,'desktop_human_acceptance':False}
    (folder/(request.node.name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))


def test_U15_busy_model_does_not_block_navigation(ux,tmp_path):
    import threading,sqlite3
    from types import SimpleNamespace
    from bridge import Bridge
    am,g,s,api,clock,port=ux;entered=threading.Event();release=threading.Event()
    db=sqlite3.connect(':memory:',check_same_thread=False);db.execute('CREATE TABLE ledger_inbox(state TEXT)');db.execute("INSERT INTO ledger_inbox VALUES('queued')")
    def slow(**kw):entered.set();release.wait(5);return True
    ledger=SimpleNamespace(assistant=object(),step=slow,mutex=threading.RLock(),db=db)
    poc=SimpleNamespace(step=lambda:False,model_busy=lambda:False,store=s,gateway=g)
    bridge=Bridge({'app_id':'cli_test','state_directory':str(tmp_path/'bridge'),'allowed_open_ids':[]},lambda *a:None,poc=poc,group_ledger=ledger)
    bridge.am_self=am
    try:
        started=time.monotonic();bridge.process_cycle();assert time.monotonic()-started<1
        assert entered.wait(1)
        payload=event('/menu',number=55);assert am.ingest(payload)==(True,True)
        started=time.monotonic();bridge.process_cycle();drain(g)
        assert time.monotonic()-started<1 and '项目查询' in text(ux)
    finally:release.set();bridge.group_future.result(5);bridge.db.close();db.close()


def test_U16_long_exact_preview_all_pages_reachable(ux):
    am,g,s,api,clock,_=ux
    row={'app':g.config.app_id,'tenant':g.config.tenant_key,'user':am.owner,'chat':'oc_dm','chat_type':'p2p','expires':clock()+86400,'id':'long-preview','kind':'text'}
    complete='合成对象：原值及限定条件完整保留。\n'*400
    am.ux_page(row,'精确差异预览',complete,[('完成查看',{'page':'home'})],data={'full_preview':True});drain(g)
    pieces=[]
    while True:
        c=latest(ux);snapshot=json.loads(c['snapshot']);visible=json.loads(text(ux))['body']['elements'][0]['text']['content']
        pieces.append(visible.split('\n',1)[1])
        next_action=next((a for a in snapshot['actions'].values() if a['page']=='long_content' and a['offset']>snapshot['data'].get('_long_index',0)),None)
        if next_action is None:break
        assert not any(a['page']=='home' for a in snapshot['actions'].values())
        click(ux,'long_content',overrides={'offset':next_action['offset']})
    assert ''.join(pieces)==complete


def test_U15_expired_form_recovers_valid_draft(ux):
    start(ux);click(ux,'preview_reminder',form=form(ux,body='需要保留的草稿正文'))
    click(ux,'remind');old=latest(ux);ux[4].now+=3601
    assert click(ux,'preview_reminder',c=old,form=form(ux))['state']=='failed'
    click(ux,'retry_form')
    assert json.loads(latest(ux)['snapshot'])['fields']['body']['default']=='需要保留的草稿正文'
    assert not ux[2].rows('SELECT * FROM reminder_plans')


def test_U03_independent_role_rows_keep_scope_and_qualifiers(ux):
    from source_views import project_data
    roles='\n'.join(f'职责{n}：AR{n}合成人员，负责本项目第{n}类资料核对，不代表专业验收。' for n in range(100,108))
    p={'key':'roles','title':'合成人员范围','人员与职责':roles,'项目进展':'','关键日期':'','待办':'','source_revision':'r2'}
    d=project_data(p,['people']);assert 1<=len(d['blocks'])<=3 and d['omitted_blocks']>0
    for block in d['blocks']:
        assert roles[slice(*block['span'])]==block['text'] and '不代表专业验收' in block['text'] and block['subject']=='roles'
    p['人员与职责']='HD14组：\n'+roles+'\n以上仅限旧型号，新增型号尚未确认。'
    d=project_data(p,['people']);assert not d['blocks'] and d['limitation']


def test_U15_transformed_link_readback_requires_same_render_and_url(ux):
    from fs_agent.card_ui import card,paragraph,bind_rendered_card,card_readback_matches
    expected=bind_rendered_card(card('合成核验',[paragraph('原文完整'),{'tag':'markdown','content':'[原文](https://synthetic.invalid/source)'}]))
    marker=expected['body']['elements'][0]['element_id']
    raw={'header':{'tag':'card_header','property':{'title':{'tag':'plain_text','property':{'content':'合成核验'}}}},'body':{'tag':'body','property':{'elements':[{'id':marker,'tag':'div','property':{'text':{'tag':'plain_text','property':{'content':'原文完整'}}}},{'tag':'markdown','property':{'elements':[{'tag':'link','property':{'content':'原文','url':{'url':'https://synthetic.invalid/source'}}}]}}]}}}
    assert card_readback_matches({'json_card':json.dumps(raw)},expected)
    raw['body']['property']['elements'][1]['property']['elements'][0]['property']['url']['url']='https://synthetic.invalid/wrong'
    assert not card_readback_matches({'json_card':json.dumps(raw)},expected)
    raw['body']['property']['elements'][0]['id']='old'
    assert not card_readback_matches({'json_card':json.dumps(raw)},expected)


def test_U16_transformed_mentions_preserve_exact_people(ux):
    from fs_agent.card_ui import card,paragraph,bind_rendered_card,card_readback_matches
    expected=bind_rendered_card(card('合成群卡',[{'tag':'markdown','content':'<at id="ou_a"></at> <at id="ou_b"></at>'},paragraph('仍待核验')]))
    raw={'header':{'property':{'title':{'tag':'plain_text','property':{'content':'合成群卡'}}}},'body':{'property':{'elements':[{'id':expected['body']['elements'][0]['element_id'],'tag':'markdown','property':{'elements':[{'tag':'at','property':{'userID':'ou_a'}},{'tag':'at','property':{'userID':'ou_b'}}]}},{'tag':'div','property':{'text':{'tag':'plain_text','property':{'content':'仍待核验'}}}}]}}}
    assert card_readback_matches({'json_card':json.dumps(raw)},expected)
    raw['body']['property']['elements'][0]['property']['elements'][1]['property']['userID']='ou_wrong'
    assert not card_readback_matches({'json_card':json.dumps(raw)},expected)


def test_U10_legacy_content_check_has_one_result_and_no_approval(ux):
    request(ux,'/update 需求75：预计明天提交，尚未验收。',1)
    r=ux[2].rows('SELECT * FROM progress_collections')[0];n=len(ux[3].sent)
    request(ux,'/update 核对 '+r['id']+' v1',2)
    assert len(ux[3].sent)==n+1
    assert not ux[2].rows('SELECT * FROM ledger_approval_snapshots')
    assert ux[2].rows('SELECT * FROM ledger_proposals')[0]['approval'] is None


def test_U11_repeated_subscription_confirmation_has_one_receipt(ux):
    request(ux,'/menu',1);click(ux,'more');click(ux,'subscribe')
    until=(datetime.fromtimestamp(ux[4](),TZ)+timedelta(days=3)).strftime('%Y-%m-%d %H:%M +0800')
    click(ux,'subscription_preview',form={'frequency':'daily','time':'09:00','until':until});preview=latest(ux)
    click(ux,'subscription_confirm');n=len(ux[3].sent)
    click(ux,'subscription_confirm',c=preview)
    assert len(ux[3].sent)==n and len(ux[2].rows('SELECT * FROM reminder_plans'))==1
