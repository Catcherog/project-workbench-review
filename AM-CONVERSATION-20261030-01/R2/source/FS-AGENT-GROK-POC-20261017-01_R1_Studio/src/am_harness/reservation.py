"""Task-bound dispatch reservations; original business journals remain authoritative.

The admission commit linearizes against cancellation in the original AM database.
A committed reservation is never undone by cancellation or automatically replayed.
Downstream journals also call reserve_effect in their actual dispatch transaction.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
from .store import canonical

_current = ContextVar('am_harness_action_reservation', default=None)


@contextmanager
def action_context(host, ctx, action):
    host.bridge.authorize(ctx, 'execute', action['arguments'])
    fence = host.hooks.fence
    if fence is None:
        raise RuntimeError('HARNESS_UNBOUND_RUN')
    expected = (action['version'], action['digest'], action['execution_id'])
    fresh = host.bridge.store.get_action(ctx, action['id'])
    if fresh['status'] != 'executing' or expected != (fresh['version'], fresh['digest'], fresh['execution_id']):
        raise RuntimeError('HARNESS_ACTION_VERSION_CHANGED')
    token = _current.set((host, fence, action))
    try:
        with host.s.tx() as conn:
            reserve_effect(conn, action['id'], 'action',
                           {'tool': action['tool_name'], 'version': action['version'],
                            'digest': action['digest'], 'execution_id': action['execution_id']})
        yield
    finally:
        _current.reset(token)


def reserve_effect(conn, operation_id, kind, payload):
    """Optional only for original non-harness calls; never a permissive authorizer."""
    bound = _current.get()
    if bound is None:
        return
    host, fence, action = bound
    if kind in ('native_document','document_mount') and (not payload.get('accepted_hash') or payload['accepted_hash'] != payload.get('content_hash')):
        raise RuntimeError('HARNESS_CONTENT_ADOPTION_REQUIRED')
    host.effects._transaction(conn)
    host.tasks.check_in_transaction(conn, fence, allowed_states=('running',))
    key = hashlib.sha256(canonical([action['id'], kind, operation_id]).encode()).hexdigest()
    value_hash = hashlib.sha256(canonical(payload).encode()).hexdigest()
    old = conn.execute('SELECT * FROM am_harness_reservations WHERE id=?', (key,)).fetchone()
    if old:
        if (old['run_id'], old['revision'], old['cancel_epoch'], old['payload_hash']) != (fence.run_id, fence.revision, fence.cancel_epoch, value_hash):
            raise RuntimeError('HARNESS_RESERVATION_CONFLICT')
        raise RuntimeError('HARNESS_RESERVATION_RECONCILE_REQUIRED')
    conn.execute('INSERT INTO am_harness_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                 (key, fence.run_id, fence.scope_key, fence.revision, fence.cancel_epoch,
                  fence.generation, action['id'], kind, value_hash, 'reserved', None, host.s.clock()))


def record_result(host, action_id, result):
    # This receipt is metadata; the original action/accepted_hash/receipt is the authority.
    state = result.get('status', 'unknown') if isinstance(result, dict) else 'unknown'
    if state not in ('succeeded', 'failed', 'unknown'):
        state = 'unknown'
    receipt_hash = hashlib.sha256(str(result.get('receipt_id', '')).encode()).hexdigest() if isinstance(result, dict) and result.get('receipt_id') else None
    host.s.execute('UPDATE am_harness_reservations SET state=?,receipt_hash=? WHERE action_id=?',
                   (state, receipt_hash, action_id))
