"""Two real SQLite stores and the original gateway; only platform I/O is fake."""
from copy import deepcopy
from dataclasses import replace
import json
import threading
from types import SimpleNamespace

import pytest

from am_information import AMInformation
from am_info_sync.document_snapshot import capture_document_snapshot, request_scope
from am_info_sync.models import Observation, Page, Principal, Source, digest
from am_info_sync.runtime import InformationService
from am_info_sync.store import Store
from fs_agent.config import BoundaryError
from fs_agent.document_view_binding import capture, SCOPED_SOURCE_FENCE
from test_document_views_r9_fix1 import (
    doc, harness, convo, ux, service, am_rig, base_rig, open_view)
from test_am_ux1 import click
from test_gateway import drain


def set_binding(r, schema="am-document-evidence-binding/2"):
    _, binding = capture_document_snapshot(r.info, r.info_service, r.project,
        principal=Principal(r.row["user"], r.row["tenant"], ("th2-query",)),
        scope=request_scope(r.row), project_code="IRAD-2099-001",
        expires=r.clock()+600, expected_access_version=r.info.access_version(),
        binding_schema=schema)
    draft = r.s.rows("SELECT * FROM logic_drafts WHERE id=?", (r.ident,))[0]
    rules = json.loads(draft["rules"])
    rules["document_binding"] = binding
    payload = {"document_binding": binding, "request": {"project_id": "p"}}
    r.s.execute("UPDATE logic_drafts SET rules=? WHERE id=?", (json.dumps(rules), r.ident))
    r.s.execute("UPDATE amdoc_results SET payload=? WHERE draft_id=?", (json.dumps(payload), r.ident))
    return binding


@pytest.fixture
def scoped_doc(doc):
    r = doc
    r.info = Store(":memory:", clock=lambda: int(r.clock()*1000))
    r.info_service = InformationService(r.info)
    r.project = {"key": "p", "title": "IRAD-2099-001 合成项目",
        "identity_status": "verified", "source_revision": "1",
        "关键日期": "", "待办": "", "项目进展": "", "人员与职责": ""}
    common = dict(tenant_id=r.row["tenant"], owner_user_id=r.row["user"],
                  enabled=True, raw_retention_seconds=86400)
    r.source = Source("source-a", "manual", "local-a", **common,
        settings={"subject_id": "p", "freshness_seconds": 600})
    r.other = Source("source-b", "manual", "local-b", **common,
        settings={"subject_id": "other-project", "freshness_seconds": 600})
    ledger = Source("th2-ledger", "ledger_snapshot", "fixed/sheet", **common,
        settings={"host_managed": True, "subject_ids": ["p"],
                  "freshness_seconds": 600})
    for source in (r.source, r.other, ledger):
        r.info.register_source(source)
    record = {"title": r.project["title"], "identity_status": "verified",
        "fields": {k: r.project[k] for k in ("关键日期", "待办", "项目进展", "人员与职责")}}
    raw = Observation("th2-ledger", "p", "ledger:1:"+digest(record),
        r.info.clock(), text="合成台账原件",
        payload={"record": record, "subject_id": "p", "revision_id": 1,
                 "quote": r.project["title"], "time_basis": "observed_at"})
    r.info.record(raw, authoritative=True)
    r.info_service.facts.process(r.info.get_observation(raw.source_id, raw.object_id, raw.version), [])
    raw = Observation("source-a", "message", "v1", r.info.clock(), text="合成工程进展，待业务核验。")
    r.info.record(raw, authoritative=True)
    r.info_service.facts.process(r.info.get_observation(raw.source_id, raw.object_id, raw.version), [{
        "source_id": raw.source_id, "object_id": raw.object_id, "version": raw.version,
        "subject_id": "p", "field": "progress", "value": raw.text, "quote": raw.text,
        "assertion_type": "reported"}])
    r.info.conn.execute("UPDATE sources SET availability='ok',last_checked_ms=?", (r.info.clock(),))
    host = AMInformation.__new__(AMInformation)
    host.store, host.service = r.info, r.info_service
    host.am = SimpleNamespace(
        query_grant=lambda row: ["*"], query_projects=lambda row: [deepcopy(r.project)],
        query_group=lambda row: None,
        snapshots=SimpleNamespace(lock=threading.RLock(), latest="local",
            versions={"local": {"complete": True, "rows": [r.project]}}))
    r.info_host = host
    previous = r.am.information
    r.am.information = host
    r.g.logic.shared_evidence = host.evidence_bundle
    r.g.logic.shared_evidence_current = host.document_evidence_current
    set_binding(r)
    try:
        yield r
    finally:
        r.am.information = previous
        r.info.close()


def enqueue(r, *, query=True, stale_query_epoch=None):
    row = dict(r.row)
    if query:
        row.update(_query_read=True, _query_grant=r.am.query_grant(dict(row)))
    if stale_query_epoch is not None:
        row["_source_access_version"] = stale_query_epoch
    draft = r.s.rows("SELECT * FROM logic_drafts WHERE id=?", (r.ident,))[0]
    row["_document_binding"] = capture(r.g.logic, row, draft)
    ident = r.am.notify(row, text="SYNTHETIC_SCOPED_DOCUMENT", kind="document_result",
                       object_id=r.ident, version=draft["revision"])
    return r.s.rows("SELECT * FROM outbox WHERE id=?", (ident,))[0]


def change_other(r):
    r.info.register_source(replace(r.other, readers=("user:unrelated-reader",)))


def test_unrelated_acl_change_between_capture_queue_and_dispatch_still_delivers(scoped_doc):
    r = scoped_doc
    old_epoch = r.info.access_version()
    change_other(r)
    out = enqueue(r, stale_query_epoch=old_epoch)
    assert r.s.rows('SELECT source_access_version FROM am_source_deliveries WHERE outbox_id=?',
                    (out['id'],))[0]['source_access_version'] == old_epoch
    assert r.s.rows('SELECT source_fence FROM am_document_source_outputs WHERE outbox_id=?',
                    (out['id'],))[0]['source_fence'].startswith(SCOPED_SOURCE_FENCE)
    assert not r.s.rows('SELECT 1 FROM am_conversation_outputs WHERE outbox_id=?', (out['id'],))
    assert not r.s.rows('SELECT 1 FROM am_harness_outbox WHERE outbox_id=?', (out['id'],))
    assert r.am.query_delivery_authorized(out) is True
    assert r.g.deliver_one()
    assert r.s.rows("SELECT state FROM outbox WHERE id=?", (out["id"],))[0]["state"] == "sent"
    assert len(r.api.sent) == 1


def test_queued_view_survives_unrelated_acl_at_final_transport_guard(scoped_doc):
    r = scoped_doc
    out = enqueue(r)
    original = r.api.send
    def send(row, guard):
        change_other(r)
        assert guard() is True
        return original(row, guard)
    r.api.send = send
    assert r.g.deliver_one()
    assert r.s.rows("SELECT state FROM outbox WHERE id=?", (out["id"],))[0]["state"] == "sent"


def test_related_denial_then_restore_rejects_previously_queued_document(scoped_doc):
    r = scoped_doc
    out = enqueue(r)
    r.info.mark_source_error("source-a", "synthetic-denial", permission_denied=True)
    run = r.info.begin_sync("source-a")
    r.info.save_page(run["run_id"], run["lease_token"], None, Page(()))
    assert r.info.source_status("source-a")["availability"] == "ok"
    assert r.am.query_delivery_authorized(out) is False
    assert r.g.deliver_one()
    assert r.s.rows("SELECT state FROM outbox WHERE id=?", (out["id"],))[0]["state"] == "rejected"
    assert r.api.sent == []


@pytest.mark.parametrize("change", ["body", "expires", "marker", "binding", "view_deleted", "both_deleted"])
def test_scoped_fence_cannot_authorize_tampered_payload_or_extended_ttl(scoped_doc, change):
    r = scoped_doc
    out = enqueue(r, query=False)  # Completion notices also need the final fence.
    if change == "body":
        r.s.execute("UPDATE outbox SET body='tampered' WHERE id=?", (out["id"],))
    elif change == "expires":
        r.s.execute("UPDATE outbox SET expires=expires+60 WHERE id=?", (out["id"],))
    elif change == "marker":
        r.s.execute("DELETE FROM am_document_source_outputs WHERE outbox_id=?", (out["id"],))
    elif change in ("view_deleted", "both_deleted"):
        r.s.execute("DELETE FROM am_document_view_outputs WHERE outbox_id=?", (out["id"],))
        if change == "both_deleted":
            r.s.execute("DELETE FROM am_document_source_outputs WHERE outbox_id=?", (out["id"],))
    else:
        r.s.execute("UPDATE am_document_view_outputs SET binding='{}' WHERE outbox_id=?", (out["id"],))
    assert r.g.deliver_one()
    assert r.s.rows("SELECT state FROM outbox WHERE id=?", (out["id"],))[0]["state"] == "rejected"
    assert r.api.sent == []


def test_scoped_marker_cannot_be_transplanted_onto_an_ordinary_query(scoped_doc):
    r = scoped_doc
    document = enqueue(r)
    marker = r.s.rows("SELECT source_fence FROM am_document_source_outputs WHERE outbox_id=?",
                     (document["id"],))[0]["source_fence"]
    row = dict(r.row, _query_read=True, _query_grant=r.am.query_grant(dict(r.row)))
    ident = r.am.notify(row, text="ORDINARY_QUERY")
    r.s.execute("INSERT INTO am_document_source_outputs VALUES(?,?)", (ident, marker))
    forged = r.s.rows("SELECT * FROM outbox WHERE id=?", (ident,))[0]
    assert r.am.query_delivery_authorized(forged) is False
    # Copying the view record too still cannot reuse a different outbox's marker.
    r.s.execute("INSERT INTO am_document_view_outputs SELECT ?,binding,expires FROM am_document_view_outputs WHERE outbox_id=?",
                (ident, document["id"]))
    assert r.am.query_delivery_authorized(forged) is False


def test_legacy_document_keeps_global_fence_and_is_never_upgraded(scoped_doc):
    r = scoped_doc
    set_binding(r, "am-document-evidence-binding/1")
    out = enqueue(r)
    marker = r.s.rows("SELECT source_access_version FROM am_source_deliveries WHERE outbox_id=?",
                     (out["id"],))[0]["source_access_version"]
    assert not marker.startswith(SCOPED_SOURCE_FENCE)
    assert not r.s.rows('SELECT 1 FROM am_document_source_outputs WHERE outbox_id=?', (out['id'],))
    change_other(r)
    assert r.g.deliver_one()
    assert r.api.sent == []
    assert r.s.rows("SELECT state FROM outbox WHERE id=?", (out["id"],))[0]["state"] == "rejected"


def test_ordinary_query_keeps_global_fence(scoped_doc):
    r = scoped_doc
    row = dict(r.row, _query_read=True, _query_grant=r.am.query_grant(dict(r.row)))
    ident = r.am.notify(row, text="ORDINARY_QUERY")
    out = r.s.rows("SELECT * FROM outbox WHERE id=?", (ident,))[0]
    change_other(r)
    assert r.am.query_delivery_authorized(out) is False


def test_new_document_capture_does_not_reuse_an_old_query_epoch(scoped_doc):
    r = scoped_doc
    row = dict(r.row, _source_access_version=r.info.access_version())
    change_other(r)
    _, bundle = r.info_host.evidence_bundle(row, "IRAD-2099-001")
    assert bundle.data["document_binding"]["schema"] == "am-document-evidence-binding/2"
    assert r.info_host.document_evidence_current(row, bundle.data["document_binding"]) is True


def test_scoped_binding_covers_actual_pagination(scoped_doc):
    r = scoped_doc
    open_view(r)
    drain(r.g)
    change_other(r)
    click(r.ux, "long_content")
    assert len(r.api.sent) == 2
    assert "第 2/" in r.api.sent[-1]["body"]
    r.info.record(Observation("source-a", "unanalysed", "v1", r.info.clock(), text="新增未解析依据"))
    before = len(r.api.sent)
    failed = click(r.ux, "long_content")
    assert failed["state"] == "failed"
    assert all("SYNTHETIC_PRIVATE" not in row["body"] for row in r.api.sent[before:])


def test_plain_completion_fails_when_information_host_is_unavailable(scoped_doc):
    r = scoped_doc
    out = enqueue(r, query=False)
    r.am.information = None
    assert r.g.deliver_one()
    assert r.api.sent == []
    assert r.s.rows('SELECT state FROM outbox WHERE id=?', (out['id'],))[0]['state'] == 'rejected'


def test_orphan_result_without_standard_context_cannot_acquire_a_scoped_marker(scoped_doc):
    r = scoped_doc
    r.s.execute("UPDATE logic_drafts SET rules='{}' WHERE id=?", (r.ident,))
    r.s.execute('DELETE FROM amdoc_context WHERE draft_id=?', (r.ident,))
    with pytest.raises(BoundaryError, match='EVIDENCE_UNVERIFIED'):
        enqueue(r, query=False)
    assert not r.s.rows('SELECT 1 FROM outbox')
    assert not r.s.rows('SELECT 1 FROM am_document_source_outputs')


@pytest.mark.parametrize('replacement', ['legacy', 'neutral'])
def test_persisted_scoped_output_cannot_downgrade_to_an_unscoped_view(scoped_doc, replacement):
    r = scoped_doc
    out = enqueue(r, query=False)
    if replacement == 'legacy':
        set_binding(r, 'am-document-evidence-binding/1')
    else:
        r.s.execute("UPDATE logic_drafts SET state='collecting',content=NULL,analysis=NULL,review=NULL WHERE id=?", (r.ident,))
    draft = r.s.rows('SELECT * FROM logic_drafts WHERE id=?', (r.ident,))[0]
    replacement_binding = capture(r.g.logic, r.row, draft)
    r.s.execute('UPDATE am_document_view_outputs SET binding=? WHERE outbox_id=?',
                (json.dumps(replacement_binding), out['id']))
    assert r.g.deliver_one()
    assert r.api.sent == []
    assert r.s.rows('SELECT state FROM outbox WHERE id=?', (out['id'],))[0]['state'] == 'rejected'


@pytest.mark.parametrize('corruption', ['missing_component','extra_component','invalid_component','inconsistent_state'])
def test_local_and_host_validation_share_the_v2_component_contract(scoped_doc, corruption):
    from fs_agent.document_evidence import validate_binding as local_validate
    from am_info_sync.document_snapshot import validate_binding as host_validate, DocumentSnapshotError
    r = scoped_doc
    binding = set_binding(r)
    local_validate(r.row,binding,now=r.clock())
    host_validate(binding,r.row,r.info.clock())
    bad = deepcopy(binding)
    if corruption == 'missing_component':
        bad['component_hashes'].pop('objects')
    elif corruption == 'extra_component':
        bad['component_hashes']['unexpected']='a'*64
    elif corruption == 'invalid_component':
        bad['component_hashes']['objects']='not-a-hash'
    else:
        bad['state_hash']='a'*64
    with pytest.raises(BoundaryError, match='BINDING_INVALID'):
        local_validate(r.row,bad,now=r.clock())
    with pytest.raises(DocumentSnapshotError, match='BINDING_INVALID'):
        host_validate(bad,r.row,r.info.clock())
