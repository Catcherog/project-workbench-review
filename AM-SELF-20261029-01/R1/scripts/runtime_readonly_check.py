"""Read-only validation through the original app; never sends a message."""
import hashlib
import json
import logging
import sqlite3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
import lark_oapi as lark
from fs_agent.config import Config
from fs_agent.qwen_provider import LocalQwenProvider
from fs_agent.reminder_feishu import ReminderPort
from fs_agent.project_catalog import ProjectCatalog
from group_ledger import FeishuLedgerPort,TOKEN,SHEET
from sheets_write_port import CliProtectedReader
logging.disable(logging.CRITICAL)
private=Path.home()/'.local/share/local-qwen-feishu';directory=private/'validation/am-self-20261029-r1'
cfg=json.loads((private/'config.json').read_text());c=Config.load(Path(cfg['poc_config']))
client=lark.Client.builder().app_id(c.app_id).app_secret(c.app_secret_file.read_text().strip()).timeout(20).log_level(lark.LogLevel.CRITICAL).build()
reminders=ReminderPort(c,client);bot=reminders.bot();policy=reminders.policy()
prior=json.loads((private/'validation/th2-ledger-20261028-live.json').read_text())
assert prior['chat_id'] in policy['outbound_group_ids']
disclosure={prior['chat_id']:['*']}
port=FeishuLedgerPort(client,app_id=c.app_id,tenant_key=c.tenant_key,bot_open_id=c.bot_open_id,department_root_id=cfg['group_ledger']['department_root_id'],disclosure=disclosure)
port.authorize_user(c.owner);port.guard(prior['chat_id'],c.owner)
projects=port.read();db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
catalog=ProjectCatalog(db,c.tenant_key+'/'+c.app_id+'/'+TOKEN+'/'+SHEET);mapped=catalog.sync(projects,revision=projects[0].get('source_revision'))
provider=LocalQwenProvider(c);pin=provider.pin()
identity=json.loads((directory/'cli-identity.json').read_text());assert identity['appId']==c.app_id and identity['onBehalfOf']['openId']==c.owner
binary=Path.home()/'.local/bin/lark-cli';sha=hashlib.sha256(binary.read_bytes()).hexdigest();reader=CliProtectedReader(binary,sha,identity)
selected=[p for p in mapped if p.get('business_id')=='需求75'];assert len(selected)==1
headers,cell=reader.read(selected[0]['row'])
summary={'kind':'real_platform_read_only','original_bot_identity_verified':bot['id']==c.bot_open_id,'original_owner_verified':True,'previously_approved_group_verified':True,'group_scope_count':len(disclosure),'project_count':len(mapped),'verified_project_count':sum(p['identity_status']=='verified' for p in mapped),'protected_cell_read_complete':len(headers)==len(cell)==7,'same_app_owner_metadata_profile':True,'model':pin['model'],'server_version':pin['server_version'],'model_pin_verified':True,'messages_sent':0,'ledger_writes':0}
(directory/'readonly-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
(ROOT/'AM-SELF-20261029-01/R1/evidence/real-platform-readonly.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
identity={k:identity[k] for k in ('profile','appId','identity','onBehalfOf')}
(directory/'proposed-runtime-settings.json').write_text(json.dumps({'disclosure':disclosure,'metadata':{'binary':str(binary),'sha256':sha,'identity':identity}},ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False))
