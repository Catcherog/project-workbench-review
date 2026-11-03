"""Pure assembly stays cheap; full source checks fence model calls and commits."""
import json,time
from dataclasses import replace
import pytest
from fs_agent.config import BoundaryError
from am_doc_engine.host_bridge import prepare_am_document
from test_document_shared_evidence_r9 import prepare_fixture,profile,ROW


def many_fields(tmp_path,monkeypatch,*,invalidate=False):
    standards,store,draft=prepare_fixture(tmp_path,monkeypatch)
    p=profile();p=replace(p,fields=tuple(replace(p.fields[0],field_id='field-'+str(i)) for i in range(60)))
    monkeypatch.setattr('fs_agent.document_standards.blueprint',lambda *a,**k:(p,[]))
    monkeypatch.setattr('fs_agent.document_standards.prepare_am_document',prepare_am_document)
    counts={'local':0,'full':0};current={'value':True}
    original=standards.guard
    def local(*args,**kwargs):
        counts['local']+=1
        if invalidate and counts['local']>=30:current['value']=False
        return original(*args,**kwargs)
    def full(*a):
        counts['full']+=1
        return current['value']
    standards.guard=local;standards.logic.shared_evidence_current=full
    return standards,store,draft,counts


def test_sixty_fields_do_not_rebuild_full_source_snapshot_sixty_times(tmp_path,monkeypatch):
    standards,store,draft,counts=many_fields(tmp_path,monkeypatch)
    try:
        content,_,_=standards.prepare(ROW,draft,{'revision':1},time.monotonic()+10,None,[])
        assert content and counts['local']>=60 and counts['full']<15
        trace=json.loads(store.rows('SELECT trace FROM amdoc_attempt_traces')[0]['trace'])
        assert trace['guard_counts']['local']>=60 and trace['guard_counts']['full']<15
    finally:store.close()


def test_revocation_during_pure_assembly_cannot_commit_or_publish(tmp_path,monkeypatch):
    standards,store,draft,counts=many_fields(tmp_path,monkeypatch,invalidate=True)
    original_results=store.rows('SELECT * FROM amdoc_results')
    try:
        with pytest.raises(BoundaryError,match='EVIDENCE_CHANGED'):
            standards.prepare(ROW,draft,{'revision':1},time.monotonic()+10,None,[])
        assert store.rows('SELECT * FROM amdoc_results')==original_results
        assert not store.rows("SELECT * FROM amdoc_runs WHERE status='complete'")
        assert store.rows('SELECT content FROM logic_drafts')[0]['content']=='已有草稿'
    finally:store.close()
