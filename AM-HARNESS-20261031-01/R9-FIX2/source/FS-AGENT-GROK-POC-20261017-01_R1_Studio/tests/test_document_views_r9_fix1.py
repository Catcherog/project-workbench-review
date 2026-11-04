"""Real host, durable dispatch and SQLite; only platform/evidence I/O is synthetic."""
import json
from types import SimpleNamespace
import pytest
from fs_agent.config import BoundaryError
from fs_agent.doc_logic import digest
from fs_agent.document_standards import DocumentStandards
from test_harness_host import harness, convo, ux, service, am_rig, base_rig, incoming
from test_am_ux1 import latest, click
from test_gateway import drain


@pytest.fixture
def doc(harness):
    conv, h = harness
    am, g, s, api, clock, port = conv[0]
    row = incoming(harness, '查看合成文稿')
    s.execute("UPDATE am_inbox SET state='done' WHERE id=?",(row['id'],))
    d = g.logic.create(row, 'charter')
    body = 'SYNTHETIC_PRIVATE_BODY\n' * 600
    analysis = {'questions': [{'ask': 'SYNTHETIC_PRIVATE_QUESTION'}]}
    binding = {'schema': 'am-document-evidence-binding/1', 'project_id': 'p',
        'project_code': 'IRAD-2099-001', 'scope': [row['tenant'],row['app'],row['user'],row['chat'],''],
        'expires': clock()+600, 'state_hash': 'source-v1', 'access_version': 1, 'dependencies': []}
    standards = DocumentStandards(g.logic, {})
    g.logic.standards = standards
    state = {'current': True}
    g.logic.shared_evidence = lambda *a: pytest.fail('no retrieval at delivery')
    g.logic.shared_evidence_current = lambda *a: state['current']
    rules = {'engine': 'am-doc-standards-r9', 'project_id': 'p', 'document_binding': binding}
    s.execute("UPDATE logic_drafts SET state='ready',content=?,content_hash=?,analysis=?,rules=?,expires=? WHERE id=?",
        (body,digest(body),json.dumps(analysis),json.dumps(rules),clock()+600,d['id']))
    s.execute('INSERT INTO amdoc_context VALUES(?,?,?)', (d['id'],json.dumps({
        'project_code': 'IRAD-2099-001', 'doc_type': 'charter'}),clock()+600))
    s.execute('INSERT INTO amdoc_results VALUES(?,?,?,?)', (d['id'],1,json.dumps({
        'document_binding': binding, 'request': {'project_id': 'p'}}),clock()+600))
    return SimpleNamespace(am=am,g=g,s=s,api=api,clock=clock,state=state,row=row,
        ident=d['id'],body=body,ux=conv[0],h=h)


def open_view(r, section='content'):
    r.am.ux_documents(dict(r.row), {'draft':r.ident,'section':section})
    return r.s.rows('SELECT * FROM outbox ORDER BY rowid DESC LIMIT 1')[0]


@pytest.mark.parametrize('change', ['source','revision','body','review','binding'])
def test_queued_view_rechecks_document_before_durable_dispatch(doc, change):
    r=doc;out=open_view(r)
    if change=='source':r.state['current']=False
    elif change=='revision':r.s.execute('UPDATE logic_drafts SET revision=revision+1 WHERE id=?',(r.ident,))
    elif change=='body':r.s.execute("UPDATE logic_drafts SET content='tampered' WHERE id=?",(r.ident,))
    elif change=='review':r.s.execute("UPDATE logic_drafts SET review='{}' WHERE id=?",(r.ident,))
    else:r.s.execute("UPDATE amdoc_results SET payload='{}' WHERE draft_id=?",(r.ident,))
    assert r.g.deliver_one()
    assert r.s.rows('SELECT state FROM outbox WHERE id=?',(out['id'],))[0]['state']=='rejected'
    assert r.api.sent==[]


def test_current_view_and_next_page_still_deliver(doc):
    r=doc;open_view(r);drain(r.g)
    click(r.ux,'long_content')
    assert len(r.api.sent)==2
    assert '第 2/' in r.api.sent[-1]['body']


def test_callback_rechecks_source_after_first_page(doc):
    r=doc;open_view(r);drain(r.g);r.state['current']=False
    before=len(r.api.sent);row=click(r.ux,'long_content')
    assert row['state']=='failed'
    assert all('SYNTHETIC_PRIVATE' not in o['body'] for o in r.api.sent[before:])


@pytest.mark.parametrize('section',[None,'actions'])
def test_stale_summary_does_not_emit_old_questions(doc,section):
    r=doc;r.state['current']=False
    with pytest.raises(BoundaryError):open_view(r,section)
    assert r.api.sent==[] and not r.s.rows('SELECT * FROM outbox')


def test_all_page_storage_uses_document_expiry_and_purges_cached_text(doc):
    r=doc;out=open_view(r);card=latest(r.ux)
    view=r.s.rows('SELECT * FROM am_interactions')[0]
    assert out['expires']==card['expires']==view['expires']==r.clock()+600
    r.clock.now+=601
    r.g.logic.cleanup();r.s.cleanup();r.am.step(maintenance=True)
    for table,column in [('outbox','body'),('am_cards','snapshot'),('am_interactions','current_view')]:
        assert all('SYNTHETIC_PRIVATE' not in (row[column] or '') for row in r.s.rows('SELECT '+column+' FROM '+table))


def test_existing_unbound_document_card_cannot_be_replayed_after_upgrade(doc):
    r=doc;open_view(r);drain(r.g)
    c=latest(r.ux);snap=json.loads(c['snapshot']);snap['data'].pop('document_binding',None)
    r.s.execute('UPDATE am_cards SET snapshot=?,hash=? WHERE nonce=?',
        (json.dumps(snap,ensure_ascii=False),__import__('fs_agent.project_catalog',fromlist=['digest']).digest(snap),c['nonce']))
    before=len(r.api.sent);row=click(r.ux,'long_content')
    assert row['state']=='failed'
    assert all('SYNTHETIC_PRIVATE' not in o['body'] for o in r.api.sent[before:])


def test_final_transport_guard_rechecks_after_preflight(doc):
    from fs_agent.feishu import SendRejected
    r=doc;out=open_view(r)
    def send(row,guard):
        r.state['current']=False
        assert guard() is False
        raise SendRejected('DOCUMENT_VIEW_CHANGED')
    r.api.send=send
    assert r.g.deliver_one()
    assert r.s.rows('SELECT state FROM outbox WHERE id=?',(out['id'],))[0]['state']=='rejected'


def test_completion_summary_is_bound_before_notification(doc):
    r=doc
    r.s.execute('INSERT INTO logic_jobs VALUES(?,?,?)',(r.row['id'],r.ident,1))
    with r.s.tx() as c:r.am.document_completion(r.row,None,c)
    r.state['current']=False;drain(r.g)
    assert r.api.sent==[]
    assert r.s.rows('SELECT state FROM outbox')[0]['state']=='rejected'


def test_upgrade_scrubs_unbound_caches_without_rewriting_unknown(doc):
    from fs_agent.document_view_binding import retire_unbound
    r=doc;out=open_view(r);c=latest(r.ux)
    snapshot=json.loads(c['snapshot']);snapshot['data'].pop('document_binding')
    r.s.execute('UPDATE am_cards SET snapshot=? WHERE nonce=?',(json.dumps(snapshot),c['nonce']))
    r.s.execute('UPDATE am_interactions SET current_view=?',(json.dumps(snapshot),))
    r.s.execute('DELETE FROM am_document_view_outputs')
    r.s.execute("DELETE FROM meta WHERE key='document-view-binding-r9-fix1'")
    r.s.execute("UPDATE outbox SET state='unknown' WHERE id=?",(out['id'],))
    retire_unbound(r.g.logic)
    out=r.s.rows('SELECT * FROM outbox')[0]
    assert out['state']=='unknown' and out['body'] is None
    assert r.s.rows('SELECT snapshot FROM am_cards')[0]['snapshot']=='{}'
    assert r.s.rows('SELECT current_view FROM am_interactions')[0]['current_view']=='{}'


def test_old_document_history_does_not_expire_a_current_ordinary_view(doc):
    from fs_agent.document_view_binding import retire_unbound
    r=doc;open_view(r);c=latest(r.ux)
    snapshot=json.loads(c['snapshot']);snapshot['data'].pop('document_binding')
    r.s.execute('UPDATE am_cards SET snapshot=? WHERE nonce=?',(json.dumps(snapshot),c['nonce']))
    r.s.execute("UPDATE am_interactions SET current_view=?,expires=?",(json.dumps({'data':{},'actions':{'0':{'page':'projects'}}}),r.clock()+3600))
    r.s.execute('DELETE FROM am_document_view_outputs')
    r.s.execute("DELETE FROM meta WHERE key='document-view-binding-r9-fix1'")
    retire_unbound(r.g.logic)
    view=r.s.rows('SELECT current_view,expires FROM am_interactions')[0]
    assert view['expires']==r.clock()+3600 and 'projects' in view['current_view']
