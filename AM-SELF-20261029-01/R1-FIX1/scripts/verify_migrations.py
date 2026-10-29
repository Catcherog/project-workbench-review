"""Verify migrations on private copies; never connect or execute business actions."""
import hashlib,json,os,sqlite3,sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from fs_agent.config import Config
from fs_agent.store import Store
from fs_agent.logic_service import LogicService,MissingBusiness
from group_ledger import GroupLedger
from am_service import AmSelfService

private=Path.home()/'.local/share/local-qwen-feishu'
cfg=json.loads((private/'config.json').read_text());config=Config.load(Path(cfg['poc_config']))
folder=private/'validation/am-self-20261029-r1-fix1/migration-copy'
folder.mkdir(parents=True,exist_ok=True,mode=0o700)
path=folder/'gateway.sqlite3'
original=sqlite3.connect('file:'+str(config.db)+'?mode=ro',uri=True)
backup=sqlite3.connect(path);original.backup(backup);original.close();backup.close();path.chmod(0o600)
original=sqlite3.connect('file:'+str(private/'state/group-ledger.sqlite3')+'?mode=ro',uri=True)
backup=sqlite3.connect(folder/'group-ledger.sqlite3');original.backup(backup);original.close();backup.close();(folder/'group-ledger.sqlite3').chmod(0o600)
s=Store(path)
protected=('action_items','item_feedback','item_operations','reminder_plans','action_approvals','reminder_occurrences','am_subscriptions','logic_writes','ledger_write_attempts')
columns={t:[r[1] for r in s.conn.execute('PRAGMA table_info('+t+')')] for t in protected}
def fingerprint():
    return {t:hashlib.sha256(json.dumps([tuple(r) for r in s.conn.execute('SELECT '+','.join(columns[t])+' FROM '+t+' ORDER BY rowid')],sort_keys=True).encode()).hexdigest() for t in protected}
before=fingerprint()
gateway=SimpleNamespace(config=config,store=s,authorized=lambda row:False,reminders=SimpleNamespace(port=SimpleNamespace()))
ledger=GroupLedger(folder,SimpleNamespace(app_id=config.app_id,tenant_key=config.tenant_key,bot_open_id=config.bot_open_id),lambda *a:(_ for _ in ()).throw(AssertionError('NO_SEND')))
for _ in range(2):
    gateway.logic=LogicService(gateway,business=MissingBusiness())
    service=AmSelfService(gateway,ledger)
    assert not service.flags['ledger_write']
assert fingerprint()==before
assert s.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert ledger.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
result={'kind':'original_runtime_private_copy','repeated_migration_idempotent':True,'existing_business_rows_preserved':True,'checked_tables':list(protected),'sqlite_integrity':'ok','production_databases_changed':False,'consumers_started':0,'model_calls':0,'external_mutations':0,'legacy_bad_hash_and_pending_cases':'separately covered by synthetic migration tests'}
(ROOT/'AM-SELF-20261029-01/R1-FIX1/evidence/migration-copy.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False));ledger.close();s.close()
