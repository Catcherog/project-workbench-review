import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-qwen3.8/feishu-bridge'))
from fs_agent.project_catalog import ProjectCatalog
from group_ledger import parse_rows,GroupLedger
from test_group_ledger import VALUES,Port
from test_reminder import rig,base_rig
from test_gateway import event,drain
from am_service import AmSelfService

@pytest.fixture
def catalog(tmp_path):
 db=sqlite3.connect(tmp_path/'catalog.db');db.row_factory=sqlite3.Row
 c=ProjectCatalog(db,'synthetic/namespace',lambda:2000000000)
 yield c
 db.close()


def test_B02_stable_id_rename_sort_and_ambiguous_numbers(catalog):
 projects=catalog.sync(parse_rows(VALUES));original=projects[0]['key']
 values=[r[:] for r in VALUES];values[1][0]='需求75:新标题';values[1:]=list(reversed(values[1:]))
 result=catalog.sync(parse_rows(values))
 assert next(p for p in result if p['business_id']=='需求75')['key']==original
 values.append(['需求75:另一个名称','','','','待核','',''])
 result=catalog.sync(parse_rows(values))
 assert all(p['identity_status']=='conflict' for p in result if p['business_id']=='需求75')
 values[-1][0]='没有业务编号'
 assert catalog.sync(parse_rows(values))[-1]['identity_status']=='needs_mapping'


def test_B03_first_same_revision_only_and_order_do_not_make_changes(catalog):
 p=catalog.sync(parse_rows(VALUES),revision=1);assert catalog.changes()==[]
 catalog.sync(parse_rows(VALUES),revision=2);assert catalog.changes()==[]
 values=[VALUES[0]]+list(reversed(VALUES[1:]));catalog.sync(parse_rows(values),revision=3)
 assert catalog.changes()==[]
 values=[r[:] for r in VALUES];values[1][4]='2026.10.29\n样机自报到货，实际收货尚未核实。'
 catalog.sync(parse_rows(values),revision=4)
 changes=catalog.changes();assert len(changes)==1 and changes[0]['kind']=='record_text_changed'
 catalog.sync(parse_rows(values),revision=5);assert catalog.changes()==changes


def test_B04_partial_failed_read_does_not_advance_baseline(catalog):
 catalog.sync(parse_rows(VALUES),revision=1)
 before=tuple(catalog.db.execute('SELECT * FROM source_baselines').fetchone())
 with pytest.raises(ValueError,match='SOURCE_PARTIAL'):catalog.sync([],complete=False,revision=2)
 assert tuple(catalog.db.execute('SELECT * FROM source_baselines').fetchone())==before


def test_B06_changes_query_is_non_consuming(catalog):
 catalog.sync(parse_rows(VALUES));values=[r[:] for r in VALUES];values[1][2]='预计2026.11.2'
 catalog.sync(parse_rows(values));a=catalog.changes();b=catalog.changes()
 assert a==b and len(a)==1
 assert catalog.db.execute('SELECT count(*) FROM briefing_deliveries').fetchone()[0]==0


def test_B07_owner_private_query_does_not_fake_a_group(rig,tmp_path):
 g,s,api,p,clock,e=rig;port=Port();auth=[];port.authorize_user=lambda u:auth.append(u)
 port.guard=lambda *a:pytest.fail('private query must not call group guard')
 ledger=GroupLedger(tmp_path,port,lambda *a:pytest.fail('no group sends'),clock=clock)
 service=AmSelfService(g,ledger,flags={'query':True,'snapshots':True})
 payload=event('/project 需求75',number=1)
 assert service.ingest(payload)==(True,True);assert service.step();drain(g)
 assert any('实际收货尚未核实' in x.get('body','') for x in api.sent)
 assert auth and all(x=='ou_a' for x in auth)
 assert not s.rows('SELECT * FROM tasks') and not p.prompts
 assert service.ingest(event('/progress sample',number=2))==(False,False)
 assert service.ingest(event('/project 需求75',number=3,user='ou_b'))==(True,False)
 ledger.close()


def test_B02_changed_number_stays_pending_until_explicit_mapping(catalog):
 original=catalog.sync(parse_rows(VALUES))[0]
 values=[r[:] for r in VALUES];values[1][0]='需求76:柔轮试验'
 changed=catalog.sync(parse_rows(values))[0]
 assert changed['identity_status']=='needs_mapping'
 assert catalog.sync(parse_rows(values))[0]['identity_status']=='needs_mapping'
 catalog.confirm_mapping(changed['key'],original['key'],changed['content_fingerprint'],'ou_owner')
 mapped=catalog.sync(parse_rows(values))[0]
 assert mapped['key']==original['key'] and mapped['identity_status']=='verified'
