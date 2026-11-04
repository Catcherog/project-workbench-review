"""Native admission regressions; SQLite is real and all platform calls are fake."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import sqlite3
from threading import Event

import pytest

from am_info_sync.models import Principal
from am_info_sync.store import Store as InfoStore
from group_ledger import LedgerError
from test_followup_native import native, service, am_rig, base_rig, preview, click


@pytest.mark.parametrize('change', ['source', 'acl', 'disclosure', 'binding'])
def test_change_in_final_recipient_lookup_must_block(native, change):
    """The original three audit failures plus invalidation of the exact binding."""
    n = native
    card = preview(n)
    click(n, card)
    original = n.f.coordinator.recipient_gate
    mutated = []

    def gate(*args):
        result = original(*args)
        if n.s.rows("SELECT id FROM reminder_occurrences WHERE state='sending'") and not mutated:
            if change == 'source':
                n.reader.record(replace(n.obs, version='v2', occurred_at_ms=n.obs.occurred_at_ms + 1,
                                        text='来源更新，旧催办不再成立'), authoritative=True)
            elif change == 'acl':
                n.reader.register_source(replace(n.source, output_chats=()))
            elif change == 'disclosure':
                n.s.execute("UPDATE followup_disclosures SET state='revoked',revision=revision+1")
            else:
                n.s.execute('UPDATE followup_bindings SET invalidated=1')
            mutated.append(change)
        return result

    n.f.coordinator.recipient_gate = gate
    n.am.scheduler.dispatch()
    assert mutated == [change]
    assert not n.calls
    assert n.s.rows('SELECT state FROM followup_intents') == [{'state': 'blocked'}]
    assert not n.s.rows('SELECT intent_id FROM followup_delivery_barriers')


def test_unrelated_source_change_during_final_lookup_still_sends(native):
    n = native
    click(n, preview(n))
    original = n.f.coordinator.recipient_gate

    def gate(*args):
        result = original(*args)
        if n.s.rows("SELECT id FROM reminder_occurrences WHERE state='sending'"):
            n.reader.register_source(replace(n.source, source_id='unrelated', remote_id='unrelated',
                                            settings={'subject_id': 'another-project'}))
        return result

    n.f.coordinator.recipient_gate = gate
    n.am.scheduler.dispatch()
    assert len(n.calls) == 1


def test_second_connection_revocation_committed_before_fence_blocks(native):
    """The last local check observes a real concurrent writer, not a stale cache."""
    n = native
    click(n, preview(n))
    writer = InfoStore(n.reader.path, clock=n.reader.clock)
    original = n.f.coordinator.recipient_gate
    changed = []
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            def gate(*args):
                result = original(*args)
                if n.s.rows("SELECT id FROM reminder_occurrences WHERE state='sending'") and not changed:
                    pool.submit(writer.register_source, replace(n.source, output_chats=())).result(timeout=3)
                    changed.append(True)
                return result

            n.f.coordinator.recipient_gate = gate
            n.am.scheduler.dispatch()
    finally:
        writer.close()
    assert changed == [True] and not n.calls
    assert n.s.rows('SELECT state FROM followup_intents') == [{'state': 'blocked'}]


@pytest.mark.parametrize('database', ['information', 'native'])
def test_concurrent_writer_cannot_commit_between_check_and_send_boundary(native, database):
    """A second SQLite writer commits only after the durable sending boundary.

    Its event is intentionally before the mock SDK call, but after that boundary.
    Such an event cannot promise cancellation of a message that is now in flight.
    """
    n = native
    click(n, preview(n))
    attempted, committed = Event(), Event()
    original_check = n.f.final_dependencies_current
    original_create = n.api.client.im.v1.message.create
    futures = []
    observed = []
    writer = InfoStore(n.reader.path, clock=n.reader.clock) if database == 'information' else None

    def trace(statement):
        if statement == 'BEGIN IMMEDIATE':
            attempted.set()

    def change():
        if writer is not None:
            writer.conn.set_trace_callback(trace)
            writer.register_source(replace(n.source, output_chats=()))
        else:
            with sqlite3.connect(n.f.coordinator.db_path, timeout=3, isolation_level=None) as conn:
                conn.set_trace_callback(trace)
                conn.execute('BEGIN IMMEDIATE')
                conn.execute("UPDATE followup_disclosures SET state='revoked',revision=revision+1")
                conn.execute('COMMIT')
        with sqlite3.connect(n.f.coordinator.db_path) as conn:
            observed.append(conn.execute('SELECT state,crossed_send_boundary FROM followup_intents').fetchone())
        committed.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            def check(*args):
                result = original_check(*args)
                assert result is True
                futures.append(pool.submit(change))
                assert attempted.wait(3), 'second connection never attempted its write'
                assert not committed.wait(0.05), 'writer committed before the sending transaction'
                return result

            def create(request):
                assert committed.wait(3), 'local fence leaked into the network call'
                assert observed == [('sending', 1)]
                # Independently prove neither database is still write-locked.
                for path in (n.reader.path, n.f.coordinator.db_path):
                    with sqlite3.connect(path, timeout=0, isolation_level=None) as conn:
                        conn.execute('BEGIN IMMEDIATE')
                        conn.execute('ROLLBACK')
                return original_create(request)

            n.f.final_dependencies_current = check
            n.api.client.im.v1.message.create = create
            n.am.scheduler.dispatch()
            for future in futures:
                future.result(timeout=3)
    finally:
        if writer is not None:
            writer.close()
    assert observed == [('sending', 1)] and len(n.calls) == 1
    assert n.s.rows('SELECT state FROM followup_intents') == [{'state': 'confirmed'}]


def test_private_directory_calls_run_outside_database_transactions(native):
    n = native
    original_get = n.am.ledger.port.get
    checked = []

    def get(*args, **kwargs):
        assert not n.reader.conn.in_transaction
        assert not n.s.conn.in_transaction
        checked.append(args[0])
        return original_get(*args, **kwargs)

    n.am.ledger.port.get = get
    click(n, preview(n, 'recipient_p2p'))
    n.am.scheduler.dispatch()
    assert any(path.endswith('/members') for path in checked)
    assert len(n.calls) == 1


def test_fact_query_borrows_exact_transaction_without_committing_it(native):
    n = native
    principal = Principal(n.f.owner, n.f.tenant)
    expected = n.facts.query(n.item['project_ref'], principal)
    with n.reader.transaction() as conn:
        actual = n.facts.query(n.item['project_ref'], principal, connection=conn)
        assert actual == expected and conn.in_transaction
    assert not n.reader.conn.in_transaction
    with pytest.raises(RuntimeError, match='active transaction'):
        n.facts.query(n.item['project_ref'], principal, connection=n.reader.conn)
    with sqlite3.connect(':memory:') as foreign:
        foreign.execute('BEGIN IMMEDIATE')
        with pytest.raises(RuntimeError, match='active transaction'):
            n.facts.query(n.item['project_ref'], principal, connection=foreign)


@pytest.mark.parametrize('error', [TimeoutError, LedgerError])
def test_final_private_directory_read_failure_is_blocked_and_reviewable(native, error):
    n = native
    click(n, preview(n, 'recipient_p2p'))
    original = n.f.sources.disclosure_memberships
    calls = []

    def memberships(target):
        calls.append(True)
        if len(calls) == 3:  # both normal evidence gates succeeded; final lookup fails
            raise error('PLATFORM_READ_UNAVAILABLE')
        return original(target)

    n.f.sources.disclosure_memberships = memberships
    n.am.scheduler.dispatch()
    assert len(calls) == 3 and not n.calls
    assert n.s.rows('SELECT state,crossed_send_boundary FROM followup_intents') == [
        {'state': 'blocked', 'crossed_send_boundary': 0}]
    assert n.s.rows('SELECT state FROM reminder_occurrences') == [{'state': 'cancelled'}]
    assert not n.s.rows('SELECT intent_id FROM followup_delivery_barriers')
    n.f.sources.disclosure_memberships = original
    click(n, preview(n, 'recipient_p2p'))
    n.am.scheduler.dispatch()
    assert len(n.calls) == 1  # only the new, separately approved exact preview sends


def test_rolled_back_local_check_failure_does_not_create_unknown(native):
    n = native
    click(n, preview(n))

    def fail(*args):
        raise sqlite3.OperationalError('synthetic local check failure')

    n.f.final_dependencies_current = fail
    n.am.scheduler.dispatch()
    assert not n.calls
    assert n.s.rows('SELECT state,crossed_send_boundary FROM followup_intents') == [
        {'state': 'blocked', 'crossed_send_boundary': 0}]
    assert not n.s.rows('SELECT intent_id FROM followup_delivery_barriers')
    assert not n.reader.conn.in_transaction and not n.s.conn.in_transaction


def test_guard_exit_failure_after_sending_commit_remains_unknown(native):
    n = native
    click(n, preview(n))
    original = n.f.coordinator.final_native_guard

    @contextmanager
    def fail_after_transition(request):
        with original(request) as check:
            yield check
            raise RuntimeError('synthetic evidence fence exit failure')

    n.f.coordinator.final_native_guard = fail_after_transition
    n.am.scheduler.dispatch()
    assert not n.calls
    assert n.s.rows('SELECT state,crossed_send_boundary FROM followup_intents') == [
        {'state': 'unknown', 'crossed_send_boundary': 1}]
    assert len(n.s.rows('SELECT intent_id FROM followup_delivery_barriers')) == 1


def test_process_interruption_in_local_check_keeps_crash_recovery_evidence(native):
    n = native
    click(n, preview(n))

    def interrupt(*args):
        raise KeyboardInterrupt('synthetic process interruption')

    n.f.final_dependencies_current = interrupt
    with pytest.raises(KeyboardInterrupt):
        n.am.scheduler.dispatch()
    assert not n.calls
    assert n.s.rows('SELECT state,crossed_send_boundary FROM followup_intents') == [
        {'state': 'claimed', 'crossed_send_boundary': 0}]
    assert len(n.s.rows('SELECT intent_id FROM followup_delivery_barriers')) == 1
