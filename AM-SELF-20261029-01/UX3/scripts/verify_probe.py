import json,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'))
from fs_agent.config import Config
from fs_agent.feishu import Feishu
p=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((p/'config.json').read_text());cfg=Config.load(Path(settings['poc_config']))
db=sqlite3.connect('file:'+str(cfg.db)+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
r=db.execute('SELECT * FROM am_query_probes ORDER BY rowid DESC LIMIT 1').fetchone()
result={'layer':'real_original_owner_content_free_callback','sdk':'lark-oapi 1.7.5','returned':bool(r and r['response']),'platform_applied_verified':False,'no_business_action':True,'production_query_direct_return_enabled':False,'limitation':'Protocol probe contains no project facts. Production project queries retain fresh remote authorization and asynchronous publication.'}
if r and r['response']:
 response=json.loads(r['response']);row={'body':json.dumps(response['card']['data']), 'app':cfg.app_id,'tenant':cfg.tenant_key,'user':r['actor'],'chat':r['chat'],'chat_type':'p2p','kind':'interactive','expires':r['expires']}
 result['platform_applied_verified']=Feishu(cfg).verify_card(r['message_id'],row);result['response_returned_at']=r['returned'];result['platform_application_observed_at']=time.time();result['extra_patch_outbox_count']=db.execute('SELECT count(*) FROM outbox WHERE created>? AND body LIKE ?', (r['returned'],'%回调直接更新完成%')).fetchone()[0]
(Path(__file__).resolve().parents[1]/'evidence/callback-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result))
