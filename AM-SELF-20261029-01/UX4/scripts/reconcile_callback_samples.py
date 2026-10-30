"""Reconcile only actual owner callback samples using original readback logic.

No consumer, service constructor, inference, message send or business write.
"""
import json,sys,time
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-SELF-20261029-01/UX4'
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from fs_agent.config import Config
from fs_agent.store import Store
from fs_agent.feishu import Feishu
from fs_agent import request_timing as timing
from group_ledger import FeishuLedgerPort
from am_service import AmSelfService
from am_query import QueryIdentityCache
private=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((private/'config.json').read_text());cfg=Config.load(Path(settings['poc_config']));api=Feishu(cfg)
assert settings['am_self']['ledger_write'] is False
port=FeishuLedgerPort(api.client,app_id=cfg.app_id,tenant_key=cfg.tenant_key,bot_open_id=cfg.bot_open_id,department_root_id=settings['group_ledger']['department_root_id'],disclosure=settings['group_ledger']['disclosure'])
am=object.__new__(AmSelfService);am.s=Store(cfg.db);am.g=SimpleNamespace(config=cfg,api=api);am.owner=cfg.owner
am.ledger=SimpleNamespace(port=port);am.query_settings=settings['am_query'];am.query_scope=am.query_settings['private_scope'];am.query_identity=QueryIdentityCache(port.authorize_private_user,600)
records=am.s.rows("SELECT v.id,v.pending_outbox FROM am_interactions v JOIN outbox o ON o.id=v.pending_outbox WHERE o.user=? AND o.state='unknown' AND o.error='CALLBACK_APPLICATION_UNKNOWN'",(cfg.owner,))
results=[]
for r in records:
 ok=am.reconcile_view(r['id']);event=timing.origin(am.s,r['pending_outbox'])
 if ok:
  am.s.execute('UPDATE am_request_timings SET readback_verified=1,finished=? WHERE event_id=?',(am.s.clock(),event))
  timing.anchor(am.s,event,'verify',state='verified_exact_card')
 results.append({'verified_and_reconciled':ok,'observed_at':time.time()})
out={'source_commit':json.loads((TASK/'evidence/installation.json').read_text())['source_commit'],'owner_only':True,'samples':results,'reused_original_reconciliation':True,'new_messages':0,'business_writes':0}
(TASK/'evidence/callback-sample-reconciliation.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
am.query_identity.close();port.identity_pool.shutdown(wait=True);am.s.close()
