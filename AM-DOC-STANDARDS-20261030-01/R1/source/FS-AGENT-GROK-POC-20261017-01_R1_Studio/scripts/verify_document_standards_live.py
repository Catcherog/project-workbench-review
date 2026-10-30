"""Explicit local operator test. No consumer, message send, adoption or mount is started.

Credentials remain in the original service config. All business content is written only
to --private-output, which must never be included in a public review export.
"""
from __future__ import annotations
import argparse
import json
import time
import types
import uuid
from pathlib import Path
from fs_agent.config import Config
from fs_agent.document_standards import DocumentStandards
from fs_agent.feishu import Feishu
from fs_agent.logic_service import LogicService
from fs_agent.model_coordinator import ModelCoordinator
from fs_agent.qwen_provider import LocalQwenProvider
from fs_agent.store import Store


def main():
    p=argparse.ArgumentParser();p.add_argument('--service-config',type=Path,required=True)
    p.add_argument('--settings',type=Path,required=True);p.add_argument('--private-output',type=Path,required=True)
    p.add_argument('--project-code',required=True);p.add_argument('--kind',choices=['charter','change','closure'],required=True)
    p.add_argument('--project-type',choices=['IPD','IRAD','other'],required=True);p.add_argument('--level',choices=['L1','L2','L3'],required=True)
    p.add_argument('--project-source',type=Path)
    p.add_argument('--save-native',action='store_true');a=p.parse_args()
    out=a.private_output;out.mkdir(mode=0o700,parents=True,exist_ok=True)
    config=Config.load(a.service_config);config.check_service();api=Feishu(config)
    # The original process-shared lock and pause state cover this test invocation.
    live_store=Store(config.db);provider=ModelCoordinator(LocalQwenProvider(config),live_store,config.root/'state')
    provider.pin();store=Store(out/'gateway.sqlite3')
    gateway=types.SimpleNamespace(config=config,store=store,api=api,provider=provider,authorized=api.authorized)
    logic=LogicService(gateway);gateway.logic=logic
    logic.standards=DocumentStandards(logic,json.loads(a.settings.read_text()))
    stages=[];test_started=time.monotonic()
    def progress(stage):
        value={'stage':stage,'elapsed':round(time.monotonic()-test_started,3)};stages.append(value);print(json.dumps(value),flush=True)
    logic.standards.progress=progress
    now=time.time();row={'app':config.app_id,'tenant':config.tenant_key,'user':config.owner,
        'chat':'local-document-validation','chat_type':'p2p','expires':now+3600}
    logic.standards.authorize(row)
    draft=logic.create(row,a.kind)
    context={'doc_type':a.kind,'project_code':a.project_code,'project_type':a.project_type,'level':a.level,
        'stage':{'charter':'initiation','change':'change','closure':'closure'}[a.kind]}
    store.execute('INSERT INTO amdoc_context VALUES(?,?,?)',(draft['id'],json.dumps(context),draft['expires']))
    if a.project_source:
        logic.add_source(row,draft,a.project_source.name,a.project_source.read_bytes())
        draft=logic.get(row,draft['id'])
    task=dict(row,id=uuid.uuid4().hex,run_id=uuid.uuid4().hex)
    store.execute('INSERT INTO logic_jobs VALUES(?,?,?)',(task['id'],draft['id'],draft['revision']))
    started=time.monotonic();report={'kind':a.kind,'real_qwen':None,'real_feishu_read':True,
        'real_message_flow':False,'human_acceptance':False,'ledger_write':False,'mount':False}
    try:
        content,result,expires=logic.generate(task,lambda *args:None)
        d=logic.get(row,draft['id']);payload=json.loads(store.rows('SELECT payload FROM amdoc_results WHERE draft_id=?',(d['id'],))[0]['payload'])
        (out/'result-private.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        (out/'draft-private.md').write_text(content)
        report.update(state=payload['document']['state'],model=result.model,timings=payload['timings'],
            fields=len(payload['document']['fields']),issues=len(payload['document']['issues']),
            real_qwen=payload['timings']['model_calls']>0,elapsed=time.monotonic()-started)
        if a.save_native:
            native_started=time.monotonic();result=logic.standards.native_action(row,d,'保存云文档')
            (out/'native-private.txt').write_text(result)
            report['native_readback_verified']='已保存并独立回读' in result
            report['native_elapsed']=time.monotonic()-native_started
    except Exception as exc:
        report.update(error_type=type(exc).__name__,error_code=str(exc),elapsed=time.monotonic()-started)
    finally:
        report['stages']=stages
        (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
        store.close();live_store.close()
    return 1 if 'error_code' in report else 0


if __name__=='__main__':raise SystemExit(main())
