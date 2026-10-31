"""Real existing Qwen, synthetic fixtures only; no company template activation or writes."""
import argparse
import json
import time
import uuid
from dataclasses import replace
from pathlib import Path
from am_doc_engine.adapters import ProviderSession, EvidenceBoundModelComposer
from am_doc_engine.catalog import TemplateCatalog
from am_doc_engine.engine import DocumentEngine
from am_doc_engine.models import AccessContext,DraftRequest,profile_from_dict,snapshot_from_dict,ContractError
from am_doc_engine.review import EvidenceSemanticReviewer
from am_doc_engine.storage import SQLiteRunStore
from am_doc_engine.style import derive_style_guide,activate_style_guide,apply_style_guide
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from fs_agent.model_coordinator import ModelCoordinator
from fs_agent.qwen_provider import LocalQwenProvider
from fs_agent.store import Store
from fs_agent.document_standards import SharedProvider


def main():
    p=argparse.ArgumentParser();p.add_argument('--service-config',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    config=Config.load(a.service_config);api=Feishu(config);host_store=Store(config.db)
    coordinator=ModelCoordinator(LocalQwenProvider(config),host_store,config.root/'state');coordinator.pin()
    deadline=time.monotonic()+120
    principal={'user':config.owner,'app':config.app_id,'tenant':config.tenant_key,'chat':'local-document-model-validation','chat_type':'p2p'}
    provider=SharedProvider(coordinator,guard=lambda:api.authorized(principal),deadline=deadline)
    session=ProviderSession(provider,run_id=uuid.uuid4().hex,deadline_monotonic=deadline,timeout=120,max_tokens=4096)
    data=json.loads(a.bundle.read_text());base=next(profile_from_dict(x) for x in data['profiles'] if x['doc_type']=='charter')
    base=replace(base,fields=tuple(replace(f,mode='narrative') if f.field_id in ('background','goal') else f for f in base.fields))
    user=data['access'];access=AccessContext(user['tenant_id'],user['actor_id'],tuple(user['project_ids']),('document:draft','template:manage'),user['app_id'],user['chat_id'])
    report={'real_qwen':True,'fixtures':'synthetic_only','real_feishu_write':False,'company_template_activation':False,'human_acceptance':False}
    try:
        guide=derive_style_guide(base,access,session)
        report['style_candidate']=guide.status=='candidate'
        guide=activate_style_guide(guide,base,access,activation_ref='synthetic:test-authorized')
        profile=apply_style_guide(base,guide)
        request=DraftRequest(**next(x for x in data['requests'] if x['doc_type']=='charter'))
        snapshot=snapshot_from_dict(data['snapshot'])
        with SQLiteRunStore() as store:
            doc=DocumentEngine(TemplateCatalog([profile]),store,composer=EvidenceBoundModelComposer(session=session),reviewer=EvidenceSemanticReviewer(session)).generate(request,access,snapshot)
        report.update(state=doc.state,model_fields=sum(f.origin=='model' for f in doc.fields),issues=[i.code for i in doc.issues],model_calls=provider.calls,model_elapsed=provider.elapsed)
        changed=replace(base,assets=tuple(replace(x,revision=x.revision+'-changed') if x.role=='example' else x for x in base.assets))
        try:apply_style_guide(changed,guide);report['stale_guide_rejected']=False
        except ContractError:report['stale_guide_rejected']=True
    except Exception as exc:report.update(error_type=type(exc).__name__,error_code=str(exc),model_calls=provider.calls)
    finally:
        a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False));host_store.close()
    return int('error_code' in report or report.get('model_fields',0)<1)


if __name__=='__main__':raise SystemExit(main())
