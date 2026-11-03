"""Independent dispatch/recovery probes: original native fixture, simulated Feishu only."""
import json
import pytest

from test_followup_native import native, service, am_rig, base_rig, preview, click
from test_gateway import drain
from am_followup_host import FollowupHost
from fs_agent.project_catalog import canonical, digest


def second_item(n):
    item = n.am.items.create(n.am.owner, 'review-independent-item',
        project_ref=n.item['project_ref'], description='独立事项核对',
        requirements='独立事项进度', assignees=['ou_engineer_a'],
        source=json.loads(n.item['source']))
    nonce = n.am.followup.preview_card(dict(n.row, id='independent-preview-request', created=n.clock()), item['id'])
    drain(n.g)
    card = n.s.rows('SELECT * FROM am_cards WHERE nonce=?', (nonce,))[0]
    click(n, card, created=n.clock())
    return item


def states(n):
    return {
        'calls': len(n.calls),
        'native': n.s.rows('SELECT id,item_id,state,readback_state FROM reminder_occurrences ORDER BY rowid'),
        'intents': n.s.rows('SELECT intent_id,state,reason FROM followup_intents ORDER BY rowid'),
        'barriers': n.s.rows('SELECT intent_id FROM followup_delivery_barriers'),
    }


def test_recovery_bridges_already_verified_native_receipt(native, monkeypatch):
    n = native
    card = preview(n)
    click(n, card)
    def crash(*a, **kw):
        raise SystemExit('simulated crash after native verified commit, before intent finish')
    monkeypatch.setattr(n.f.coordinator, '_finish', crash)
    with pytest.raises(SystemExit):
        n.am.scheduler.dispatch()
    assert len(n.calls) == 1
    assert n.s.rows('SELECT readback_state FROM reminder_occurrences')[0]['readback_state'] == 'verified'
    n.am.followup = FollowupHost(n.am)
    for _ in range(3):
        n.am.scheduler.step()
    print('VERIFIED_NATIVE_RECOVERY', states(n))
    assert n.s.rows('SELECT state FROM followup_intents')[0]['state'] == 'confirmed'
    assert not n.s.rows('SELECT * FROM followup_delivery_barriers')


def test_claim_recovery_does_not_starve_unrelated_occurrence(native, monkeypatch):
    n = native
    card = preview(n)
    click(n, card)
    def crash(*a, **kw):
        raise SystemExit('simulated crash after coordinator claim, before native sending')
    monkeypatch.setattr(n.f.coordinator, 'evidence_gate', crash)
    with pytest.raises(SystemExit):
        n.am.scheduler.dispatch()
    n.am.followup = FollowupHost(n.am)
    second_item(n)
    for _ in range(3):
        n.am.scheduler.step()
    print('CLAIM_RECOVERY', states(n))
    assert len(n.calls) == 1, 'unrelated approved occurrence must still dispatch'


def test_uncertain_prior_round_does_not_starve_unrelated_occurrence(native):
    n = native
    first = preview(n)
    click(n, first)
    nonce = n.f.preview_card(dict(n.row, id='explicit-second-round'), n.item['id'], new_round=True)
    drain(n.g)
    second = n.s.rows('SELECT * FROM am_cards WHERE nonce=?', (nonce,))[0]
    click(n, second)
    second_item(n)
    n.fault['send'] = True
    n.am.scheduler.dispatch()
    n.fault['send'] = False
    for _ in range(3):
        n.am.scheduler.step()
    print('PRIOR_UNKNOWN_STARVATION', states(n))
    assert len(n.calls) == 2, 'one uncertain first send plus one independent send expected'


def test_reconcile_callback_failure_is_retried_after_native_verified(native, monkeypatch):
    n = native
    card = preview(n)
    click(n, card)
    actual_read = n.f.port.reconcile
    n.f.port.reconcile = lambda *a: None
    n.am.scheduler.dispatch()
    n.f.port.reconcile = actual_read
    occurrence = n.s.rows('SELECT * FROM reminder_occurrences')[0]
    actual_callback = n.f.reconciled
    def fail_once(*a):
        raise RuntimeError('simulated failure between native verified and intent reconciliation')
    monkeypatch.setattr(n.f, 'reconciled', fail_once)
    assert n.am.scheduler.reconcile(occurrence['id'], manual=True) is False
    monkeypatch.setattr(n.f, 'reconciled', actual_callback)
    for _ in range(3):
        n.am.scheduler.step()
    print('RECONCILE_CALLBACK_FAILURE', states(n))
    assert n.s.rows('SELECT state FROM followup_intents')[0]['state'] == 'confirmed'


def verified_pending(n, monkeypatch):
    """Produce the real native checkpoint before one local callback failure."""
    card = preview(n)
    click(n, card)
    read = n.f.port.reconcile
    n.f.port.reconcile = lambda *a: None
    n.am.scheduler.dispatch()
    n.f.port.reconcile = read
    occurrence = n.s.rows('SELECT * FROM reminder_occurrences')[0]
    with monkeypatch.context() as patch:
        def fail(*args):
            raise RuntimeError('one local callback failure')
        patch.setattr(n.f, 'reconciled', fail)
        assert n.am.scheduler.reconcile(occurrence['id'], manual=True) is False
    return n.am.scheduler.occurrence(occurrence['id'])


def test_local_result_retry_uses_backoff_and_never_rereads_platform(native, monkeypatch):
    n = native
    occurrence = verified_pending(n, monkeypatch)
    original_uuid = occurrence['request_key']
    original = n.f.coordinator.reconcile
    calls = []
    def transient(*args):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError('temporary local contention')
        return original(*args)
    monkeypatch.setattr(n.f.coordinator, 'reconcile', transient)
    monkeypatch.setattr(n.f.port, 'reconcile', lambda *args: pytest.fail('recovery must not reread the platform'))
    n.f.recover_adoptions()
    retry = n.s.rows('SELECT * FROM followup_result_retries')[0]
    assert retry['attempts'] == 1 and retry['next_attempt'] > n.clock()
    for _ in range(3):
        n.am.scheduler.step()
    assert len(calls) == 1 and len(n.calls) == 1
    n.clock.now = retry['next_attempt']
    n.am.scheduler.step()
    assert len(calls) == 2 and len(n.calls) == 1
    assert n.s.rows('SELECT state FROM followup_intents')[0]['state'] == 'confirmed'
    assert n.am.scheduler.occurrence(occurrence['id'])['request_key'] == original_uuid
    assert not n.s.rows('SELECT * FROM followup_delivery_barriers')
    assert not n.s.rows('SELECT * FROM followup_result_retries')


def test_historical_verified_result_converges_after_expiry_with_sending_disabled(native, monkeypatch):
    n = native
    occurrence = verified_pending(n, monkeypatch)
    original_uuid = occurrence['request_key']
    n.clock.now += 601
    n.am.flags['scheduler'] = False
    monkeypatch.setattr(n.f.port, 'reconcile', lambda *args: pytest.fail('historical reconciliation is local'))
    assert n.am.scheduler.step()
    assert n.s.rows('SELECT state FROM followup_intents')[0]['state'] == 'confirmed'
    assert n.am.scheduler.occurrence(occurrence['id'])['request_key'] == original_uuid
    assert len(n.calls) == 1 and not n.s.rows('SELECT * FROM followup_delivery_barriers')
    n.am.scheduler.step()
    assert len(n.calls) == 1


@pytest.mark.parametrize('change', ['request_uuid', 'body', 'target', 'message_id'])
def test_native_verified_mapping_mismatch_never_releases_unknown(native, monkeypatch, change):
    n = native
    occurrence = verified_pending(n, monkeypatch)
    if change == 'request_uuid':
        n.s.execute('UPDATE followup_adoptions SET request_uuid=? WHERE occurrence_id=?', ('other-request', occurrence['id']))
    elif change in ('body', 'target'):
        payload = json.loads(occurrence['payload'])
        if change == 'body':
            payload['body'] = '另一条正文'
        else:
            payload['target']['payload']['group']['id'] = 'oc_other'
        n.s.execute('UPDATE reminder_occurrences SET payload=?,hash=? WHERE id=?',
                    (canonical(payload), digest(payload), occurrence['id']))
    else:
        n.s.execute('UPDATE reminder_occurrences SET message_id=? WHERE id=?', ('om_other', occurrence['id']))
    monkeypatch.setattr(n.f.port, 'reconcile', lambda *args: pytest.fail('no search or network retry'))
    n.f.recover_adoptions()
    assert n.s.rows('SELECT state FROM followup_intents')[0]['state'] == 'unknown'
    assert n.s.rows('SELECT * FROM followup_delivery_barriers')
    retry = n.s.rows('SELECT * FROM followup_result_retries')[0]
    assert retry['error'] == 'recovery_native_mapping_changed'
    assert len(n.calls) == 1


def test_completed_native_result_recovers_without_restarting_service(native, monkeypatch):
    n = native
    card = preview(n)
    click(n, card)
    with monkeypatch.context() as patch:
        def crash(*args):
            raise SystemExit('local result commit interrupted')
        patch.setattr(n.f.coordinator, '_finish', crash)
        with pytest.raises(SystemExit):
            n.am.scheduler.dispatch()
    assert n.s.rows('SELECT state FROM followup_intents')[0]['state'] == 'sending'
    n.am.scheduler.step()
    assert n.s.rows('SELECT state FROM followup_intents')[0]['state'] == 'confirmed'
    assert not n.s.rows('SELECT * FROM followup_delivery_barriers') and len(n.calls) == 1


def test_waiting_round_expiry_never_retries_unknown_and_later_item_can_send(native):
    n = native
    first = preview(n)
    click(n, first)
    nonce = n.f.preview_card(dict(n.row, id='second-round-before-fault'), n.item['id'], new_round=True)
    drain(n.g)
    click(n, n.s.rows('SELECT * FROM am_cards WHERE nonce=?', (nonce,))[0])
    n.fault['send'] = True
    n.am.scheduler.dispatch()
    n.fault['send'] = False
    uuid_before = n.s.rows('SELECT request_uuid FROM followup_intents ORDER BY rowid')[0]['request_uuid']
    n.clock.now += 601
    independent = second_item(n)
    for _ in range(3):
        n.am.scheduler.step()
    first_intent = n.s.rows('SELECT * FROM followup_intents ORDER BY rowid')[0]
    assert first_intent['state'] == 'unknown' and first_intent['request_uuid'] == uuid_before
    independent_send = n.s.rows('SELECT * FROM reminder_occurrences WHERE item_id=?', (independent['id'],))[0]
    assert independent_send['state'] == 'sent' and len(n.calls) == 2
