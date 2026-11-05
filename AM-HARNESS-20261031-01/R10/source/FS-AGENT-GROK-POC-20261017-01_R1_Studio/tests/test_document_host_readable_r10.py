"""Native information-host wiring, using real stores and the existing gateway."""
from copy import deepcopy
from dataclasses import replace
import json
import sqlite3
import pytest

from am_info_sync.models import Observation
from fs_agent.config import BoundaryError
from test_document_source_delivery_r9_fix2 import (
    scoped_doc, set_binding, doc, harness, convo, ux, service, am_rig, base_rig)


def binding(r):
    row=r.s.rows('SELECT rules FROM logic_drafts WHERE id=?',(r.ident,))[0]
    return json.loads(row['rules'])['document_binding']


def test_native_host_readable_hook_retains_frozen_revision_after_quality_change(scoped_doc):
    r=scoped_doc;b=binding(r)
    before=deepcopy(b)
    assert r.info_host.document_evidence_readable(r.row,b)['basis_current'] is True
    r.info.open_gap('source-a','message','extraction','synthetic_pending_analysis')
    with pytest.raises(BoundaryError,match='DOCUMENT_EVIDENCE_CHANGED'):
        r.info_host.document_evidence_current(r.row,b)
    result=r.info_host.document_evidence_readable(r.row,b)
    assert result['readable'] is True and result['basis_current'] is False
    assert set(result['changed_components']).intersection({'quality','gaps'})
    assert b==before


def test_native_readable_keeps_old_object_but_publication_guard_rejects_new_revision(scoped_doc):
    r=scoped_doc;b=binding(r)
    r.info.record(Observation('source-a','message','v2',r.info.clock()+1,
        text='合成更新，仍未形成实际完成证据。'),authoritative=True)
    result=r.info_host.document_evidence_readable(r.row,b)
    assert result['readable'] is True and result['basis_current'] is False
    assert 'objects' in result['changed_components']
    with pytest.raises(BoundaryError,match='DOCUMENT_EVIDENCE_CHANGED'):
        r.info_host.document_evidence_current(r.row,b)


def test_revocation_then_restoration_cannot_revive_old_read_proof(scoped_doc):
    r=scoped_doc;b=binding(r)
    r.info.register_source(replace(r.source,enabled=False))
    r.info.register_source(r.source)
    with pytest.raises(BoundaryError,match='SOURCE_ACCESS_CHANGED'):
        r.info_host.document_evidence_readable(r.row,b)


def test_host_checks_current_project_identity_lease_before_frozen_read(scoped_doc):
    r=scoped_doc;b=binding(r)
    r.info_host.am.query_grant=lambda row: []
    with pytest.raises(BoundaryError,match='DOCUMENT_PROJECT_AMBIGUOUS'):
        r.info_host.document_evidence_readable(r.row,b)


def test_historical_v2_without_read_proof_retains_strict_invalidation(scoped_doc):
    r=scoped_doc;b=binding(r);b.pop('read_snapshot')
    assert r.info_host.document_evidence_readable(r.row,b)['basis_current'] is True
    r.info.open_gap('source-a','message','extraction','synthetic_pending_analysis')
    with pytest.raises(BoundaryError,match='DOCUMENT_EVIDENCE_CHANGED'):
        r.info_host.document_evidence_readable(r.row,b)


def test_native_read_guard_never_retrieves_or_reauthenticates_remotely(scoped_doc):
    r=scoped_doc;b=binding(r);observed=[]
    def grant(row):
        observed.append(row.get('_direct_return'))
        return ['*']
    r.info_host.am.query_grant=grant
    r.info_host.am.query_projects=lambda row: pytest.fail('no remote retrieval in a local read guard')
    result=r.info_host.document_evidence_readable(r.row,b)
    assert result['readable'] is True and observed==[True]


def test_frozen_read_does_not_reconstruct_purged_original(scoped_doc):
    r=scoped_doc;b=binding(r)
    with r.info.transaction() as db:
        db.execute("UPDATE observations SET purged=1 WHERE source_id='source-a' AND object_id='message' AND version='v1'")
    with pytest.raises(BoundaryError):
        r.info_host.document_evidence_readable(r.row,b)


@pytest.mark.parametrize('failure',['after_capture','current_unavailable'])
def test_ttl_crossing_during_current_sampling_never_becomes_readable(scoped_doc,monkeypatch,failure):
    import am_info_sync.document_snapshot as snapshots
    r=scoped_doc;b=binding(r);original=snapshots.capture_document_snapshot
    def delayed(*args,**kwargs):
        result=original(*args,**kwargs)
        monkeypatch.setattr(r.info,'clock',lambda:int(b['expires']*1000)+1)
        if failure=='current_unavailable':
            raise snapshots.DocumentSnapshotError('DOCUMENT_LOCAL_SNAPSHOT_UNAVAILABLE')
        return result
    monkeypatch.setattr(snapshots,'capture_document_snapshot',delayed)
    with pytest.raises(BoundaryError,match='DOCUMENT_EVIDENCE_EXPIRED'):
        r.info_host.document_evidence_readable(r.row,b)


def test_one_sqlite_snapshot_fences_other_connection_authorization_writes(scoped_doc,monkeypatch,tmp_path):
    import am_info_sync.document_snapshot as snapshots
    from am_info_sync.store import Store
    from am_info_sync.runtime import InformationService
    r=scoped_doc;b=binding(r)
    path=tmp_path/'shared-information.sqlite'
    local=Store(str(path),clock=r.info.clock)
    r.info.conn.backup(local.conn)
    original_store,original_service=r.info_host.store,r.info_host.service
    r.info_host.store=local;r.info_host.service=InformationService(local)
    other=sqlite3.connect(path,timeout=0)
    original=snapshots.capture_document_snapshot;blocked=[]
    def probe(*args,**kwargs):
        assert kwargs['connection'] is local.conn and local.conn.in_transaction
        with pytest.raises(sqlite3.OperationalError,match='locked'):
            other.execute("UPDATE sources SET availability='denied' WHERE source_id='source-a'")
        other.rollback();blocked.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(snapshots,'capture_document_snapshot',probe)
    try:
        assert r.info_host.document_evidence_readable(r.row,b)['readable'] is True
        assert blocked==[True]
        other.execute("UPDATE sources SET availability='denied' WHERE source_id='source-a'");other.commit()
        with pytest.raises(BoundaryError,match='SOURCE_ACCESS_CHANGED'):
            r.info_host.document_evidence_readable(r.row,b)
    finally:
        other.close();local.close()
        r.info_host.store,r.info_host.service=original_store,original_service
