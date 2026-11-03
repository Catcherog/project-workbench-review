from pathlib import Path
from types import SimpleNamespace
import json,sys,time,hashlib
ROOT=Path(__file__).resolve().parents[3];TASK=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'))
from fs_agent.config import Config
from fs_agent.feishu import Feishu
from fs_agent.gateway import Gateway
from fs_agent.store import Store
from fs_agent.project_catalog import business_ids
cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text());config=Config.load(Path(cfg['poc_config']))
out=TASK/'private/target-diagnostic-v2';out.mkdir(mode=0o700,exist_ok=False)
store=Store(out/'local.sqlite3');g=Gateway(config,store,Feishu(config),SimpleNamespace());port=g.logic.business
row={'user':config.owner,'app':config.app_id,'tenant':config.tenant_key,'chat':'r9fix1-target-read',
    'chat_type':'p2p','expires':time.time()+600}
report=[]
try:
    for alias in port.settings['targets']:
        b=port._authorize(row,alias)
        node=port._run(['workflow','get-node','--project-key',b['space'],'--work-item-id',b['project'],'--node-id-list',b['node'],'--need-sub-task'])
        required=[b[k] for k in ('attachment_field','approval_field','node_field','project_field','document_field','delivery_mode_field')]+['updated_at']
        item=port._run(['workitem','get','--project-key',b['space'],'--work-item-id',b['deliverable'],'--fields',','.join(required)])
        project=port._run(['workitem','get','--project-key',b['space'],'--work-item-id',b['project']])
        key=hashlib.sha256(alias.encode()).hexdigest()[:12]
        (out/(key+'.json')).write_text(json.dumps({'binding':b,'node':node,'item':item,'project':project},ensure_ascii=False,indent=2))
        nodes=node.get('list',[]);groups=[x for n in nodes for x in n.get('sub_workitems',[])]
        members=[str(x) for group in groups for x in group.get('workitems',[])]
        fields=port._fields(item);kind=fields.get(b['document_field']);parent=fields.get(b['project_field'])
        report.append({'alias_sha256':key,'configured_member_in_node':b['deliverable'] in members,
            'node_count':len(nodes),'sub_workitem_group_count':len(groups),'member_count':len(members),
            'group_keys':sorted({k for group in groups for k in group}),
            'project_code_matches_requested':business_ids(project.get('work_item_attribute',{}).get('work_item_name',''))==['IRAD-2026-003'],
            'deliverable_project_matches':(isinstance(parent,dict) and str(parent.get('id'))==b['project']) if b['project_field'] in fields else None,
            'deliverable_node_matches':fields.get(b['node_field'])==b['node'],
            'requested_fields_returned':{k:b[k] in fields for k in ('project_field','node_field','document_field')},
            'document_field_value_type':type(kind).__name__,
            'document_field_contains_url':any(isinstance(v,str) and v.startswith('https://') for v in kind) if isinstance(kind,list) else isinstance(kind,str) and kind.startswith('https://'),
            'read_only':True,'binding_modified':False,
            'private_object_sha256':hashlib.sha256((out/(key+'.json')).read_bytes()).hexdigest()})
finally:
    g.pool.shutdown(wait=True);g.delivery_pool.shutdown(wait=True);g.verification_pool.shutdown(wait=True);store.close()
(TASK/'evidence/target-diagnostic.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
