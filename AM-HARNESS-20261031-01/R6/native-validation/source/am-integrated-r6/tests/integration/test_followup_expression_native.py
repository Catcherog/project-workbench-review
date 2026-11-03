"""Native AM services/SQLite; synthetic platform fixture, no real messages."""
import json
from dataclasses import replace
import pytest

from test_followup_native import native, service, am_rig, base_rig, preview, click
from am_followup_expression import NativeFollowupExpression
from am_style.runtime import TerminalPresenter, StaleFrame
from am_style.followup import render_followup
from am_style.contracts import ContractError


def expression(n, mode="enforce"):
    result=NativeFollowupExpression(n.f,TerminalPresenter(mode=mode,wall_clock=n.clock))
    n.f.expression=result
    return result


def sent(n):
    card=preview(n);click(n,card);n.am.scheduler.dispatch()
    return n.s.rows('SELECT * FROM reminder_occurrences')[0]


def prepare(n,e):
    return e.prepare(n.row,n.item['id'],legacy_text="原状态文字",fastpath=True)


def test_default_off_does_not_capture_or_call_model(native,monkeypatch):
    n=native;e=NativeFollowupExpression(n.f)
    monkeypatch.setattr(e,"capture",lambda *a,**k:pytest.fail("off must not capture"))
    assert e.prepare(n.row,n.item['id'],legacy_text="保留") is None
    assert not n.calls


def test_native_exact_receipt_becomes_bound_speech_without_send(native):
    n=native;sent(n);e=expression(n)
    snapshot=e.capture(n.row,n.item['id'])
    assert snapshot.data['delivery']['state']=='verified'
    assert "已发出" in render_followup(snapshot)
    assert "尚未核验完成" in render_followup(snapshot)
    assert len(n.calls)==1 and n.am.items.get(n.item['id'])['state']=='waiting'


def test_outcome_change_between_prepare_and_enqueue_is_rejected(native):
    n=native;sent(n);e=expression(n);p=prepare(n,e)
    count=len(n.s.rows('SELECT * FROM outbox'))
    n.am.items.change(n.am.owner,'pause-after-prepare',n.item['id'],1,'pause')
    with pytest.raises(StaleFrame):e.enqueue(p)
    assert len(n.s.rows('SELECT * FROM outbox'))==count and len(n.calls)==1


def test_feedback_after_enqueue_invalidates_outbound_status(native):
    n=native;o=sent(n);e=expression(n);p=prepare(n,e);out=e.enqueue(p)
    row=n.s.rows('SELECT * FROM outbox WHERE id=?',(out,))[0]
    assert e.valid_notification(row) is True
    n.s.execute('INSERT INTO followup_reply_links VALUES(?,?,?,?,?,?)',
        ('new-reply',n.item['id'],o['id'],'ou_engineer_a','reported_update',n.clock()))
    assert e.valid_notification(row) is False
    assert n.am.valid_notification(row) is False
    assert len(n.calls)==1


def test_permission_revocation_rejects_without_throwing_out_of_gateway(native):
    n=native;sent(n);e=expression(n);out=e.enqueue(prepare(n,e))
    row=n.s.rows('SELECT * FROM outbox WHERE id=?',(out,))[0]
    n.am.flags['items']=False
    assert e.valid_notification(row) is False


def test_final_text_mutation_or_nontext_transport_is_rejected(native):
    n=native;sent(n);e=expression(n);out=e.enqueue(prepare(n,e))
    row=n.s.rows('SELECT * FROM outbox WHERE id=?',(out,))[0]
    assert e.valid_notification(dict(row,body=row['body']+'done')) is False
    assert e.valid_notification(dict(row,kind='interactive')) is False


def test_source_epoch_change_rejects_outbound_status(native):
    n=native;sent(n);e=expression(n);out=e.enqueue(prepare(n,e))
    row=n.s.rows('SELECT * FROM outbox WHERE id=?',(out,))[0]
    n.reader.register_source(replace(n.source,enabled=False))
    assert e.valid_notification(row) is False


def test_unknown_only_promises_check_for_actual_native_queue(native):
    n=native;o=sent(n);e=expression(n)
    n.s.execute("UPDATE reminder_occurrences SET state='unknown',readback_state='pending',reconcile_attempts=0,next_reconcile=0 WHERE id=?",(o['id'],))
    n.s.execute("UPDATE followup_intents SET state='unknown'")
    assert "我确定一下" in render_followup(e.capture(n.row,n.item['id']))
    n.s.execute('UPDATE reminder_occurrences SET reconcile_attempts=6 WHERE id=?',(o['id'],))
    assert "我确定一下" not in render_followup(e.capture(n.row,n.item['id']))
    n.s.execute('UPDATE reminder_occurrences SET reconcile_attempts=0,message_id=NULL WHERE id=?',(o['id'],))
    assert "我确定一下" not in render_followup(e.capture(n.row,n.item['id']))
    assert len(n.calls)==1


def test_bound_receipt_tampering_cannot_be_described_as_sent(native):
    n=native;o=sent(n);e=expression(n);out=e.enqueue(prepare(n,e))
    row=n.s.rows('SELECT * FROM outbox WHERE id=?',(out,))[0]
    n.s.execute('UPDATE reminder_occurrences SET receipt=? WHERE id=?',(json.dumps({'message_id':'wrong'}),o['id']))
    from am_followup.followup import FollowupError
    with pytest.raises(FollowupError):e.capture(n.row,n.item['id'])
    assert e.valid_notification(row) is False


def test_feedback_actor_removed_from_assignment_is_not_still_called_owner(native):
    n=native;o=sent(n);e=expression(n)
    n.s.execute('INSERT INTO followup_reply_links VALUES(?,?,?,?,?,?)',
        ('reply',n.item['id'],o['id'],'ou_engineer_a','reported_update',n.clock()))
    n.s.execute('UPDATE action_items SET assignees=? WHERE id=?',(json.dumps(['ou_other']),n.item['id']))
    with pytest.raises(StaleFrame):e.capture(n.row,n.item['id'])


def test_metrics_kept_separate_from_native_delivery_evidence(native):
    n=native;sent(n);e=expression(n);p=prepare(n,e);out=e.enqueue(p)
    evidence=n.s.rows('SELECT * FROM followup_expression_outputs WHERE outbox_id=?',(out,))[0]
    metrics=json.loads(evidence['metrics_json'])
    assert metrics['presentation_calls']==0 and metrics['reason']=='fastpath_no_model'
    assert evidence['delivery_state']=='queued'
    with n.s.tx() as db:e.delivered(db,{'id':out},'receipt')
    assert n.s.rows('SELECT delivery_state FROM followup_expression_outputs WHERE outbox_id=?',(out,))==[{'delivery_state':'native_sent'}]


def test_expiry_cleanup_and_disabling_expression_do_not_allow_old_candidate(native):
    n=native;sent(n);e=expression(n);out=e.enqueue(prepare(n,e))
    row=n.s.rows('SELECT * FROM outbox WHERE id=?',(out,))[0]
    e.presenter.mode='off'
    assert e.valid_notification(row) is False
    n.s.execute('UPDATE followup_expression_outputs SET expires=0')
    e.cleanup()
    assert not n.s.rows('SELECT * FROM followup_expression_outputs')
    assert e.valid_notification(row) is False


def test_exact_preview_must_bypass_expression(native):
    n=native;e=expression(n)
    with pytest.raises(ContractError,match='not_rewritable'):
        e.prepare(dict(n.row,_response_kind='followup_text_preview'),n.item['id'],legacy_text='完整预览')


def test_real_status_entry_off_uses_native_text_without_expression_capture(native, monkeypatch):
    from test_followup_text_host import incoming
    n=native
    monkeypatch.setattr(n.f.expression,'capture',lambda *a,**k:pytest.fail('off captured expression'))
    row=incoming(n,'跟进状态 '+n.item['id'],2101)
    assert row['kind']=='text'
    n.am.step(row)
    output=n.s.rows('SELECT * FROM outbox ORDER BY rowid DESC LIMIT 1')[0]
    assert output['kind']=='text' and '业务完成：尚未核验完成。' in output['body']
    assert not n.s.rows('SELECT * FROM followup_expression_outputs') and not n.calls


@pytest.mark.parametrize('mode',['shadow','enforce'])
def test_real_status_entry_uses_existing_outbox_and_fresh_expression_guard(native,mode):
    from test_followup_text_host import incoming
    n=native;sent(n);e=expression(n,mode)
    row=incoming(n,'跟进状态 '+n.item['id'],2102)
    n.am.step(row)
    outputs=n.s.rows('SELECT o.* FROM outbox o JOIN followup_expression_outputs x ON x.outbox_id=o.id')
    assert len(outputs)==1 and outputs[0]['kind']=='text'
    assert '消息记录已核对' in outputs[0]['body'] and '尚未核验完成' in outputs[0]['body']
    assert n.am.valid_notification(outputs[0]) is True
    metrics=json.loads(n.s.rows('SELECT metrics_json FROM followup_expression_outputs')[0]['metrics_json'])
    assert metrics['mode']==mode and metrics['presentation_calls']==0
    assert len(n.calls)==1 and n.am.items.get(n.item['id'])['state']=='waiting'


def test_real_status_entry_does_not_fallback_stale_expression_to_old_details(native,monkeypatch):
    from test_followup_text_host import incoming
    n=native;sent(n);e=expression(n)
    enqueue=e.enqueue
    def changed(prepared):
        n.am.items.change(n.am.owner,'entry-race',n.item['id'],1,'pause')
        return enqueue(prepared)
    monkeypatch.setattr(e,'enqueue',changed)
    row=incoming(n,'跟进状态 '+n.item['id'],2103)
    n.am.step(row)
    assert not n.s.rows('SELECT * FROM followup_expression_outputs')
    outputs=n.s.rows('SELECT * FROM outbox ORDER BY rowid DESC LIMIT 1')
    assert outputs[0]['kind']=='text' and '这次操作未完成' in outputs[0]['body']
    assert len(n.calls)==1
