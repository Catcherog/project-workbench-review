import {stableHash,type Item} from './domain';
import type {V2Kind,V2State} from './v2-types';
import {buildWorkbenchOverview} from './workbench-overview';
import {applyWorkItemFindings,workItemState} from './work-items';
import {observedDeliveryReview,deliveryRecorded} from './feishu-facts';
import {ensureCore,coreDigest} from './work-item-core';

/** Date/field rules propose checks. AI decides necessity before they become follow-up. */
export function reconcileBusinessFollowups(s:V2State,at:string):boolean{
 if(s.workspaceType==='restored')return false;
 let changed=false;
 const incoming=buildWorkbenchOverview(s,undefined,Date.parse(at),{includeDataReview:false}).allAttention.filter(item=>['deliverables','actions'].includes(item.kind));
 const targets=[...s.deliverables.filter(r=>r.riskTrackingItemId).map(r=>({kind:'deliverables' as V2Kind,row:r})),...s.actions.filter(r=>r.riskTrackingItemId).map(r=>({kind:'actions' as V2Kind,row:r}))];
 for(const item of incoming)if(!targets.some(t=>t.row.id===item.targetId)){const row=s[item.kind as V2Kind].find(r=>r.id===item.targetId);if(row&&!row.workItemId)targets.push({kind:item.kind as V2Kind,row});}
 for(const {kind,row} of targets){
  if(row.archived||kind==='deliverables'&&row.importedFrom?.system==='feishu'&&!row.feishuFacts?.deliveryReview)continue;
  const sourceId='business-signal-'+stableHash(kind+':'+row.id),id=row.riskTrackingItemId||'business-followup-'+stableHash(kind+':'+row.id);
  const facts={kind,title:row.title,owner:row.owner||row.executor||'',plannedEnd:row.plannedEnd||row.dueAt||'',status:row.status||'',deliveryReview:kind==='deliverables'?observedDeliveryReview(row):'',nodeIds:row.flowNodeIds||[],progress:row.deliverableProgress||row.progressNote||'',blocker:row.blocker||'',rule:'先判断现在是否有必要推进，旧项目历史资料缺口不追补；已审核是工程师交付标记。'};
  const excerpt=JSON.stringify(facts),old=s.sources.find(r=>r.id===sourceId),topic=s.sources.find(r=>r.id===id&&r.workItem);
  if(old?.excerpt===excerpt)continue;
  const source:Item={id:sourceId,title:'业务事实 · '+row.title,projectIds:[...row.projectIds],sourceIds:row.sourceIds||[],objectIds:[row.id],excerpt,version:(old?.version||0)+1,collectedAt:at,occurredAt:at,createdAt:old?.createdAt||at,updatedAt:at,confirmed:false,riskEvent:{kind:'business-followup',targetKind:kind,targetId:row.id},history:old?[...(old.history||[]),{at:old.updatedAt,excerpt:old.excerpt}].slice(-30):[]};
  if(old)Object.assign(old,source);else s.sources.push(source);
  if(!topic){
   const association=row.caseId?{kind:'case' as const,id:row.caseId,confirmed:true,reason:'沿用明确专项'}:row.projectIds.length===1?{kind:'project' as const,id:row.projectIds[0],confirmed:true,reason:'沿用业务工作所属项目'}:{kind:'unknown' as const,id:'',confirmed:false,reason:'归属需要核对'};
   applyWorkItemFindings(s,[{id,title:row.title,summary:incoming.find(i=>i.targetId===row.id)?.reason||'业务工作有变化，需要判断是否跟进',nextStep:'AI先核对必要性与下一步',nature:'action',urgency:'normal',sourceIds:[sourceId],association,businessTarget:{kind,id:row.id}}],at);
   const created=s.sources.find(r=>r.id===id)!;created.workItem.provisional=true;created.workItem.nativeFollowup=true;row.riskTrackingItemId=id;row.version++;
  }else if(kind==='deliverables'&&deliveryRecorded(row)&&row.flowNodeIds?.some((id:string)=>s.flowNodes.some(n=>n.id===id&&!n.archived&&n.projectIds.some(p=>row.projectIds.includes(p))))&&topic.workItem.nativeFollowup&&topic.workItem.nature==='action'&&!topic.workItem.human?.fields?.length){
   const current=workItemState(s,topic,Date.parse(at));topic.workItem.handling={state:'handled',basis:current.basis,evidenceBasis:current.liveEvidenceBasis,staleEvidenceBasis:current.staleEvidenceBasis,at,reason:'飞书已读取工程师的已审核交付标记'};topic.workItem.history.push({at,operation:'delivery-recorded',reason:'工程师已交付，结束本条交付跟进；没有代替内容审核'});topic.version++;
   const core=ensureCore(topic);core.admission=core.admission==='candidate'?'withdrawn':core.admission;core.cycle.temp=null;core.need={...core.need,arranged:true,actor:'none'};topic.workItem.p1||={};topic.workItem.p1.lifecycle={state:'closed',owner:'auto',at,reason:'有效节点关联及已审核交付标记已核实'};core.resultNotice={id:coreDigest([topic.id,source.version,'delivered']),at,text:core.admission==='withdrawn'?'已解决，无需纳入':'工程师交付已记录，本条交付跟进已结束'};
  }
  changed=true;
 }
 return changed;
}
