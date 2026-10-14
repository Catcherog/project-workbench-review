import type {Item} from './domain';
import type {V2State} from './v2-types';
import {coreDigest,validCoreProofs,type CoreProof} from './work-item-core';
import {observedDeliveryReview} from './feishu-facts';
export type DeliveryContext={
  targetId:string;nodeId:string;ownerId:string;providerId:string;fileOwnerId:string;teamOwnerId:string;
  verified:boolean;proof:CoreProof[];requirement:string;requirementConflict:boolean;exceptionProof:CoreProof[];
  templates:{sourceId:string;title:string;applicable:boolean;reason:string}[];templateUncertain:boolean;
  materialSourceIds:string[];missing:string[];accessDenied:boolean;linked:boolean;submitted:boolean;reviewValue:string;
  ownerCannotIdentifyProvider?:boolean;providerLookupProof?:CoreProof[];responsibilityDisputed?:boolean;
};
/** This prepares resources and message drafts; it never writes/links a report. */
export function prepareDeliveryCollaboration(s:V2State,row:Item,c:DeliveryContext){
  const target=s.deliverables.find(d=>d.id===c.targetId&&!d.archived),node=s.flowNodes.find(n=>n.id===c.nodeId&&!n.archived);
  const base={workItemId:row.id,targetId:c.targetId,nodeId:c.nodeId,projectIds:row.projectIds,proof:c.proof,fingerprint:coreDigest(c),messages:[] as Item[],materials:[] as Item[],gaps:[] as string[],decision:'',delivered:false};
  if(!target||!c.verified||!validCoreProofs(s,c.proof)){base.gaps.push('真实交付物及现行要求尚未核实');return base;}
  if(!c.requirement?.trim()){base.gaps.push('缺少适用交付要求');return base;}
  if(c.requirementConflict&&!validCoreProofs(s,c.exceptionProof)){base.decision='交付要求冲突，连同双方依据交本人判断';return base;}
  if(c.responsibilityDisputed){base.decision='责任分工存在争议，连同当前依据与反馈交本人协调';return base;}
  if(!node||!row.projectIds.some(id=>node.projectIds.includes(id))){base.decision='关联节点尚未明确，由本人判断并亲自帮助关联';return base;}
  if(c.templateUncertain){base.decision='模板适用性未明确，请本人按差异与依据选择';}
  for(const template of c.templates||[]){const source=s.sources.find(x=>x.id===template.sourceId&&!x.archived);if(source&&(template.applicable||c.templateUncertain))base.materials.push({id:source.id,title:source.title,projectIds:source.projectIds,sourceIds:[source.id],reason:template.reason,role:c.templateUncertain?'template-option':'template'});}
  for(const id of c.materialSourceIds||[]){const source=s.sources.find(x=>x.id===id&&!x.archived);if(source)base.materials.push({id,title:source.title,projectIds:source.projectIds,sourceIds:[id],role:'reference'});else base.gaps.push('资料暂不可读：'+id);}
  const linked=!!target.flowNodeIds?.includes(node.id),reviewValue=observedDeliveryReview(target);
  if(linked&&reviewValue==='已审核'){base.delivered=true;return base;}
  const person=(id:string)=>s.people.find(p=>p.id===id&&!p.archived);
  const message=(recipientId:string,purpose:string,text:string)=>{
    const recipient=person(recipientId);if(!recipient){base.gaps.push('接收人尚未核实：'+purpose);return;}
    base.messages.push({id:coreDigest([row.id,c.targetId,purpose,recipientId]),title:target.title,projectIds:row.projectIds,sourceIds:c.proof.map(p=>p.sourceId),workItemId:row.id,targetId:c.targetId,nodeId:c.nodeId,recipientId,purpose,text,channel:'private',requiresPreview:true});
  };
  if(c.accessDenied){message(c.fileOwnerId,'access','请为报告责任人开放「'+target.title+'」所需资料的访问权限。'+c.missing.join('；'));return base;}
  if(c.missing?.length){
    if(person(c.providerId))message(c.providerId,'materials','为准备「'+target.title+'」，请提供：'+c.missing.join('；')+'。现行要求：'+c.requirement);
    else message(c.ownerCannotIdentifyProvider&&validCoreProofs(s,c.providerLookupProof||[])?c.teamOwnerId:c.ownerId,'provider','「'+target.title+'」还缺：'+c.missing.join('；')+'。请核实这些资料的具体提供方。');
  }else if(!linked)message(c.ownerId,'link','请按现行要求将「'+target.title+'」自行关联到「'+node.title+'」。'+c.requirement);
  else if((target.submissionStatus==='已提交'||c.submitted)&&reviewValue!=='已审核')message(c.ownerId,'review','「'+target.title+'」已提交，当前交付审核尚未回读为已审核，请你推动相应审核。');
  else if(!c.templateUncertain)message(c.ownerId,'prepare','请按适用模板和已提供资料编写「'+target.title+'」。'+c.requirement);
  return base;
}
