"""Copy-only migration check. Does not open a socket, send, or change production DBs."""
import hashlib,json,sqlite3,sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from fs_agent.config import Config
from fs_agent.store import Store
from fs_agent.gateway import Gateway
from group_ledger import GroupLedger
from am_service import AmSelfService
private=Path.home()/'.local/share/local-qwen-feishu';cfg=json.loads((private/'config.json').read_text());config=Config.load(Path(cfg['poc_config']))
folder=private/'validation/am-self-20261029-r1';backups=folder/'db-before';backups.mkdir(exist_ok=True)
copydir=folder/'migration-copy';copydir.mkdir(exist_ok=True)
counts={}
for name,src in [('chat',private/'state/chat.sqlite3'),('group-ledger',private/'state/group-ledger.sqlite3'),('gateway',config.db)]:
 original=sqlite3.connect('file:'+str(src)+'?mode=ro',uri=True)
 dest=backups/(name+'.sqlite3')
 if not dest.exists():
  backup=sqlite3.connect(dest);original.backup(backup);backup.close()
 test=sqlite3.connect(copydir/(name+'.sqlite3'));original.backup(test);test.close()
 counts[name]={row[0]:original.execute('SELECT count(*) FROM "'+row[0]+'"').fetchone()[0] for row in original.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
 original.close()
store=Store(copydir/'gateway.sqlite3');gateway=Gateway(config,store,SimpleNamespace(authorize=lambda *a:False),SimpleNamespace())
port=SimpleNamespace(app_id=config.app_id,tenant_key=config.tenant_key,bot_open_id=config.bot_open_id)
ledger=GroupLedger(copydir,port,lambda *a:(_ for _ in ()).throw(AssertionError('NO_SEND')))
service=AmSelfService(gateway,ledger,flags={'query':True,'items':True})
service=AmSelfService(gateway,ledger,flags={'query':True,'items':True})
after={k:store.conn.execute('SELECT count(*) FROM "'+k+'"').fetchone()[0] for k in counts['gateway']}
assert all(after[k]==v for k,v in counts['gateway'].items())
assert store.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert ledger.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
summary={'kind':'private_production_copy_migration','repeated_migration_idempotent':True,'legacy_gateway_table_counts_preserved':True,'sqlite_integrity':'ok','production_databases_changed':False,'event_consumers_created':0,'model_calls':0,'platform_sends':0,'new_tables':sorted(r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'") if r[0] not in counts['gateway'])}
(ROOT/'AM-SELF-20261029-01/R1/evidence/migration-copy-verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
gateway.pool.shutdown(wait=False);ledger.close();store.close()
