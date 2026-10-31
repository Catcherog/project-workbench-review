import json,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from _bootstrap import bootstrap
root=bootstrap()
studio=root/'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
from fs_agent.store import Store,scope_of
from fs_agent.logic_service import LogicService
from am_conversation.documents import DocumentTools

with tempfile.TemporaryDirectory() as td:
    s=Store(Path(td)/'test.sqlite3')
    g=SimpleNamespace(store=s,config=SimpleNamespace(root=Path(td),owner='owner'),authorized=lambda row:True)
    logic=LogicService(g,business=SimpleNamespace())
    row={'app':'app','tenant':'tenant','user':'owner','chat':'dm','chat_type':'p2p','message_id':'event','expires':time.time()+120}
    for name in ('A','B'):
        s.execute("INSERT INTO logic_drafts(id,scope,revision,state,document_type,sources,answers,expires,mode,target) VALUES(?,?,1,'collecting','test','[]','{}',?,'precheck',?)",(name,scope_of(row),row['expires'],json.dumps({'id':'target-'+name})))
    tools=DocumentTools.__new__(DocumentTools)
    tools.logic=logic;tools.s=s
    tools.principal=lambda ctx:row
    tools.get=lambda ctx,ident:(row,logic.get(row,ident))
    reply=tools.edit(None,{'operation':'requirements','draft_id':'A','version':1,'requirements':'型号=A型号'},'event')
    result=s.rows('SELECT id,revision,target_requirements FROM logic_drafts ORDER BY rowid')
    assert result[0]['target_requirements'] is None
    assert 'A型号' in result[1]['target_requirements']
    assert reply['draft_id']=='A' and reply['version']==1
    print(json.dumps({'requested_draft':'A','reported_result':reply,'actual_drafts':result},ensure_ascii=False,indent=2))
    s.close()
