"""Explicit owner-only live query/control validation; never starts a consumer.

Receipts and message IDs stay in the private validation directory. The exported
summary contains counts, timings, code identifiers and readback booleans only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'),str(ROOT/'local-qwen3.8/feishu-bridge')]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('mode',choices=('submit','check'))
parser.add_argument('--label',required=True)
parser.add_argument('--prompt')
parser.add_argument('--verify',action='store_true')
args=parser.parse_args()
if not __import__('re').fullmatch('[a-z0-9-]{1,40}',args.label):raise ValueError('INVALID_LABEL')
private=Path.home()/'.local/share/local-qwen-feishu'
settings=json.loads((private/'config.json').read_text())
from fs_agent.config import Config
cfg=Config.load(Path(settings['poc_config']))
folder=private/'validation/am-harness-r1';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
path=folder/(args.label+'.json')
db=sqlite3.connect('file:'+str(cfg.db)+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
if args.mode=='submit':
    if path.exists():raise ValueError('LABEL_ALREADY_SUBMITTED')
    if not args.prompt:raise ValueError('PROMPT_REQUIRED')
    origin=db.execute("SELECT * FROM am_inbox WHERE user=? AND chat_type='p2p' AND chat LIKE 'oc_%' ORDER BY created DESC LIMIT 1",(cfg.owner,)).fetchone()
    if not origin:raise RuntimeError('OWNER_PRIVATE_ORIGIN_REQUIRED')
    # The only destination is the already established original-owner AM DM.
    receipt=subprocess.run([str(Path.home()/'.local/bin/lark-cli'),'im','+messages-send',
        '--as','user','--chat-id',origin['chat'],'--text',args.prompt,
        '--idempotency-key','harness-'+uuid.uuid4().hex],capture_output=True,text=True)
    if receipt.returncode:raise RuntimeError('LIVE_SUBMISSION_FAILED')
    value=json.loads(receipt.stdout);mid=value.get('data',{}).get('message_id')
    if not mid:raise RuntimeError('LIVE_MESSAGE_ID_MISSING')
    saved={'label':args.label,'message_id':mid,'submitted':time.time(),
           'prompt_hash':hashlib.sha256(args.prompt.encode()).hexdigest(),
           'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
           'harness_settings':settings.get('am_harness',{}),'receipt':value}
    path.write_text(json.dumps(saved,ensure_ascii=False,indent=2));path.chmod(0o600)
    print(json.dumps({'label':args.label,'submitted':True,'owner_private_only':True}))
else:
    saved=json.loads(path.read_text());mid=saved['message_id']
    incoming=db.execute('SELECT * FROM am_inbox WHERE id=?',(mid,)).fetchone()
    outputs=db.execute('SELECT o.* FROM outbox o JOIN am_outbox_events a ON a.outbox_id=o.id WHERE a.event_id=?',(mid,)).fetchall()
    timing=db.execute('SELECT * FROM am_request_timings WHERE event_id=?',(mid,)).fetchone()
    replies=db.execute('SELECT reply FROM am_conversation_outputs WHERE event_id=?',(mid,)).fetchall()
    verified=False
    if args.verify and outputs and all(o['state']=='sent' for o in outputs):
        from fs_agent.feishu import Feishu
        from group_ledger import FeishuLedgerPort
        api=Feishu(cfg)
        port=FeishuLedgerPort(api.client,app_id=cfg.app_id,tenant_key=cfg.tenant_key,bot_open_id=cfg.bot_open_id,
            department_root_id=settings['group_ledger']['department_root_id'],disclosure=settings['group_ledger']['disclosure'])
        try:
            def verify(row):
                def guard():
                    port.authorize_private_user(cfg.owner)
                    return row['user']==cfg.owner and row['chat_type']=='p2p' and row['expires']>time.time()
                return api.verify_text(row['message_id'],dict(row,_query_readback_guard=guard))
            verified=all(verify(dict(o)) for o in outputs)
        finally:port.identity_pool.shutdown(wait=True)
    summary={'label':args.label,'source_commit':saved['source_commit'],
        'harness_settings':saved['harness_settings'],'state':incoming['state'] if incoming else 'not_received',
        'error':incoming['error'] if incoming else None,'reply_count':len(outputs),
        'outbox_states':[o['state'] for o in outputs],
        'reply_statuses':[json.loads(r['reply']).get('status') for r in replies],
        'independent_text_readback':verified,
        'publication_seconds':round(timing['actionable']-timing['received'],4) if timing and timing['actionable'] else None,
        'stages':json.loads(timing['stages']) if timing else {},'checked_at':time.time()}
    if verified:
        summary['content_hashes']=[hashlib.sha256(o['body'].encode()).hexdigest() for o in outputs]
        saved['verification']=summary;path.write_text(json.dumps(saved,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False))
