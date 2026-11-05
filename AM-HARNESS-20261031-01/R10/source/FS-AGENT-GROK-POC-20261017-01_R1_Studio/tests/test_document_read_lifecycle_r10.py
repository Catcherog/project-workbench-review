"""Real gateway/store lifecycle regressions; only external platform I/O is fake."""
from dataclasses import replace
import json
import pytest

from fs_agent.config import BoundaryError
from fs_agent.document_view_binding import capture,require
from test_document_source_delivery_r9_fix2 import (
    scoped_doc,doc,harness,convo,ux,service,am_rig,base_rig,open_view,enqueue)
from test_am_ux1 import click,latest
from test_gateway import drain


@pytest.fixture
def frozen_doc(scoped_doc):
    r=scoped_doc
    r.g.logic.shared_evidence_readable=r.info_host.document_evidence_readable
    return r


def change(r):r.info.open_gap('source-a','message','extraction','synthetic_pending_analysis')


@pytest.mark.parametrize('section',['content','review',None,'actions'])
def test_fixed_revision_pages_display_changes_without_requiring_current_basis(frozen_doc,section):
    r=frozen_doc;change(r)
    out=open_view(r,section);drain(r.g)
    assert r.s.rows('SELECT state FROM outbox WHERE id=?',(out['id'],))[0]['state']=='sent'
    assert '依据已变化' in r.api.sent[-1]['body']
    assert '固定版本' in r.api.sent[-1]['body']


def test_page_two_rechecks_access_and_updates_change_notice(frozen_doc):
    r=frozen_doc;open_view(r);drain(r.g);change(r)
    result=click(r.ux,'long_content')
    assert result['state']=='done'
    assert '第 2/' in r.api.sent[-1]['body']
    assert '依据已变化' in r.api.sent[-1]['body']
    assert 'SYNTHETIC_PRIVATE_BODY' in r.api.sent[-1]['body']


@pytest.mark.parametrize('section',['content','review'])
def test_original_completion_buttons_work_after_changes_with_sixty_seconds_left(frozen_doc,section):
    r=frozen_doc
    r.s.execute('INSERT INTO logic_jobs VALUES(?,?,?)',(r.row['id'],r.ident,1))
    with r.s.tx() as db:r.am.document_completion(r.row,None,db)
    drain(r.g);original=latest(r.ux)
    r.clock.now+=540;change(r)
    result=click(r.ux,'documents',c=original,overrides={'section':section})
    assert result['state']=='done'
    assert '依据已变化' in r.api.sent[-1]['body']
    assert latest(r.ux)['expires']==original['expires']
    assert latest(r.ux)['expires']-r.clock()==60


def test_view_and_final_send_survive_new_quality_but_not_revocation(frozen_doc):
    r=frozen_doc;out=enqueue(r);change(r)
    assert r.g.deliver_one()
    assert r.s.rows('SELECT state FROM outbox WHERE id=?',(out['id'],))[0]['state']=='sent'
    out=enqueue(r);r.info.register_source(replace(r.source,enabled=False))
    assert r.g.deliver_one()
    assert r.s.rows('SELECT state FROM outbox WHERE id=?',(out['id'],))[0]['state']=='rejected'


def test_stale_adoption_and_publication_verifier_remain_strict(frozen_doc):
    r=frozen_doc;change(r)
    d=r.g.logic.get(r.row,r.ident)
    assert capture(r.g.logic,r.row,d)
    with pytest.raises(BoundaryError,match='DOCUMENT_EVIDENCE_CHANGED'):r.g.logic.adopt(r.row,r.ident)
    with pytest.raises(BoundaryError,match='DOCUMENT_EVIDENCE_CHANGED'):r.g.logic.standards.require_current_evidence(r.row,d)
    assert r.g.logic.get(r.row,r.ident)['accepted_hash'] is None


def test_regeneration_is_explicit_separate_and_original_deadlines_do_not_move(frozen_doc):
    r=frozen_doc;d=r.g.logic.get(r.row,r.ident);bound=capture(r.g.logic,r.row,d)
    before=r.s.rows('SELECT * FROM logic_drafts WHERE id=?',(r.ident,))[0]
    change(r);queued=[]
    r.g.logic.queue=lambda row,draft: queued.append((row,draft))
    r.am.ux_documents(dict(r.row),{'draft':r.ident,'section':'regenerate_preview'})
    assert queued==[]
    assert len(r.s.rows('SELECT * FROM logic_drafts'))==1
    r.am.ux_documents(dict(r.row),{'draft':r.ident,'section':'regenerate',
        'revision':d['revision'],'hash':d['content_hash']})
    assert len(queued)==1
    row,fresh=queued[0]
    assert fresh['id']!=r.ident and fresh['revision']==1
    assert fresh['state']=='collecting' and not fresh['accepted_hash'] and not fresh['target']
    assert fresh['expires']==row['expires']==bound['expires']
    assert r.s.rows('SELECT * FROM logic_drafts WHERE id=?',(r.ident,))[0]==before
    assert require(r.g.logic,r.row,bound) is True
    context=json.loads(r.s.rows('SELECT context FROM amdoc_context WHERE draft_id=?',(fresh['id'],))[0]['context'])
    assert context['regenerated_from']=={'draft_id':r.ident,'revision':d['revision'],
        'content_hash':d['content_hash'],'expires':bound['expires']}


def test_regenerate_confirmation_callback_replay_does_not_create_second_candidate(frozen_doc):
    r=frozen_doc;change(r);queued=[]
    r.g.logic.queue=lambda row,draft:queued.append((row,draft))
    r.am.ux_documents(dict(r.row),{'draft':r.ident,'section':'regenerate_preview'})
    drain(r.g);preview=latest(r.ux)
    assert click(r.ux,'documents',c=preview,overrides={'section':'regenerate'})['state']=='done'
    click(r.ux,'documents',c=preview,overrides={'section':'regenerate'})
    assert len(queued)==1 and len(r.s.rows('SELECT * FROM logic_drafts'))==2


@pytest.mark.parametrize('change_kind',['revoked','expired','content_tampered'])
def test_no_regeneration_from_unreadable_or_changed_revision(frozen_doc,change_kind):
    r=frozen_doc;d=r.g.logic.get(r.row,r.ident);queued=[]
    r.g.logic.queue=lambda *args:queued.append(args)
    if change_kind=='revoked':r.info.register_source(replace(r.source,enabled=False))
    elif change_kind=='expired':r.clock.now+=601
    else:r.s.execute("UPDATE logic_drafts SET content_hash='tampered' WHERE id=?",(r.ident,))
    with pytest.raises(BoundaryError):r.am.ux_documents(dict(r.row),{'draft':r.ident,'section':'regenerate',
        'revision':d['revision'],'hash':d['content_hash']})
    assert queued==[] and len(r.s.rows('SELECT * FROM logic_drafts'))==1
