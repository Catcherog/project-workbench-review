import {createHash} from 'node:crypto';
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex').slice(0,32);
const ref=v=>v&&typeof v==='object'?String(v.id??v.key??v.value??''):v==null?'':String(v);
const ids=v=>Array.isArray(v)?v.map(ref).filter(Boolean):ref(v)?[ref(v)]:[];
export function deliverableNodes(state,spaceKey,projectId,remoteId){
 return state.externalObjects.filter(o=>o.system==='meegle'&&o.spaceKey===spaceKey&&o.remoteKind==='node'&&o.parentRemoteId===projectId&&o.verificationStatus==='verified'&&!['quarantined','unmapped'].includes(o.mappingStatus)&&o.raw?.sub_workitems?.some(g=>ids(g.workitems).includes(remoteId)));
}
export function importDiscoveredNodes(input,nodes,domain,at){
 let s=structuredClone(input),count=0;const pendingReads=[];
 for(const item of nodes){
  if(item.remoteKind!=='node'||!item.raw?.basic||s.externalObjects.some(o=>o.spaceKey===item.spaceKey&&o.remoteKind==='node'&&o.parentRemoteId===item.parentRemoteId&&o.remoteId===item.remoteId))continue;
  const parent=s.externalObjects.find(o=>o.system==='meegle'&&o.spaceKey===item.spaceKey&&o.remoteKind==='project'&&o.remoteId===item.parentRemoteId&&!['unmapped','quarantined'].includes(o.mappingStatus));if(!parent)continue;
  const suffix=hash([item.spaceKey,item.parentRemoteId,item.remoteId]),id='feishu-node-live-'+suffix,sourceId='feishu-node-source-'+suffix,externalId='external-node-live-'+suffix;
  const title=item.raw.basic.name;if(typeof title!=='string'||!title.trim())continue;
  const fields={name:title,status:item.raw.basic.status},importedFrom={system:'feishu',sourceId:'node:'+item.parentRemoteId+':'+item.remoteId,kind:'flowNodes',readonly:true,collectedAt:at};
  s.flowNodes.push({id,title,projectIds:[parent.localObjectId],sourceIds:[sourceId],version:1,createdAt:at,updatedAt:at,archived:false,classification:'fact',nodeStatus:'待确认',owner:(item.raw.assignees?.owners||[]).map(o=>o.name).filter(Boolean).join('、'),plannedStart:'',plannedEnd:'',milestoneIds:[],importedFrom});
  s.sources.push({id:sourceId,title:'飞书记录 · '+title,projectIds:[parent.localObjectId],sourceIds:[],objectIds:[id],version:1,confirmed:true,collectedAt:at,excerpt:JSON.stringify({kind:'flowNodes',title,sourceId:importedFrom.sourceId,fields,raw:item.raw}),importedFrom});
  const object={...parent,id:externalId,remoteKind:'node',remoteId:item.remoteId,parentRemoteId:parent.remoteId,parentNodeRemoteId:'',parentDeliverableRemoteId:'',localObjectId:id,sourceId,raw:item.raw,collectedAt:at,mappingStatus:'mapped',verificationStatus:'verified'};s.externalObjects.push(object);
  pendingReads.push({...object,externalObjectId:externalId,fields,complete:true});count++;
 }
 if(pendingReads.length)s=domain.mergeFeishuRead(s,pendingReads,{now:at}).state;
 if(count){s.revision=input.revision+1;s.audit.push({id:'feishu-nodes-'+hash([at,count]),time:at,operation:'feishu.nodes.import',objectId:'feishu-sync',actor:'飞书只读同步',before:{count:input.flowNodes.length},after:{count:s.flowNodes.length},revision:s.revision});}
 return {state:count?s:input,count};
}
/** All records mirror existing external objects; no work is created in Feishu. */
export function importDiscoveredDeliverables(input,reads,domain,at){
 let s=structuredClone(input);const imported=[],skipped=[],pendingReads=[];
 for(const read of reads){
  if(!read.complete||read.error||read.remoteKind!=='deliverable'){skipped.push({remoteId:read.remoteId,reason:'读取不完整'});continue;}
  const spaceKey=read.spaceKey,remoteId=String(read.remoteId),fields=read.fields||{};
  if(s.externalObjects.some(o=>o.system==='meegle'&&o.spaceKey===spaceKey&&o.remoteKind==='deliverable'&&o.remoteId===remoteId))continue;
  const declared=[...new Set([ref(fields.field_f7b70e),ref(fields.field_69751f)].filter(Boolean))];
  const projects=s.externalObjects.filter(o=>o.system==='meegle'&&o.spaceKey===spaceKey&&o.remoteKind==='project'&&declared.includes(o.remoteId)&&!['quarantined','unmapped'].includes(o.mappingStatus)&&s.projects.some(p=>p.id===o.localObjectId&&!p.archived));
  if(declared.length!==1||projects.length!==1){skipped.push({remoteId,reason:'所属项目不唯一或不在已开启范围'});continue;}
  const project=projects[0],nodes=deliverableNodes(s,spaceKey,project.remoteId,remoteId);
  const identity=[project.host,project.tenantKey,spaceKey,'deliverable',remoteId],suffix=hash(identity);
  const old=s.deliverables.find(d=>d.importedFrom?.sourceId==='deliverable:'+remoteId&&!d.archived);
  const id=old?.id||'feishu-deliverable-live-'+suffix,sourceId='feishu-source-live-'+suffix,externalId='external-live-'+suffix;
  if(old&&old.projectIds.some(p=>p!==project.localObjectId)){skipped.push({remoteId,reason:'已有本地身份的项目归属冲突'});continue;}
  const title=typeof fields.name==='string'?fields.name.trim():'';if(!title){skipped.push({remoteId,reason:'名称尚未完整读取'});continue;}
  const provenance={system:'feishu',sourceId:'deliverable:'+remoteId,readonly:true,collectedAt:at,kind:'deliverables'};
  if(!s.sources.some(p=>p.id===sourceId))s.sources.push({id:sourceId,title:'飞书记录 · '+title,projectIds:[project.localObjectId],objectIds:[id],sourceIds:[],version:1,createdAt:at,updatedAt:at,collectedAt:at,confirmed:true,type:'其他',excerpt:JSON.stringify({kind:'deliverables',title,sourceId:provenance.sourceId,fields,raw:read.raw},null,2),importedFrom:provenance});
  if(!old)s.deliverables.push({id,title,workspaceId:s.workspaceId,projectIds:[project.localObjectId],sourceIds:[sourceId],flowNodeIds:nodes.map(n=>n.localObjectId),parentDeliverableIds:[],version:1,createdAt:at,updatedAt:at,archived:false,classification:'fact',importedFrom:provenance,status:'未开始',deliveryReview:'未审核',reviewStatus:'未审核',submissionStatus:'未提交',acceptanceStatus:'待验收',description:'',deliverableProgress:'',owner:'',plannedEnd:'',attachments:[],comments:[],sourceRelationGap:nodes.length?'':'已核对项目，节点关系尚未取得'});
  const local=s.deliverables.find(d=>d.id===id);
  const object={id:externalId,workspaceId:s.workspaceId,system:'meegle',host:project.host,tenantKey:project.tenantKey,spaceKey,remoteKind:'deliverable',remoteId,parentRemoteId:project.remoteId,parentNodeRemoteId:nodes[0]?.remoteId||'',parentDeliverableRemoteId:ref(fields.field_e34e4e),localObjectId:id,sourceId,collectedAt:at,sourceHash:'',verificationStatus:'verified',mappingStatus:'mapped',raw:read.raw};
  s.externalObjects.push(object);
  s.syncBaselines.push({id:'baseline-live-'+suffix,workspaceId:s.workspaceId,externalObjectId:externalId,capturedAt:at,sourceHash:'',remoteValues:{},localValues:Object.fromEntries(s.mappingRules.filter(r=>r.remoteKind==='deliverable'&&r.localField).map(r=>[r.localField,local[r.localField]??''])),localRevision:s.revision,sourceId});
  const normalized={...read,externalObjectId:externalId,parentRemoteId:project.remoteId,parentNodeRemoteId:object.parentNodeRemoteId,parentDeliverableRemoteId:object.parentDeliverableRemoteId,collectedAt:at};
  pendingReads.push(normalized);imported.push({remoteId,id,nodeIds:local.flowNodeIds});
 }
 if(pendingReads.length)s=domain.mergeFeishuRead(s,pendingReads,{now:at}).state;
 // Resolve only explicit parent IDs, after every identity has been inserted.
 for(const item of imported){const ext=s.externalObjects.find(o=>o.localObjectId===item.id),local=s.deliverables.find(d=>d.id===item.id);if(!ext.parentDeliverableRemoteId)continue;const parent=s.externalObjects.find(o=>o.spaceKey===ext.spaceKey&&o.remoteKind==='deliverable'&&o.remoteId===ext.parentDeliverableRemoteId&&o.parentRemoteId===ext.parentRemoteId);if(parent&&parent.localObjectId!==local.id)local.parentDeliverableIds=[parent.localObjectId];}
 if(imported.length){s.revision=input.revision+1;s.audit.push({id:'feishu-import-'+hash([at,imported]),time:at,operation:'feishu.deliverables.import',objectId:'feishu-sync',actor:'飞书只读同步',before:{count:input.deliverables.length},after:{items:imported},revision:s.revision});}
 return {state:imported.length?s:input,imported,skipped};
}
