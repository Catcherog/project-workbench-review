"""Regression contracts for repaired follow-up state and feedback lifecycles.

Uses the original native SQLite fixture and its simulated platform. These tests
must pass after repair; state_probes.py separately records the observed bugs.
No test approves a real message or modifies the reviewed implementation.

The owner UI probe accepts either native item feedback or a visible unverified
candidate. It does not require a particular feedback table, kind, or state
promotion. If the repair adds a dedicated owner candidate-detail route, include
that public UI route in _owner_feedback_ui; keep the visible-fact assertions.
"""
import json
import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from test_followup_native import native, service, am_rig, base_rig, preview, click
from test_gateway import event, drain
from fs_agent.config import BoundaryError
from fs_agent.project_catalog import canonical,digest
from am_followup.followup import FollowupError


def _publish_current_reply(n, occurrence, text, number):
    incoming = event(text, number=number, user='ou_engineer_a', chat='oc_engineer')
    message = incoming['event']['message']
    message.update(parent_id=occurrence['message_id'], create_time=str(int(n.clock()*1000)))
    # A repaired implementation can independently read this current message.
    n.remote[message['message_id']] = {
        'message_id': message['message_id'], 'chat_id': 'oc_engineer',
        'sender_id': 'ou_engineer_a', 'sender_type': 'user', 'msg_type': 'text',
        'content': {'text': text}, 'deleted': False, 'created_at': n.clock(),
        'parent_id': occurrence['message_id'],
    }
    assert n.am.ingest(incoming) == (True, True)
    assert n.am.ingest(incoming) == (True, False)
    n.am.step()
    return message['message_id']


def _owner_feedback_ui(n, item_id, monkeypatch):
    """Read rendered owner-facing text, never the private inbox or raw tables."""
    visible = []
    def capture(row, title, body, actions, **kwargs):
        if row['user'] == n.am.owner:
            visible.extend((str(title), str(body)))
        return None
    monkeypatch.setattr(n.am, 'ux_page', capture)
    n.am.ux_item(n.row, item_id)
    n.am.ux_extra(n.row, {'page':'history', 'item':item_id}, {}, {})
    n.f.dashboard(n.row)
    # A repair may have already prepared an owner-visible candidate/notice.
    visible.extend(r['body'] for r in n.s.rows('SELECT body FROM outbox WHERE chat=?', (n.row['chat'],)))
    return '\n'.join(visible)


def test_reviewed_new_source_can_resume_same_item_without_old_approval(native):
    n = native
    old_card = preview(n)
    click(n, old_card)
    canonical_id = n.f.semantic(n.item['id'])['canonical_id']
    obs2 = replace(n.obs, version='v2', occurred_at_ms=n.obs.occurred_at_ms + 1,
                   text='已开测，等待测试结果',
                   payload={'record':{'todo':'等待测试结果'}, 'quote':'已开测，等待测试结果'})
    n.reader.record(obs2, authoritative=True)
    processed = n.facts.process(obs2, [])
    n.am.scheduler.dispatch()
    assert not n.calls, 'Changing the source must invalidate the old approval.'

    refs2 = n.f.sources.resolve(n.item['project_ref'], processed['fact_ids'])
    # Explicit owner review, not an automatic promotion of model output.
    n.f.bind(n.row, n.item['id'], refs=refs2)
    n.f.record_claim(n.row, n.item['id'], 'execution', 'in_progress', processed['fact_ids'])
    assert n.f.semantic(n.item['id'])['canonical_id'] == canonical_id
    nonce = n.f.preview_card(n.row, n.item['id'], body='请补充本次测试的当前进展。')
    drain(n.g)
    current = n.s.rows('SELECT * FROM am_cards WHERE nonce=?', (nonce,))[0]
    click(n, current)
    n.am.scheduler.dispatch()
    assert len(n.calls) == 1, 'The newly reviewed preview must resume the same item once.'
    assert len(n.s.rows('SELECT * FROM action_items')) == 1


def test_rejected_import_does_not_leave_an_unfenced_native_item(native):
    n = native
    before_ids = {r['id'] for r in n.s.rows('SELECT id FROM action_items')}
    facts = n.f.sources.defaults(n.item['project_ref'])
    payload = {
        'producer':'personal', 'external_id':'bad-history',
        'identity':{'tenant':n.f.tenant, 'project':n.item['project_ref'],
                    'object':'new-work', 'action':'request_update', 'cycle':'one'},
        'item':{'description':'不得遗漏历史的导入事项', 'assignees':['ou_engineer_a']},
        'fact_ids':[r['fact_id'] for r in facts],
        'history':['invalid-record'], 'history_complete':False,
    }
    candidate_id = None
    # Rejecting malformed input immediately or retaining only a candidate are
    # both valid; neither may leave an executable ActionItems row behind.
    with pytest.raises(BoundaryError):
        candidate_id = n.f.import_candidate(n.row, payload)
        n.f.adopt_candidate(n.row, candidate_id)
    assert {r['id'] for r in n.s.rows('SELECT id FROM action_items')} == before_ids, (
        'Failed adoption must atomically roll back the new item and its bindings.'
    )
    if candidate_id is not None:
        assert n.s.rows('SELECT state FROM followup_candidates WHERE id=?', (candidate_id,))[0]['state'] != 'adopted'
    assert not n.calls and not n.s.rows('SELECT * FROM followup_intents')


def test_substantive_exact_reply_is_visible_as_unverified_feedback(native, monkeypatch):
    n = native
    card = preview(n, 'recipient_p2p')
    click(n, card)
    n.am.scheduler.dispatch()
    occurrence = n.s.rows('SELECT * FROM reminder_occurrences')[0]
    message_id = _publish_current_reply(n, occurrence, '已开测，预计周五交报告', 301)
    row = n.s.rows('SELECT state,error FROM am_inbox WHERE id=?', (message_id,))[0]
    assert row['state'] == 'done' and not row['error']
    text = _owner_feedback_ui(n, n.item['id'], monkeypatch)
    assert all(part in text for part in ('开测', '周五', '报告')), (
        'The owner must be able to see the reported progress/ETA in feedback or a visible candidate.'
    )
    item = n.am.items.get(n.item['id'])
    assert item['state'] != 'closed' and not item['close_evidence']
    assert not n.f.view(item['id'])['business_completed']
    assert len(n.calls) == 1, 'Receiving a report must not send another follow-up.'


def test_current_private_reply_survives_expired_old_greeting(native, monkeypatch):
    n = native
    card = preview(n, 'recipient_p2p')
    click(n, card)
    n.am.scheduler.dispatch()
    occurrence = n.s.rows('SELECT * FROM reminder_occurrences')[0]
    n.s.execute("UPDATE am_inbox SET expires=? WHERE id='om_engineer'", (n.clock()-1,))
    original_read = n.g.reminders.port.read
    def current_only(message_id):
        assert message_id != 'om_engineer', 'Do not reread expired greeting content.'
        return original_read(message_id)
    monkeypatch.setattr(n.g.reminders.port, 'read', current_only)
    message_id = _publish_current_reply(n, occurrence, '收到', 302)
    row = n.s.rows('SELECT state,error FROM am_inbox WHERE id=?', (message_id,))[0]
    assert row['state'] == 'done' and not row['error'], (
        'This authenticated current reply must establish its own exact conversation evidence.'
    )
    text = _owner_feedback_ui(n, n.item['id'], monkeypatch)
    assert any(word in text for word in ('已收到', '已回应', '已回复', '收到', 'acknowledged')), (
        'The current acknowledgement must be observable to the owner.'
    )
    item = n.am.items.get(n.item['id'])
    assert item['state'] != 'closed' and not item['close_evidence']
    assert len(n.calls) == 1
    assert n.f.p2p('ou_engineer_a')['anchor_message'] == message_id


def _candidate(n, *, complete=True, external='atomic-import'):
    return {
        'producer':'personal','external_id':external,
        'identity':{'tenant':n.f.tenant,'project':n.item['project_ref'],'object':external,'action':'request_update','cycle':'one'},
        'item':{'description':'核对测试进展','requirements':'查看实际报告','assignees':['ou_engineer_a']},
        'fact_ids':[r['fact_id'] for r in n.f.sources.defaults(n.item['project_ref'])],
        'history':[],'history_complete':complete,
    }


def _old_orphan(n, value, *, operation=None):
    fields=value['item'];identity=value['identity']
    return n.am.items.create(n.am.owner,operation or 'followup-import/task_'+digest(identity),
        project_ref=identity['project'],description=fields['description'],requirements=fields.get('requirements',''),
        assignees=fields['assignees'],source={'producer':value['producer'],'external_id':value['external_id'],'fact_ids':value['fact_ids']})


@pytest.mark.parametrize('bad', ['identity_type','assignees_type','fact_type','history_state_type','unexpected_field'])
def test_nested_import_types_are_rejected_before_native_state(native,bad):
    n=native;value=_candidate(n)
    if bad=='identity_type':value['identity']['cycle']={'execute':'send'}
    elif bad=='assignees_type':value['item']['assignees']='ou_engineer_a'
    elif bad=='fact_type':value['fact_ids']=[{'fact_id':'not-a-string'}]
    elif bad=='history_state_type':value['history']=[{'state':['sent']}]
    else:value['item']['auto_send']=True
    with pytest.raises(BoundaryError):n.f.import_candidate(n.row,value)
    assert not n.s.rows('SELECT * FROM followup_candidates')
    assert len(n.s.rows('SELECT * FROM action_items'))==1 and not n.calls


def test_adoption_rollback_after_item_insert_and_idempotent_recovery(native):
    n=native;cid=n.f.import_candidate(n.row,_candidate(n,complete=False))
    n.s.conn.execute("CREATE TRIGGER fail_binding BEFORE INSERT ON action_semantics BEGIN SELECT RAISE(ABORT,'injected binding failure'); END")
    with pytest.raises(sqlite3.IntegrityError):n.f.adopt_candidate(n.row,cid)
    assert len(n.s.rows('SELECT * FROM action_items'))==1
    assert not n.s.rows('SELECT * FROM action_aliases')
    assert not n.s.rows("SELECT * FROM item_operations WHERE id LIKE 'followup-import/%'")
    assert n.s.rows('SELECT state FROM followup_candidates')[0]['state']=='candidate'
    n.s.conn.execute('DROP TRIGGER fail_binding')
    with ThreadPoolExecutor(2) as pool:
        items=list(pool.map(lambda _:n.f.adopt_candidate(n.row,cid),range(2)))
    assert items[0]['id']==items[1]['id'] and len(n.s.rows('SELECT * FROM action_items'))==2
    assert json.loads(n.f.semantic(items[0]['id'])['legacy_history'])==[{'state':'legacy_unknown','reason':'history_incomplete'}]
    assert n.s.rows('SELECT state FROM followup_candidates')[0]['state']=='adopted'
    assert len(n.s.rows('SELECT * FROM action_aliases'))==1


@pytest.mark.parametrize('field,value',[('requirements','不同的验收要求'),('deadline','明天 10:00'),('deadline_kind','requirement')])
def test_same_canonical_import_cannot_silently_discard_business_changes(native,field,value):
    n=native;original=_candidate(n);first=n.f.adopt_candidate(n.row,n.f.import_candidate(n.row,original))
    second=copy.deepcopy(original);second.update(producer='group-import',external_id='same-object')
    second['item'][field]=value;candidate=n.f.import_candidate(n.row,second)
    with pytest.raises(BoundaryError,match='EXISTING_ITEM_REVIEW_REQUIRED'):n.f.adopt_candidate(n.row,candidate)
    assert n.am.items.get(first['id'])==first
    assert n.s.rows('SELECT state FROM followup_candidates WHERE id=?',(candidate,))[0]['state']=='candidate'
    assert len(n.s.rows('SELECT * FROM action_items'))==2


def test_same_canonical_identical_business_fields_can_add_a_second_alias(native):
    n=native;original=_candidate(n);first=n.f.adopt_candidate(n.row,n.f.import_candidate(n.row,original))
    second=copy.deepcopy(original);second.update(producer='group-import',external_id='same-object',history_complete=False)
    adopted=n.f.adopt_candidate(n.row,n.f.import_candidate(n.row,second))
    assert adopted['id']==first['id'] and len(n.s.rows('SELECT * FROM action_items'))==2
    assert len(n.s.rows('SELECT * FROM action_aliases WHERE item_id=?',(first['id'],)))==2
    assert json.loads(n.f.semantic(first['id'])['legacy_history'])==[{'state':'legacy_unknown','reason':'history_incomplete'}]


def test_legacy_orphan_is_reviewed_and_reused_without_second_item(native):
    n=native;value=_candidate(n);cid=n.f.import_candidate(n.row,value);old=_old_orphan(n,value)
    n.f.recover_import_orphans();n.f.recover_import_orphans()
    assert n.am.items.get(old['id'])['paused']
    assert n.s.rows('SELECT state FROM followup_candidates WHERE id=?',(cid,))[0]['state']=='needs_review'
    assert len(n.s.rows('SELECT * FROM followup_import_migration_audit'))==1
    with pytest.raises(BoundaryError,match='IMPORT_NOT_ADOPTED'):n.f.prepare(n.row,old['id'])
    nonce=n.f.candidate_card(n.row,cid);drain(n.g)
    card=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    click(n,card,'adopt')
    adopted=n.f.adopt_candidate(n.row,cid)
    assert adopted['id']==old['id'] and not adopted['paused']
    assert len(n.s.rows('SELECT * FROM action_items'))==2
    assert n.f.semantic(old['id'])['canonical_id']=='task_'+digest(value['identity'])
    assert n.s.rows('SELECT state FROM followup_import_recovery')[0]['state']=='adopted'
    assert not n.calls


def test_multiple_legacy_orphans_stay_paused_and_never_create_replacement(native):
    n=native;value=_candidate(n);cid=n.f.import_candidate(n.row,value)
    a=_old_orphan(n,value);b=_old_orphan(n,value,operation='legacy-duplicate')
    n.f.recover_import_orphans()
    assert all(n.am.items.get(x['id'])['paused'] for x in (a,b))
    assert {x['state'] for x in n.f.recovery_rows(cid)}=={'conflict'}
    with pytest.raises(BoundaryError,match='RECOVERY_CONFLICT'):n.f.adopt_candidate(n.row,cid)
    assert len(n.s.rows('SELECT * FROM action_items'))==3
    assert not n.s.rows('SELECT * FROM action_semantics') and not n.calls


def test_legacy_orphan_keeps_real_unknown_occurrence_after_adoption(native):
    n=native;value=_candidate(n);cid=n.f.import_candidate(n.row,value);old=_old_orphan(n,value)
    # Model the original scheduler before the new follow-up adapter existed.
    scheduler=n.am.scheduler;scheduler.followup=None
    plan=scheduler.create(n.am.owner,'old-plan',item_id=old['id'],kind='once',
        rule={'at':n.clock(),'quiet_policy':'exact'},target=n.f.group(n.item),template='此前的已批准提醒',
        policy='fixed_rule',valid_until=n.clock()+3600,window_seconds=600)
    scheduler.approve_plan(n.am.owner,plan['id'],plan['version'],plan['hash'])
    scheduler.scan();n.fault['send']=True;scheduler.dispatch();n.fault['send']=False;scheduler.followup=n.f
    unknown=n.s.rows('SELECT * FROM reminder_occurrences')[0]
    assert unknown['state']=='unknown' and len(n.calls)==1
    n.f.recover_import_orphans();adopted=n.f.adopt_candidate(n.row,cid)
    assert adopted['id']==old['id'] and n.f.legacy_uncertain(old['id'])
    assert n.s.rows('SELECT * FROM reminder_occurrences')[0]==unknown
    n.reader.register_source(replace(n.source,readers=('user:ou_engineer_a',)))
    with pytest.raises(FollowupError,match='evidence_blocked'):n.f.prepare(n.row,old['id'],'recipient_p2p')
    assert len(n.calls)==1


def _v2(n,version='v2'):
    observation=replace(n.obs,version=version,occurred_at_ms=n.obs.occurred_at_ms+(2 if version=='v3' else 1),
        text='实际开测后待核对报告',payload={'record':{'todo':'核对报告','revision':version},'quote':'实际开测后待核对报告'})
    n.reader.record(observation,authoritative=True)
    return n.facts.process(observation,[])


def test_native_source_review_invalidates_old_card_and_is_idempotent(native):
    n=native;old=preview(n);click(n,old);old_refs=n.f.semantic(n.item['id'])['refs'];_v2(n)
    n.am.ux_more_action(n.row,{'page':'followup_source_review','item':n.item['id']})
    drain(n.g);review=n.s.rows("SELECT * FROM am_cards WHERE flow='followup_source_review'")[0]
    rendered=n.s.rows('SELECT body FROM outbox WHERE id=?',(review['outbox_id'],))[0]['body']
    assert '移出当前依据' in rendered and '加入当前依据' in rendered and 'v1' in rendered and 'v2' in rendered
    click(n,review,'review_sources');version=n.f.semantic(n.item['id'])['version']
    click(n,review,'review_sources')
    assert n.f.semantic(n.item['id'])['version']==version
    assert n.s.rows('SELECT refs FROM action_semantic_history WHERE item_id=? AND version=1',(n.item['id'],))[0]['refs']==old_refs
    with pytest.raises(FollowupError):click(n,old)
    newer=preview(n);click(n,newer);n.am.scheduler.dispatch()
    assert len(n.calls)==1


def test_source_changes_after_review_preview_require_new_review(native):
    n=native;n.f.bind(n.row,n.item['id']);_v2(n)
    nonce=n.f.source_review_card(n.row,n.item['id']);drain(n.g)
    card=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0];_v2(n,'v3')
    with pytest.raises(BoundaryError):click(n,card,'review_sources')
    assert n.f.semantic(n.item['id'])['version']==1 and not n.calls


def test_review_card_and_outbox_expire_with_earliest_source_raw(native):
    n=native;n.f.bind(n.row,n.item['id']);raw_expiry=n.clock()+1
    with n.reader.transaction() as db:db.execute('UPDATE observations SET raw_expires_at_ms=?',(int(raw_expiry*1000),))
    nonce=n.f.source_review_card(n.row,n.item['id'])
    card=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    outbox=n.s.rows('SELECT * FROM outbox WHERE id=?',(card['outbox_id'],))[0]
    assert card['expires']<=raw_expiry and outbox['expires']<=raw_expiry
    n.clock.now+=2;drain(n.g)
    assert not n.s.rows("SELECT 1 FROM outbox WHERE id=? AND state='sent'",(outbox['id'],))


def test_review_card_cannot_rebind_stale_body_to_new_access_epoch(native,monkeypatch):
    n=native;n.f.bind(n.row,n.item['id']);actual=n.am.card
    def revoke_then_card(row,**kwargs):
        n.reader.register_source(replace(n.source,enabled=False))
        return actual(row,**kwargs)
    monkeypatch.setattr(n.am,'card',revoke_then_card)
    with pytest.raises(BoundaryError,match='SOURCE_ACCESS_CHANGED'):n.f.source_review_card(n.row,n.item['id'])
    assert not n.s.rows("SELECT * FROM am_cards WHERE flow='followup_source_review'")


def test_review_card_queued_before_revocation_is_not_delivered(native):
    n=native;n.f.bind(n.row,n.item['id']);nonce=n.f.source_review_card(n.row,n.item['id'])
    card=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    assert n.s.rows('SELECT 1 FROM am_query_deliveries WHERE outbox_id=?',(card['outbox_id'],))
    n.reader.register_source(replace(n.source,enabled=False));drain(n.g)
    out=n.s.rows('SELECT * FROM outbox WHERE id=?',(card['outbox_id'],))[0]
    assert out['state']!='sent' and out['message_id'] is None


def test_owner_can_explicitly_replace_revoked_old_source_with_current_project_evidence(native):
    n=native;old=preview(n);click(n,old);project=n.item['project_ref']
    replacement=replace(n.source,source_id='owner-replacement',kind='manual',remote_id='manual-object',
        settings={'subject_id':project,'retain_derived':False})
    n.reader.register_source(replacement)
    observation=replace(n.obs,source_id=replacement.source_id,object_id='reviewed-update',text='已核实开测，需跟进本次报告',
        payload={'subject_id':project,'actor_id':n.am.owner,'trusted_actor':True,
            'structured_claims':[{'field':'execution','value':'in_progress','quote':'已核实开测','confirmed':True}]})
    n.reader.record(observation);processed=n.facts.process(observation,[])
    n.reader.register_source(replace(n.source,enabled=False))
    with pytest.raises(BoundaryError):n.f.source_review_card(n.row,n.item['id'])
    n.f.command(dict(n.row,body='/followup 重审 '+n.item['id']+'｜'+','.join(processed['fact_ids'])))
    drain(n.g);review=n.s.rows("SELECT * FROM am_cards WHERE flow='followup_source_review'")[0]
    click(n,review,'review_sources')
    assert {r['source_id'] for r in json.loads(n.f.semantic(n.item['id'])['refs'])}=={'owner-replacement'}
    with pytest.raises(FollowupError):click(n,old)
    n.am.scheduler.dispatch();assert not n.calls
    current=preview(n);click(n,current);n.am.scheduler.dispatch();assert len(n.calls)==1


@pytest.mark.parametrize('operation',['bind','adopt','claim','review'])
def test_semantic_mutations_acquire_information_before_native_transaction(native,operation):
    n=native;refs=n.f.sources.defaults(n.item['project_ref']);args=None
    if operation=='adopt':args=n.f.import_candidate(n.row,_candidate(n))
    elif operation in ('claim','review'):
        n.f.bind(n.row,n.item['id'])
        if operation=='review':
            nonce=n.f.source_review_card(n.row,n.item['id']);drain(n.g)
            args=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    writes=[];transaction={'information_first':False}
    def trace(statement):
        sql=statement.strip().upper()
        if sql=='BEGIN IMMEDIATE':transaction['information_first']=n.reader.conn.in_transaction
        # Project/identity preflight also logs neutral timing rows in its own
        # short AM transactions. Only mutations of the reviewed business state
        # must be inside the cross-store fence.
        if sql.startswith(('INSERT','UPDATE','DELETE')) and any(table in sql for table in (
                'ACTION_ITEMS','ACTION_ALIASES','ACTION_SEMANTICS','ACTION_SEMANTIC_HISTORY','FOLLOWUP_CANDIDATES')):
            writes.append(transaction['information_first'])
    n.s.conn.set_trace_callback(trace)
    try:
        if operation=='bind':n.f.bind(n.row,n.item['id'],refs=refs)
        elif operation=='adopt':n.f.adopt_candidate(n.row,args)
        elif operation=='claim':n.f.record_claim(n.row,n.item['id'],'execution','in_progress',[r['fact_id'] for r in refs])
        else:n.f.review_sources_action(n.row,args,'review_sources')
    finally:n.s.conn.set_trace_callback(None)
    assert writes and all(writes),'Every native semantic write must start after the information writer fence.'
    assert not n.s.conn.in_transaction and not n.reader.conn.in_transaction


def test_source_review_preserves_unknown_and_cross_channel_barrier(native):
    n=native;old=preview(n);click(n,old);n.fault['send']=True;n.am.scheduler.dispatch();n.fault['send']=False
    original=n.s.rows('SELECT state,request_uuid,message_id FROM followup_intents')[0]
    barriers=n.s.rows('SELECT * FROM followup_delivery_barriers')
    _v2(n);nonce=n.f.source_review_card(n.row,n.item['id']);drain(n.g)
    review=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0];click(n,review,'review_sources')
    assert n.s.rows('SELECT state,request_uuid,message_id FROM followup_intents')[0]==original
    assert n.s.rows('SELECT * FROM followup_delivery_barriers')==barriers
    nonce=n.f.preview_card(dict(n.row,id='another-round'),n.item['id'],'recipient_p2p',new_round=True);drain(n.g)
    card=n.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))[0]
    assert '未发送' in click(n,card)
    n.am.scheduler.dispatch();assert len(n.calls)==1


def test_review_while_claimed_releases_only_proven_unsent_barrier(native):
    n=native;old=preview(n);click(n,old);original_gate=n.f.coordinator.recipient_gate;reviewed=[]
    def review_in_gate(*args):
        result=original_gate(*args)
        if not reviewed and n.s.rows("SELECT 1 FROM followup_intents WHERE state='claimed'"):
            assert n.s.rows('SELECT * FROM followup_delivery_barriers')
            processed=_v2(n)
            refs=n.f.sources.resolve(n.item['project_ref'],processed['fact_ids'])
            n.f.bind(n.row,n.item['id'],refs=refs)
            reviewed.append(True)
        return result
    n.f.coordinator.recipient_gate=review_in_gate
    n.am.scheduler.dispatch()
    assert reviewed and not n.calls
    assert n.s.rows('SELECT state,crossed_send_boundary FROM followup_intents')==[{'state':'blocked','crossed_send_boundary':0}]
    assert not n.s.rows('SELECT * FROM followup_delivery_barriers')
    current=preview(n);click(n,current);n.am.scheduler.dispatch()
    assert len(n.calls)==1


@pytest.mark.parametrize('field,value',[('sender_id','ou_someone_else'),('chat_id','oc_other'),('parent_id','om_other'),('content',{'text':'不同的回复'})])
def test_current_reply_readback_mismatch_never_records_feedback(native,field,value):
    n=native;card=preview(n,'recipient_p2p');click(n,card);n.am.scheduler.dispatch()
    occurrence=n.s.rows('SELECT * FROM reminder_occurrences')[0]
    incoming=event('已开测',number=303,user='ou_engineer_a',chat='oc_engineer')
    message=incoming['event']['message'];message.update(parent_id=occurrence['message_id'],create_time=str(int(n.clock()*1000)))
    n.am.ingest(incoming);n.remote[message['message_id']][field]=value;n.am.step()
    assert n.s.rows('SELECT state FROM am_inbox WHERE id=?',(message['message_id'],))[0]['state']=='failed'
    assert not n.s.rows('SELECT * FROM followup_reply_links') and not n.am.items.history(n.item['id'])
    assert n.am.items.get(n.item['id'])['state']=='waiting'


def test_reply_association_and_feedback_roll_back_together(native):
    n=native;card=preview(n,'recipient_p2p');click(n,card);n.am.scheduler.dispatch()
    occurrence=n.s.rows('SELECT * FROM reminder_occurrences')[0]
    n.s.conn.execute("CREATE TRIGGER fail_link BEFORE INSERT ON followup_reply_links BEGIN SELECT RAISE(ABORT,'injected reply failure'); END")
    mid=_publish_current_reply(n,occurrence,'全部完成，请核验',304)
    assert n.s.rows('SELECT state FROM am_inbox WHERE id=?',(mid,))[0]['state']=='failed'
    assert not n.am.items.history(n.item['id']) and not n.s.rows('SELECT * FROM item_feedback_raw')
    assert not n.s.rows('SELECT * FROM feedback_claims') and not n.s.rows('SELECT * FROM followup_reply_links')
    n.s.conn.execute('DROP TRIGGER fail_link')
    row=n.s.rows('SELECT * FROM am_inbox WHERE id=?',(mid,))[0]
    n.f.reply(row);n.f.reply(row)
    assert len(n.am.items.history(n.item['id']))==1 and len(n.s.rows('SELECT * FROM followup_reply_links'))==1
    assert n.am.items.get(n.item['id'])['state']=='waiting'


def test_report_raw_text_expires_without_leaking_into_permanent_results(native):
    n=native;card=preview(n,'recipient_p2p');click(n,card);n.am.scheduler.dispatch()
    occurrence=n.s.rows('SELECT * FROM reminder_occurrences')[0];text='报告签名 SAMPLE_TEMP_PRIVATE_42，预计周五交付'
    _publish_current_reply(n,occurrence,text,305)
    assert text in n.am.items.history(n.item['id'],include_raw=True)[0]['body']
    permanent='\n'.join(r['result'] for r in n.s.rows('SELECT result FROM item_operations'))
    permanent+='\n'+(n.am.items.get(n.item['id'])['latest_feedback'] or '')
    permanent+='\n'+'\n'.join(r['body'] for r in n.s.rows('SELECT body FROM item_feedback'))
    assert 'SAMPLE_TEMP_PRIVATE_42' not in permanent
    n.am.ux_extra(dict(n.row,id='read-history',expires=n.clock()+2*86400),{'page':'history','item':n.item['id']},{},{})
    history_page=n.s.rows("SELECT * FROM am_cards WHERE flow='ux' ORDER BY rowid DESC LIMIT 1")[0]
    assert history_page['expires']<=n.clock()+86400
    n.clock.now+=86401;n.am.step(maintenance=True)
    assert not n.s.rows('SELECT * FROM item_feedback_raw')
    assert 'SAMPLE_TEMP_PRIVATE_42' not in n.am.items.history(n.item['id'],include_raw=True)[0]['body']
    assert n.s.rows('SELECT kind FROM followup_reply_links')==[{'kind':'reported_update'}]
