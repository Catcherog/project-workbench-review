"""Frozen-reading proof tests over real SQLite source histories and deadlines."""
from copy import deepcopy
from dataclasses import replace
import pytest

from am_info_sync.document_snapshot import (DocumentSnapshotError,
    verify_document_snapshot_readable,capture_document_snapshot,request_scope)
from am_info_sync.models import Principal
from test_document_snapshot_r9 import Rig


@pytest.fixture
def frozen():
    rig=Rig();rig.add()
    _,binding=rig.capture()
    try:yield rig,binding
    finally:rig.close()


def verify(rig,binding,row=None):
    return verify_document_snapshot_readable(rig.store,
        principal=Principal('owner','tenant',('th2-query',)),row=row or rig.row,binding=binding)


@pytest.mark.parametrize('change',['new_fact','new_version','quality','new_unknown'])
def test_content_and_quality_changes_keep_immutable_original_readable(frozen,change):
    rig,binding=frozen;original=deepcopy(binding)
    if change=='new_fact':rig.add('新的事实，仍待业务核验',oid='new-message')
    elif change=='new_version':rig.add('原记录已有新版本',version='v2')
    elif change=='quality':rig.store.open_gap('source-a','message','extraction','pending_review')
    else:
        from am_info_sync.models import Observation
        rig.store.record(Observation('source-a','unmapped','v1',rig.time[0],text='归属未解析的新原文'))
    assert verify(rig,binding) is True
    _,current=rig.capture()
    assert current['state_hash']!=binding['state_hash']
    assert binding==original


@pytest.mark.parametrize('change',['revoke','revoke_restore','delete','purge','drop_original','shorten_raw','row_expiry','binding_expiry','scope','proof_objects','proof_sources'])
def test_frozen_read_keeps_revocation_scope_and_original_retention_fences(frozen,change):
    rig,binding=frozen;row=dict(rig.row)
    if change in ('revoke','revoke_restore'):
        rig.store.register_source(replace(rig.source,enabled=False))
        if change=='revoke_restore':rig.store.register_source(rig.source)
    elif change=='delete':rig.store.conn.execute("UPDATE observations SET deleted=1 WHERE source_id='source-a'")
    elif change=='purge':rig.store.conn.execute("UPDATE observations SET purged=1 WHERE source_id='source-a'")
    elif change=='drop_original':rig.store.conn.execute("DELETE FROM observations WHERE source_id='source-a'")
    elif change=='shorten_raw':rig.store.conn.execute("UPDATE observations SET raw_expires_at_ms=? WHERE source_id='source-a'",(rig.time[0],))
    elif change=='row_expiry':row['expires']=rig.time[0]/1000
    elif change=='binding_expiry':rig.time[0]=int(binding['expires']*1000)
    elif change=='scope':row['chat']='different-chat'
    elif change=='proof_objects':binding['read_snapshot']['objects']=[]
    else:binding['read_snapshot']['source_ids']=['th2-ledger']
    with pytest.raises(DocumentSnapshotError):verify(rig,binding,row)


def test_original_retention_cannot_be_renewed_by_newer_raw_deadline(frozen):
    rig,binding=frozen;original=deepcopy(binding)
    rig.store.conn.execute('UPDATE observations SET raw_expires_at_ms=raw_expires_at_ms+999999999')
    assert verify(rig,binding) is True
    assert binding==original
    rig.time[0]=int(original['expires']*1000)
    with pytest.raises(DocumentSnapshotError,match='EXPIRED'):verify(rig,binding)


def test_read_guard_is_local_read_only_and_missing_proof_is_not_upgraded(frozen):
    rig,binding=frozen;before=rig.store.conn.total_changes
    assert verify(rig,binding) is True
    assert rig.store.conn.total_changes==before
    binding.pop('read_snapshot')
    with pytest.raises(DocumentSnapshotError,match='DOCUMENT_READ_SNAPSHOT_REQUIRED'):verify(rig,binding)


def test_read_and_current_snapshot_share_one_caller_transaction_without_writes(frozen):
    rig,binding=frozen;traced=[];before=rig.store.conn.total_changes
    rig.store.conn.set_trace_callback(traced.append)
    with rig.store.transaction() as db:
        assert verify_document_snapshot_readable(rig.store,principal=Principal('owner','tenant',('th2-query',)),
            row=rig.row,binding=binding,connection=db)
        _,current=capture_document_snapshot(rig.store,rig.service,rig.project,
            principal=Principal('owner','tenant',('th2-query',)),scope=request_scope(rig.row),
            project_code=binding['project_code'],expires=binding['expires'],connection=db)
        assert db.in_transaction and current['state_hash']==binding['state_hash']
    assert rig.store.conn.total_changes==before
    assert sum(sql.startswith('BEGIN') for sql in traced)==1
    assert sum(sql=='COMMIT' for sql in traced)==1
    with pytest.raises(RuntimeError,match='active transaction'):
        verify_document_snapshot_readable(rig.store,principal=Principal('owner','tenant',('th2-query',)),
            row=rig.row,binding=binding,connection=db)
