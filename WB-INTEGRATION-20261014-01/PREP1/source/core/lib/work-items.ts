import {itemTiming,hasTimeOverride,combineEntry,applyEntryChanges,entryPatches,undoEntry} from './work-item-progress';
import {stableHash, type Item} from './domain';
import type {V2Kind, V2State} from './v2-types';
import type {AttentionItem} from './workbench-overview';
import type {FollowupProjection} from './followup-lifecycle';
import {caseEvidenceAvailable} from './case-evidence';
import {managementSignalState} from './management-signals';
import {riskSignalState} from './risk-signals';
import {buildFollowup} from './followup-lifecycle';
import {getProjectGates} from './project-gates';
import {workItemBrief} from './work-item-brief';
import {ensureCore,applyCoreDecision,invalidateCoreDerivations,reconcileCoreReopenProposal} from './work-item-core';

export const workItemNatures = ['progress','action','risk','decision','result','reference','noise'] as const;
export type WorkItemNature = typeof workItemNatures[number];
export const workItemLabels:Record<WorkItemNature,string> = {progress:'进展反馈',action:'待办',risk:'风险待核实',decision:'待决策',result:'成果资料',reference:'背景资料',noise:'无需处理'};
const digest=(value:unknown)=>{const text=JSON.stringify(value);return stableHash(text)+stableHash('work-items:'+text)+stableHash(text+':evidence');};
function fail(message:string,status=422):never{throw Object.assign(new Error(message),{status});}
const unique=(values:string[])=>[...new Set(values)];
const active=(source:Item)=>!source.archived&&!source.workItem?.mergedIntoId;
const bounded=(value:unknown,limit:number)=>typeof value==='string'&&value.length<=limit;
export type WorkAssociation={kind:'project'|'case'|'personal'|'unknown';id:string;reason:string;confirmed:boolean};
export type WorkTriage={necessary:boolean;ready:boolean;reason:string;gaps:string[]};
export type WorkItemFinding={id?:string;existingItemId?:string;expectedVersion?:number;matchReason?:string;materialChange?:boolean;title:string;summary:string;impact?:string;nextStep:string;nature:WorkItemNature;urgency:'normal'|'urgent';sourceIds:string[];association:WorkAssociation;legacyRefs?:string[];businessTarget?:{kind:V2Kind;id:string};limitations?:string[];triage?:WorkTriage;assessmentSourceIds?:string[]};

/** Source aliases preserve historical references. Identity is independent of the
 * collector, chat title and project association. No source is deleted. */
export function workSourceOriginal(s:V2State,source:Item,index?:Map<string,Item>):Item {
  const seen=new Set<string>();let current=source;
  while(current.intakeDocument?.originalSourceId&&!seen.has(current.id)){
    seen.add(current.id);const original=index?index.get(current.intakeDocument.originalSourceId):s.sources.find(row=>row.id===current.intakeDocument.originalSourceId);
    if(!original)break;current=original;
  }
  return current;
}
export function workSourceKey(s:V2State,source:Item,index?:Map<string,Item>):string {
  const original=workSourceOriginal(s,source,index),message=original.personalMessage||original.caseChat;
  return message?.scope&&message.accountId&&message.messageId?'message:'+JSON.stringify([message.scope,message.accountId,message.messageId]):'source:'+original.id;
}
export function workSourceFingerprint(s:V2State,source:Item):string {
  const original=workSourceOriginal(s,source);
  return digest([source.excerpt||'',!!original.archived,!!original.personalMessage?.deleted,!!original.caseChat?.raw?.deleted,
    (source.attachments||[]).map((a:Item)=>[a.id,a.sha256]),source.riskEvidence?.complete===false||source.intakeDocument?.complete===false]);
}
export function workEvidenceSources(s:V2State,sourceIds:string[]):Item[]{
  const groups=new Map<string,Item[]>();
  for(const id of sourceIds){const source=s.sources.find(row=>row.id===id);if(!source)continue;const key=workSourceKey(s,source);groups.set(key,[...(groups.get(key)||[]),source]);}
  return [...groups.values()].map(rows=>rows.sort((a,b)=>String(b.updatedAt||b.collectedAt||'').localeCompare(String(a.updatedAt||a.collectedAt||''))||Number(!!b.intakeDocument)-Number(!!a.intakeDocument)||a.id.localeCompare(b.id))[0]);
}
export function sourceWorkItems(s:V2State,sourceId:string):Item[]{
  const original=s.sources.find(row=>row.id===sourceId),key=original?workSourceKey(s,original):'';
  return s.sources.filter(row=>active(row)&&row.workItem&&row.workItem.evidence.some((e:Item)=>e.sourceId===sourceId||key&&e.key===key));
}
export function workItemOwnsFeedback(s:V2State,sourceId:string):boolean{return sourceWorkItems(s,sourceId).some(row=>['risk','action','decision'].includes(row.workItem.nature));}
const businessNature=(nature:string)=>['risk','action','decision'].includes(nature);
const evidenceStamp=(evidence:Item[])=>digest(evidence.map(e=>[e.key,e.current,e.available]).sort((a,b)=>String(a[0]).localeCompare(String(b[0]))));
function workBusinessContext(s:V2State,source:Item,now:number){
  const target=source.workItem?.businessTarget;
  const row=target&&target.kind!=='sources'?s[target.kind as V2Kind]?.find(r=>r.id===target.id&&!r.archived):undefined;
  const followup=row?buildFollowup(s,{kind:target.kind,targetId:target.id},now):undefined;
  const dates=[...(row?[row.plannedEnd,row.dueAt,row.deadline,row.checkAt,row.committed]:[]),...source.projectIds.map((id:string)=>s.projects.find(p=>p.id===id)).filter((p):p is Item=>!!p).map(p=>getProjectGates(s,p).next?.date)].filter(v=>/^\d{4}-\d{2}-\d{2}$/.test(v||'')).sort();
  return {followup,deadline:dates[0]?dates[0]+'T09:00:00+08:00':'',basis:followup?.evidenceBasis||digest(dates)};
}
export function workItemState(s:V2State,source:Item,now=Date.now()){
  const item=source.workItem;
  const index=new Map(s.sources.map(row=>[row.id,row])),keys=new Set((item.evidence||[]).map((proof:Item)=>proof.key));
  const relevant=s.sources.filter(row=>!row.workItem&&keys.has(workSourceKey(s,row,index)));
  const canonical=new Map(workEvidenceSources(s,relevant.map(row=>row.id)).map(row=>[workSourceKey(s,row,index),row]));
  const evidence=(item.evidence||[]).map((entry:Item)=>{
    const row=canonical.get(entry.key)||s.sources.find(src=>src.id===entry.sourceId),available=!!row&&caseEvidenceAvailable(s,row);
    return {...entry,sourceId:row?.id||entry.sourceId,row,available,current:row?workSourceFingerprint(s,row):''};
  });
  const assessmentKeys=item.assessmentEvidence?.map((e:Item)=>e.key),currentEvidence=assessmentKeys?evidence.filter((e:Item)=>assessmentKeys.includes(e.key)):evidence;
  const invalid=currentEvidence.filter((entry:Item)=>!entry.available||entry.current!==entry.fingerprint),stale=invalid.length>0,liveEvidenceBasis=evidenceStamp(currentEvidence),staleEvidenceBasis=evidenceStamp(invalid);
  const basis=digest([item.semanticRevision||1,item.nature,item.urgency]),handling=item.handling||{};
  const review=(item.reviews||[]).findLast((row:Item)=>row.basis===basis);
  const currentEvidenceReviewed=!!review&&(review.evidenceBasis===liveEvidenceBasis||!!review.staleEvidenceBasis&&review.staleEvidenceBasis===staleEvidenceBasis)||handling.state==='handled'&&handling.basis===basis&&(handling.evidenceBasis===liveEvidenceBasis||!!handling.staleEvidenceBasis&&handling.staleEvidenceBasis===staleEvidenceBasis);
  const pendingChange=item.pendingChange||null,nature:WorkItemNature=item.nature==='risk'?'risk':pendingChange&&businessNature(pendingChange.nature)?pendingChange.nature:item.nature;
  const actionable=businessNature(nature);
  const business=workBusinessContext(s,source,now),timing=itemTiming(s,source,now),legacyNext=Number.isFinite(Date.parse(handling.nextCheckAt||''))?(business.deadline?new Date(Math.min(Date.parse(handling.nextCheckAt),Date.parse(business.deadline))).toISOString():handling.nextCheckAt):'',nextCheckAt=hasTimeOverride(item.p1?.check)?(timing.check.state==='scheduled'&&!timing.check.completedAt&&!timing.check.needsReview?timing.check.effectiveAt||'':''):legacyNext;
  const due=!!nextCheckAt&&Date.parse(nextCheckAt)<=now;
  const businessChanged=handling.state==='waiting'&&!!handling.businessBasis&&handling.businessBasis!==business.basis;
  const reviewedClosed=!!review&&['dismissed','resolved'].includes(review.decision);
  const explicitLife=item.p1?.lifecycle?.state;
  const closed=!pendingChange&&(explicitLife?explicitLife==='closed':(!stale||currentEvidenceReviewed)&&(item.nature==='risk'?reviewedClosed:handling.state==='handled'&&handling.basis===basis));
  const knownConfirmedRisk=item.nature==='risk'&&!closed&&(review?.decision==='confirmed'||item.reviews?.at(-1)?.decision==='confirmed');
  const ignored=item.disposition?.state==='ignored'&&!knownConfirmedRisk&&!pendingChange;
  const changed=handling.basis&&handling.basis!==basis,urgency=item.nature==='risk'&&item.urgency==='urgent'&&!reviewedClosed?'urgent':pendingChange?.urgency||item.urgency;
  const urgent=!closed&&!ignored&&(!stale||currentEvidenceReviewed)&&urgency==='urgent'&&actionable;
  const handlingState=closed||ignored?'handled':pendingChange||stale&&!currentEvidenceReviewed||changed||due||businessChanged||business.followup?.pendingReply?'attention':handling.state==='waiting'?'waiting':handling.state==='in_progress'?'in_progress':'attention';
  const canIgnore=!closed&&!ignored&&!knownConfirmedRisk&&!urgent&&!['publishing','unknown','partial'].includes(source.dataPublication?.status)&&!(source.dataPublication?.artifact&&source.dataPublication.status!=='verified');
  const hasNewData=!actionable&&!closed&&!ignored&&(!!pendingChange||['progress','result'].includes(item.nature)&&item.acknowledgedBasis!==basis||item.manualAttention===true);
  const notificationBasis=pendingChange?digest([basis,pendingChange.id]):basis;
  return {item,timing,evidence,currentEvidence,stale,basis,liveEvidenceBasis,staleEvidenceBasis,review,currentEvidenceReviewed,actionable,closed,ignored,canIgnore,knownConfirmedRisk,pendingChange,nature,hasNewData,notificationBasis,urgent,handlingState,due,business,businessChanged,nextCheckAt,
    needsVerification:!!pendingChange||nature==='risk'&&(!review||stale&&!currentEvidenceReviewed),associationPending:item.association.kind==='unknown'||!item.association.confirmed&&item.association.kind!=='personal'};
}
export function workItemCandidates(s:V2State){
  return s.sources.filter(row=>active(row)&&row.workItem).slice().sort((a,b)=>String(b.workItem.lastChangedAt).localeCompare(String(a.workItem.lastChangedAt))).map(row=>({id:row.id,version:row.version,title:row.title,nature:row.workItem.nature,summary:row.workItem.summary,association:row.workItem.association,sourceIds:row.sourceIds,lastChangedAt:row.workItem.lastChangedAt,limitations:row.workItem.limitations||[],human:row.workItem.human?.fields?.length?row.workItem.human:null,ignored:workItemState(s,row).ignored,pendingChange:row.workItem.pendingChange||null,lastDecision:row.workItem.decisions?.at(-1)||null,closed:workItemState(s,row).closed}));
}
function projectIds(s:V2State,a:WorkAssociation){return a.kind==='project'?[a.id]:a.kind==='case'?s.cases.find(row=>row.id===a.id)?.projectIds||[]:[];}
function validateFinding(s:V2State,f:WorkItemFinding){
  if(f.triage&&(typeof f.triage.necessary!=='boolean'||typeof f.triage.ready!=='boolean'||!bounded(f.triage.reason,1000)||!f.triage.reason.trim()||!Array.isArray(f.triage.gaps)||f.triage.gaps.some(g=>!bounded(g,600))))fail('AI分流缺少必要性、依据或信息缺口');
  if(!workItemNatures.includes(f.nature)||!bounded(f.title,200)||!f.title.trim()||!bounded(f.summary,1600)||!f.summary.trim()||!bounded(f.nextStep,1600)||!bounded(f.impact||'',1600)||!['normal','urgent'].includes(f.urgency))fail('整合事项的内容或分类无效');
  if(!Array.isArray(f.sourceIds)||!f.sourceIds.length||f.sourceIds.length>128||f.sourceIds.some(id=>!s.sources.some(row=>row.id===id&&!row.workItem&&caseEvidenceAvailable(s,row))))fail('整合事项缺少当前可用原文');
  if(f.limitations!==undefined&&(!Array.isArray(f.limitations)||f.limitations.length>64||f.limitations.some(value=>!bounded(value,1000))))fail('事项读取范围说明无效');
  if(f.assessmentSourceIds!==undefined&&(!Array.isArray(f.assessmentSourceIds)||!f.assessmentSourceIds.length||f.assessmentSourceIds.some(id=>!f.sourceIds.includes(id))))fail('当前判断依据须来自本次已核对来源');
  const a=f.association;if(!a||!['project','case','personal','unknown'].includes(a.kind)||!bounded(a.reason,1000))fail('事项归属格式无效');
  if(f.businessTarget&&(!['projects','cases','deliverables','actions','flowNodes','milestones','risks','decisions'].includes(f.businessTarget.kind)||!s[f.businessTarget.kind]?.some(row=>row.id===f.businessTarget!.id&&!row.archived)))fail('关联业务工作不在本工作区');
  if(['project','case'].includes(a.kind)&&!s[a.kind==='project'?'projects':'cases'].some(row=>row.id===a.id&&!row.archived&&!row.mergedIntoId))fail('事项建议归属已不可用');
  if(f.existingItemId){const row=s.sources.find(row=>row.id===f.existingItemId&&row.workItem&&active(row));if(!row||row.version!==f.expectedVersion)throw Object.assign(new Error('已有事项已变化，请重新核对当前人工判断'),{status:409,code:'WORK_ITEM_CHANGED'});if(!f.matchReason?.trim())fail('缺少同一事项的匹配依据');}
}
/** Apply already grounded model results. This creates local observations only;
 * no Tasks, formal plan, acceptance or external publication is changed. */
export function applyWorkItemFindings(s:V2State,findings:WorkItemFinding[],at:string):string[]{
  findings.forEach(f=>validateFinding(s,f));const result:string[]=[];
  for(const input of findings){
    const f=structuredClone(input),incoming=structuredClone(input);
    const id=f.existingItemId||f.id||'work-item-'+digest([s.workspaceId,unique(f.sourceIds.map(sourceId=>workSourceKey(s,s.sources.find(row=>row.id===sourceId)!))).sort(),f.nature,f.title]);
    let source=s.sources.find(row=>row.id===id);if(source&&!source.workItem)fail('事项身份与已有资料冲突',409);
    const old=source?.workItem,priorState=old?workItemState(s,source!):null;
    const inputs=workEvidenceSources(s,f.sourceIds).map(row=>({sourceId:row.id,key:workSourceKey(s,row),fingerprint:workSourceFingerprint(s,row)}));
    const evidence=[...new Map([...(old?.evidence||[]),...inputs].map(row=>[row.key,row])).values()];
    const freshEvidence=!old||inputs.some(proof=>!old.evidence.some((oldProof:Item)=>oldProof.key===proof.key&&oldProof.fingerprint===proof.fingerprint));
    const newBusiness=businessNature(incoming.nature)&&incoming.triage?.necessary!==false&&incoming.materialChange!==false&&freshEvidence;
    const human=old?.human||{fields:[]},locks:string[]=unique([...(human.fields||[]),...(old?.nature==='risk'&&old.reviews?.length||old?.handling?.manuallyReady||old?.handling?.state==='in_progress'||old?.decisions?.length?['nature']:[])]);
    let pendingChange=old?.pendingChange||null,disposition=old?.disposition||{state:'active'},reactivation=old?.reactivation||null;
    const changedLocked=locks.some(field=>field!=='title'&&incoming[field as keyof WorkItemFinding]!==undefined&&incoming[field as keyof WorkItemFinding]!==old?.[field]);
    const proposalKey=digest([incoming.nature,incoming.summary,incoming.impact,incoming.nextStep,inputs]);
    if(old&&locks.length&&changedLocked&&incoming.materialChange!==false&&freshEvidence&&!(old.rejectedChanges||[]).includes(proposalKey)){
      pendingChange={id:proposalKey,title:incoming.title,summary:incoming.summary,nature:incoming.nature,impact:incoming.impact||'',nextStep:incoming.nextStep,urgency:incoming.urgency,sourceIds:f.sourceIds,at,
        previousDisposition:structuredClone(old.disposition||{state:'active'}),reason:incoming.impact||incoming.summary};
    }
    if(old?.p1?.lifecycle?.state==='closed'&&old.p1.lifecycle.owner!=='auto'&&newBusiness)pendingChange={id:proposalKey,title:incoming.title,summary:incoming.summary,nature:incoming.nature,impact:incoming.impact||'',nextStep:incoming.nextStep,urgency:incoming.urgency,sourceIds:f.sourceIds,at,previousDisposition:structuredClone(old.disposition||{state:'active'}),reason:incoming.impact||incoming.summary};
    const mayBackground=old?.nature==='action'&&!locks.length&&!priorState?.closed&&!priorState?.ignored&&f.triage?.necessary===false&&['reference','noise'].includes(f.nature);
    if(old){
      for(const field of locks){if(field==='title')f.title=source!.title;else if(['nature','summary','impact','nextStep','urgency'].includes(field))(f as unknown as Item)[field]=old[field];}
      if(businessNature(old.nature)&&!mayBackground&&!old.provisional&&!priorState!.closed&&(old.nature==='risk'&&f.nature!=='risk'||!businessNature(f.nature))){f.nature=old.nature;f.urgency=old.urgency;f.impact=old.impact;f.nextStep=old.nextStep;}
      if((priorState!.closed||priorState!.ignored)&&!newBusiness&&old.nature==='risk'){f.nature=old.nature;f.urgency=old.urgency;f.impact=old.impact;f.nextStep=old.nextStep;}
      if(priorState!.ignored&&newBusiness){disposition={state:'active',at,reason:'新资料出现实质风险或新的办理要求'};reactivation={at,reason:incoming.impact||incoming.summary,sourceIds:f.sourceIds};}
      if((priorState!.ignored||priorState!.closed)&&!newBusiness)pendingChange=old.pendingChange||null;
      if(pendingChange){f.title=source!.title;for(const field of ['nature','summary','impact','nextStep','urgency'])(f as unknown as Item)[field]=old[field];}
    }
    const association=old?.association?.confirmed?old.association:{...f.association,confirmed:f.association.confirmed===true};
    const limitations=f.limitations||old?.limitations||[];
    if(f.triage?.necessary===false&&(!old||old.provisional))f.nature='reference';
    const messageTriage=old?.nature==='risk'&&f.triage?.necessary===false?f.triage:null;
    const triage=locks.length&&old?.triage?old.triage:messageTriage?old?.triage?.necessary===true?old.triage:{necessary:true,ready:false,reason:'本次消息没有新增动作；原风险继续保留，需按完整当前依据核对下一步。',gaps:['核对原风险当前需要推进的工作']}:(f.triage||old?.triage||null);
    const assessmentEvidence=f.assessmentSourceIds&&!locks.length?inputs.filter(e=>f.assessmentSourceIds!.some(id=>workSourceKey(s,s.sources.find(row=>row.id===id)!)===e.key)):(old?.assessmentEvidence||null);
    const content=[f.title,f.summary,f.impact||'',f.nextStep,f.nature,f.urgency,association,evidence,limitations,pendingChange,disposition,triage,assessmentEvidence,messageTriage];
    if(old?.contentHash===digest(content)){result.push(id);continue;}
    let material=!old||f.materialChange!==false&&freshEvidence||old.nature!==f.nature||old.urgency!==f.urgency;
    if(old&&(pendingChange||priorState!.ignored||priorState!.closed)&&!newBusiness)material=false;
    if(pendingChange)material=false;
    const item={...(old||{}),schemaVersion:1,nature:f.nature,summary:f.summary,impact:f.impact||'',nextStep:f.nextStep,urgency:f.urgency,association,evidence,limitations,human,pendingChange,disposition,reactivation,triage,messageTriage,assessmentEvidence,needsTriage:!!messageTriage&&!old?.triage?.necessary,provisional:old?.provisional===true&&!f.triage,contentHash:digest(content),
      semanticRevision:(old?.semanticRevision||0)+(material?1:0),lastChangedAt:material||pendingChange?.id!==old?.pendingChange?.id?at:old.lastChangedAt,lastReadAt:at,
      legacyRefs:unique([...(old?.legacyRefs||[]),...(f.legacyRefs||[])]),businessTarget:old?.businessTarget||f.businessTarget||null,reviews:old?.reviews||[],handling:old?.handling||{},notificationBaseline:old?.notificationBaseline||'',
      history:old?[...(old.history||[]),{at:source!.updatedAt,title:source!.title,summary:old.summary,nature:old.nature,impact:old.impact,association:old.association,evidence:old.evidence,assessmentEvidence:old.assessmentEvidence||null,triage:old.triage||null,nextStep:old.nextStep,semanticRevision:old.semanticRevision,disposition:old.disposition,pendingChange:old.pendingChange}]:[]};
    const value={...(source||{}),id,title:f.title,type:'整合事项',projectIds:projectIds(s,association),sourceIds:unique(evidence.map((row:Item)=>row.sourceId)),objectIds:[],confirmed:false,processingStatus:'已整理',excerpt:f.summary,version:(source?.version||0)+1,createdAt:source?.createdAt||at,collectedAt:source?.collectedAt||at,updatedAt:at,workItem:item};
    if(source)Object.assign(source,value);else{s.sources.push(value);source=value;ensureCore(source).admission=businessNature(item.nature)?'candidate':'background';}
    if(old&&freshEvidence){const core=ensureCore(source);core.checks={...core.checks,needsRecheck:true,reason:'新来源已保存，重新判断当前需要'};}
    result.push(id);
  }return result;
}
export function workItemRecordView(s:V2State,source:Item,now=Date.now()):AttentionItem{
  const c=workItemState(s,source,now),item=c.item,followup=workItemFollowup(s,source,now),brief=workItemBrief(s,source);
  const ready=item.core?.admission!=='candidate'&&!c.pendingChange&&(!c.stale||c.currentEvidenceReviewed)&&item.association.kind!=='unknown'&&(item.triage?.necessary===true&&item.triage?.ready===true&&!!item.triage.reason||c.review?.decision==='confirmed'||item.handling?.manuallyReady===true&&item.handling.basis===c.basis);
  return {id:'sources:'+source.id,targetId:source.id,kind:'sources',title:brief.title,projectIds:source.projectIds,caseId:item.association.kind==='case'?item.association.id:undefined,
    category:c.closed?'followup':!ready||c.nature==='decision'?'confirmation':'followup',urgent:c.urgent,reason:followup.reason,reasons:[followup.reason],summary:c.pendingChange?.summary||brief.facts,next:c.pendingChange?.nextStep||brief.nextStep,
    owner:c.actionable?'本人':'',date:item.handling?.nextCheckAt||'',sourceIds:source.sourceIds,relatedIds:[],requiresVerification:c.needsVerification,handlingState:followup.handlingState,waitingReason:followup.waitingReason,nextCheckAt:followup.nextCheckAt,followup};
}
export function workItemAttention(s:V2State,now=Date.now()):AttentionItem[]{
  return s.sources.filter(row=>active(row)&&row.workItem).flatMap(source=>{
    const c=workItemState(s,source,now);return c.actionable&&!c.ignored&&s.workspaceType!=='restored'?[workItemRecordView(s,source,now)]:[];
  });
}
export function workItemFollowup(s:V2State,source:Item,now=Date.now()):FollowupProjection{
  const c=workItemState(s,source,now),item=c.item;
  const reason=c.pendingChange?'有新的实质变化待核对：'+c.pendingChange.summary:c.ignored?'已忽略，普通补充不再提示':c.stale&&!c.currentEvidenceReviewed?'原依据已变化或不可用，等待重新理解':c.closed?'本事项已处理':c.due?'已到跟进时间':item.impact||item.nextStep||item.summary;
  return {kind:'sources',targetId:source.id,itemKey:[s.workspaceId,'sources',source.id].map(encodeURIComponent).join(':'),title:source.title,projectIds:source.projectIds,caseId:item.association.kind==='case'?item.association.id:undefined,
    handlingState:c.handlingState as FollowupProjection['handlingState'],urgent:c.urgent,reason:c.business.followup?.pendingReply?'关联工作已有新反馈，待核对':c.businessChanged?'关联工作的期限或依据已有变化':reason,reasons:[reason],waitingReason:item.handling?.reason||'',nextCheckAt:c.nextCheckAt,primaryAction:'inspect',feedbackState:c.stale?'stale':c.business.followup?.feedbackState||'none',clarification:c.business.followup?.clarification||'',reminderEligible:!!c.business.followup?.reminderEligible,
    notificationBasis:c.notificationBasis,suppressNotification:item.notificationBaseline===c.notificationBasis||c.ignored,basis:digest([c.basis,c.liveEvidenceBasis,source.version,c.stale,item.handling,item.disposition,c.pendingChange?.id]),evidenceBasis:digest(item.evidence),feedbackBasis:c.basis,gateBasis:c.business.followup?.gateBasis||c.business.basis,sources:c.evidence.map((e:Item)=>({id:e.sourceId,version:e.row?.version||0,title:e.row?.title||'原文不可用',available:e.available,fingerprint:e.current,eventAt:e.row?.occurredAt||''})),pendingReply:!!c.business.followup?.pendingReply,executionSourceIds:c.business.followup?.executionSourceIds||[],active:c.actionable&&!c.closed&&!c.ignored&&!source.archived,
    businessStates:c.business.followup?.businessStates||{feedback:item.summary,submission:'',professionalReview:'',acceptance:'',node:'',syncApproval:''}};
}
function ownEvidence(s:V2State,source:Item,reason:string,requestId:string,at:string){
  const id='work-item-note-'+digest([s.workspaceId,requestId]);
  const note:Item={id,title:('本人核实说明 · '+source.title).slice(0,200),excerpt:reason,author:'本人',type:'本人说明',projectIds:[...source.projectIds],sourceIds:[],objectIds:[source.id],version:1,confirmed:true,collectedAt:at,occurredAt:at};
  if(!s.sources.some(row=>row.id===id))s.sources.push(note);
  source.workItem.evidence.push({sourceId:id,key:workSourceKey(s,note),fingerprint:workSourceFingerprint(s,note)});source.sourceIds=unique([...source.sourceIds,id]);
}
function reviewItem(s:V2State,source:Item,decision:string,reason:string,at:string,extra:Partial<Item>={}){
  const c=workItemState(s,source);
  source.workItem.reviews.push({basis:c.basis,evidenceBasis:c.liveEvidenceBasis,staleEvidenceBasis:c.staleEvidenceBasis,decision,reason,actor:'本人',at,...extra});
}
function correctItem(s:V2State,source:Item,patch:Partial<Item>,op:Partial<Item>,at:string){
  const item=source.workItem,c=workItemState(s,source),keys=Object.keys(patch),allowed=['title','summary','nature','impact','nextStep','urgency'];
  if(!keys.length||keys.some(key=>!allowed.includes(key)))fail('请选择需要调整的分类或理解内容');
  const nature=patch.nature===undefined?item.nature:patch.nature;
  if(!workItemNatures.includes(nature))fail('事项分类无效');
  for(const key of ['title','summary','impact','nextStep'])if(patch[key]!==undefined&&(!bounded(patch[key],key==='title'?200:1600)||['title','summary'].includes(key)&&!patch[key].trim()))fail('事项标题或内容无效');
  if(patch.urgency!==undefined&&!['normal','urgent'].includes(patch.urgency))fail('紧迫度无效');
  const changedNature=nature!==item.nature;
  if(changedNature&&(nature==='risk'||item.nature==='risk')&&!op.reason?.trim())fail('调整风险分类需要填写简短理由或依据');
  if(item.nature==='risk'&&nature!=='risk'&&!c.closed){
    if(!['dismissed','resolved'].includes(op.riskDisposition)||!op.reason?.trim())fail('请先说明原风险是不成立还是已解除');
    reviewItem(s,source,op.riskDisposition,op.reason,at,{classificationCorrection:true});
  }
  if(nature==='risk'&&(changedNature||op.riskDecision&&op.riskDecision!=='preserve')){
    if(!['pending','confirmed'].includes(op.riskDecision)||!op.reason?.trim()||!(patch.impact??item.impact)?.trim())fail('列为风险时请选择待核实或已确认，并填写影响与依据');
  }
  const currentReview=c.review,resetRisk=nature==='risk'&&op.riskDecision==='pending';
  if(changedNature||resetRisk||patch.urgency&&patch.urgency!==item.urgency)item.semanticRevision++;
  if(patch.title!==undefined)source.title=patch.title.trim();
  for(const key of ['summary','nature','impact','nextStep','urgency'])if(patch[key]!==undefined)item[key]=patch[key];
  source.excerpt=item.summary;
  item.human={fields:unique([...(item.human?.fields||[]),...keys]),at,reason:op.reason||'本人更正理解'};
  item.disposition={state:'active',at};item.pendingChange=null;item.manualAttention=false;item.contentHash='';
  if(changedNature||resetRisk)item.handling={state:'attention',basis:workItemState(s,source).basis,at};
  if(nature==='risk'&&op.riskDecision==='confirmed'){
    ownEvidence(s,source,op.reason,op.requestId,at);reviewItem(s,source,'confirmed',op.reason,at);
  }else if(nature==='risk'&&!resetRisk&&!changedNature&&currentReview&&currentReview.basis!==workItemState(s,source).basis){
    reviewItem(s,source,currentReview.decision,currentReview.reason,at,{preservedByCorrection:true});
  }
  if(!businessNature(nature))item.acknowledgedBasis=workItemState(s,source).basis;
  item.notificationBaseline=workItemState(s,source).notificationBasis;
}
export function applyWorkItemOperation(input:V2State,op:Partial<Item>,at:string):V2State{
  if(input.workspaceType==='restored')fail('恢复工作区只保留事项历史，请在正式工作区重新核对',409);
  if(op.reason!==undefined&&!bounded(op.reason,1000))fail('处理说明不能超过1000字');
  const receiptKey='work-item:'+op.requestId;
  if(!/^[\w-]{1,160}$/.test(op.requestId||'')||op.workspaceId!==input.workspaceId)fail('事项请求身份无效');
  const hash=digest(op),receipt=input.receipts[receiptKey];if(receipt){if(receipt.fingerprint!==hash)fail('同一请求不能改动操作内容',409);return input;}
  const s=structuredClone(input);
  if(op.action==='adopt'){
    const original=s.sources.find(row=>row.id===op.sourceId&&!row.archived);
    if(!original||original.version!==op.expectedVersion)fail('资料已变化，请刷新后处理',409);
    const existing=sourceWorkItems(s,original.id);if(existing.length>1)fail('这份原文已关联多个事项，请选择具体事项',409);
    let id=original.workItem?original.id:existing[0]?.id;
    if(!id){
      id='work-item-manual-'+digest([s.workspaceId,original.id]);
      const ids=unique([original.id,...(original.intakeBatch?.documents||[])]).filter(id=>s.sources.some(row=>row.id===id&&caseEvidenceAvailable(s,row)));
      if(!ids.length)fail('原文已不可用，请先补充可追溯的资料');
      const project=original.projectIds.length===1?original.projectIds[0]:'';
      const brief=workItemBrief(s,original);
      applyWorkItemFindings(s,[{id,title:brief.title,summary:brief.facts,impact:brief.impact,nextStep:brief.nextStep,nature:'reference',urgency:'normal',sourceIds:ids,association:{kind:project?'project':'unknown',id:project,reason:'沿用原资料关联',confirmed:!!project},limitations:[...brief.gaps,...(original.intakeBatch?.status==='partial'?['本资料只读到部分内容']:[])]}],at);
      s.sources.find(row=>row.id===id)!.workItem.manualAttention=true;
    }
    s.revision++;s.receipts[receiptKey]={fingerprint:hash,result:{sourceId:id}};
    s.audit.push({id:'work-item-'+digest([receiptKey,hash]),time:at,operation:'work-item.adopt',kind:'sources',objectId:id,actor:'本人',before:null,after:{originalSourceId:original.id},revision:s.revision});return s;
  }
  const source=s.sources.find(row=>row.id===op.sourceId&&row.workItem&&active(row));
  if(!source||op.action!=='p1-undo'&&source.version!==op.expectedVersion)fail('事项已变化，请刷新后核对',409);
  const c=workItemState(s,source),item=source.workItem;
  if(op.action!=='p1-undo'&&(op.expectedBasis!==c.basis||op.expectedEvidenceBasis!==undefined&&op.expectedEvidenceBasis!==c.liveEvidenceBasis))fail('事项依据已变化，请重新核对',409);
  const before=structuredClone(item),previousTitle=source.title;let p1Result:Omit<Item,'id'|'title'|'projectIds'|'sourceIds'>|undefined;const sourceEffects:Item[]=[];item.provisional=false;
  if(op.action?.startsWith('core-')){
    const calendar=s.sources.find(row=>row.workCalendar&&!row.archived)?.workCalendar;
    applyCoreDecision(s,source,op as Item,at,calendar);
  }else if(op.action==='p1-submit'){
    const prepared=combineEntry(op.entry,op.input);
    if(prepared.conflicts.length)throw Object.assign(new Error('本次输入有待澄清的具体差异，未保存。'),{status:422,conflicts:prepared.conflicts});
    if(!Object.keys(prepared.changes).length)return input;
    const change=prepared.changes,core=ensureCore(source),inputSource=s.sources.find(r=>r.id===op.inputSourceId),eventAt=inputSource?.inputEnvelope?.origin==='feishu'?op.input.occurredAt:at,pendingChanges:Item[]=[];
    if(inputSource?.inputEnvelope?.origin==='feishu'){
      const names:Record<string,string>={check:'检查安排',completion:'完成要求',waiting:'等待安排',followup:'跟进状态',riskDecision:'风险结论'};
      for(const key of ['check','completion','waiting','followup','riskDecision'] as const){
        const field=key==='followup'?'lifecycle':key,oldAt=core.instructionAt?.[field]||item.p1?.[field]?.at||'';
        const closedAt=item.p1?.lifecycle?.owner==='manual'&&item.p1.lifecycle.state==='closed'?(core.instructionAt?.lifecycle||item.p1.lifecycle.at):'';
        if(change[key]&&eventAt<(oldAt>closedAt?oldAt:closedAt)){delete change[key];if(key==='riskDecision')delete change.riskQuote;if(key==='followup')delete change.followupQuote;pendingChanges.push({id:key,title:names[key],projectIds:[],sourceIds:[],message:names[key]+'已有较新人工决定，旧消息只留存，不覆盖。'});}
      }
    }
    if(change.riskDecision&&item.nature!=='risk')fail('当前事项不是风险，不能修改风险结论');
    if(change.followup==='end'&&item.nature==='risk'&&!['resolved','dismissed'].includes(change.riskDecision||c.review?.decision))fail('风险尚未解除；本次只能记录进展或明确停止跟进原因');
    if(c.closed&&!change.followup&&!change.progress&&!change.checkCompleted)fail('事项已结束，请重新打开后再安排时间');
    if(change.checkCompleted&&!hasTimeOverride(item.p1?.check)){item.p1||={};item.p1.check=structuredClone(c.timing.check);}
    applyEntryChanges(source,change,op.requestId,at);
    for(const key of ['check','completion','waiting','followup','riskDecision'] as const)if(change[key]){core.instructionAt||={};core.instructionAt[key==='followup'?'lifecycle':key]=eventAt;}
    if(op.inputSourceId&&change.progress){const progress=item.p1.progress.find((r:Item)=>r.id===(change.progress!.editId||op.requestId));progress.inputSourceId=op.inputSourceId;progress.sourceIds=[op.inputSourceId];}
    if(change.riskDecision)reviewItem(s,source,change.riskDecision,change.riskQuote||'',at);
    if(change.followup==='continue')item.notificationBaseline=c.notificationBasis;
    if(op.input?.editProgressId){const previous=before.p1?.progress?.find((r:Item)=>r.id===op.input.editProgressId);const note=s.sources.find(r=>r.id===previous?.inputSourceId);if(note?.inputEnvelope){const prior={effectWithdrawn:note.inputEnvelope.effectWithdrawn===true,correctedBy:note.inputEnvelope.correctedBy||''};note.inputEnvelope.effectWithdrawn=true;note.inputEnvelope.correctedBy=op.inputSourceId;sourceEffects.push({id:note.id,title:'本次纠正影响的原输入效力',projectIds:[],sourceIds:[],before:prior,after:{effectWithdrawn:true,correctedBy:op.inputSourceId||''}});note.version++;item.evidence=item.evidence.filter((e:Item)=>e.sourceId!==note.id);if(item.assessmentEvidence)item.assessmentEvidence=item.assessmentEvidence.filter((e:Item)=>e.sourceId!==note.id);}}
    const patches=entryPatches(before,item);
    p1Result={p1:true,version:source.version+1,basis:workItemState(s,source).basis,evidence:workItemState(s,source).liveEvidenceBasis,operationId:op.requestId,progressId:change.progress?(change.progress.editId||op.requestId):'',at,sourceId:source.id,sourceEffects,pendingChanges,patches,progress:change.progress?.text||'',changes:Object.keys(change),closed:item.p1?.lifecycle?.state==='closed',stay:prepared.stay||pendingChanges.length>0,timing:itemTiming(s,source,at),input:op.input};
  }else if(op.action==='p1-undo'){
    const original=s.receipts['work-item:'+op.operationId]?.result;
    if(!original?.p1||original.sourceId!==source.id)fail('没有可撤销的本次操作');
    if(original.undoneAt)return input;
    for(const effect of original.sourceEffects||[]){const note=s.sources.find(r=>r.id===effect.id);if(!note?.inputEnvelope||JSON.stringify({effectWithdrawn:note.inputEnvelope.effectWithdrawn===true,correctedBy:note.inputEnvelope.correctedBy||''})!==JSON.stringify(effect.after))fail('相关来源效力已有后续修改，未撤销任何内容',409);Object.assign(note.inputEnvelope,effect.before);note.version++;if(!item.evidence.some((e:Item)=>e.sourceId===note.id))item.evidence.push({sourceId:note.id,key:workSourceKey(s,note),fingerprint:workSourceFingerprint(s,note)});}
    for(const target of original.relatedPatches||[{id:source.id,patches:original.patches}]){
      const related=s.sources.find(r=>r.id===target.id&&r.workItem);if(!related)fail('同次操作的相关事项已不可用，未撤销任何内容',409);
      // A newly created identity remains as an ignored historical item. Validate
      // all conflicts on a clone; deleting its required fields would corrupt it.
      undoEntry(target.created?structuredClone(related):related,target.patches);
      related.workItem.evidence=related.workItem.evidence.filter((e:Item)=>e.sourceId!==original.inputSourceId);
      if(related.workItem.assessmentEvidence)related.workItem.assessmentEvidence=related.workItem.assessmentEvidence.filter((e:Item)=>e.sourceId!==original.inputSourceId);
      if(target.created){related.workItem.disposition={state:'ignored',at,reason:'撤销本次新建；原件与历史保留'};ensureCore(related).admission='withdrawn';related.workItem.p1||={};related.workItem.p1.lifecycle={state:'closed',owner:'manual',at,reason:'撤销本次新建；保留历史身份'};}
      if(related!==source){related.version++;invalidateCoreDerivations(s,related,at,'同次操作撤销');}
    }
    const note=s.sources.find(r=>r.id===original.inputSourceId);if(note?.inputEnvelope){note.inputEnvelope.effectWithdrawn=true;note.version++;}
    original.undoneAt=at;original.undoneBy=op.requestId;
    const core=ensureCore(source);for(const patch of original.patches||[]){if(patch.path[0]==='p1'&&['check','completion','waiting','lifecycle','riskDecision'].includes(patch.path[1])){core.instructionAt||={};core.instructionAt[patch.path[1]]=at;}}
  }else if(op.action==='associate'){
    const a=op.association as WorkAssociation;
    if(!a||!['project','case','personal','unknown'].includes(a.kind))fail('请选择事项归属');
    if(['project','case'].includes(a.kind)&&!s[a.kind==='project'?'projects':'cases'].some(row=>row.id===a.id&&!row.archived))fail('事项归属已不可用');
    item.association={kind:a.kind,id:['project','case'].includes(a.kind)?a.id:'',reason:'本人确认',confirmed:true};source.projectIds=projectIds(s,item.association);
  }else if(op.action==='ignore'){
    if(!c.canIgnore)fail(c.knownConfirmedRisk||c.urgent?'已确认或紧急风险请记录不成立、解除或等待，不用忽略代替风险处理':'请先核对已有执行结果，或恢复后再操作');
    if(source.dataPublication&&!source.dataPublication.artifact&&['prepared','stale','failed'].includes(source.dataPublication.status)){const publicationBefore={status:source.dataPublication.status,targetId:source.dataPublication.targetId,destination:source.dataPublication.destination};source.dataPublication.status='cancelled';source.dataPublication.cancelledAt=at;source.dataPublication.approvedAt='';source.dataPublication.error='';s.audit.push({id:'cancel-on-ignore-'+digest(receiptKey),time:at,operation:'data.publication.cancel',kind:'sources',objectId:source.id,actor:'本人',before:publicationBefore,after:{status:'cancelled',reason:'本人选择忽略并取消未执行的挂载准备'},revision:s.revision+1});}
    item.disposition={state:'ignored',basis:c.basis,at,reason:op.reason||'本人选择忽略'};item.pendingChange=null;item.manualAttention=false;
  }else if(op.action==='restore'||op.action==='reopen'){
    if(c.closed&&item.nature==='risk'){if(!op.reason?.trim())fail('重新核实风险需填写简短原因');item.semanticRevision++;}
    if(item.p1){item.p1.lifecycle={state:'open',reason:op.reason||'本人重新打开',at};if(item.p1.check?.state==='scheduled'&&Date.parse(item.p1.check.effectiveAt||'')<=Date.parse(at))item.p1.check={...item.p1.check,needsReview:true,reviewReason:'原检查时间已过，重新安排前保持待核对'};}
    item.disposition={state:'active',at,reason:op.reason||'本人恢复关注'};item.handling={state:'attention',basis:workItemState(s,source).basis,at};
    item.manualAttention=!businessNature(item.nature);item.acknowledgedBasis='';item.notificationBaseline=workItemState(s,source).notificationBasis;
  }else if(op.action==='acknowledge'){
    if(c.actionable||c.pendingChange)fail('请在原事项完成业务处理或核对新变化');
    item.acknowledgedBasis=c.basis;item.manualAttention=false;
  }else if(op.action==='correct'){
    correctItem(s,source,op.patch||{},op,at);
    if(businessNature(item.nature)&&ensureCore(source).admission==='background')item.core.admission='managed';
  }else if(op.action==='change-decision'){
    const change=item.pendingChange;
    if(!change||change.id!==op.changeId||!['accept','reject'].includes(op.decision))fail('新变化已更新，请重新核对',409);
    if(op.decision==='reject'){
      if(!op.reason?.trim())fail('保留原判断时请说明简短理由');
      item.rejectedChanges=unique([...(item.rejectedChanges||[]),change.id]);item.disposition=change.previousDisposition||{state:'active'};item.pendingChange=null;
    }else{
      if(item.p1?.lifecycle?.state==='closed')item.p1.lifecycle={state:'open',reason:op.reason||'本人采用新的实质变化',at};
      correctItem(s,source,Object.fromEntries(['title','summary','nature','impact','nextStep','urgency'].map(key=>[key,change[key]])),{...op,riskDecision:op.riskDecision||'pending',reason:op.reason||'本人采纳本次变化'},at);
    }
    item.notificationBaseline=workItemState(s,source).notificationBasis;
  }else if(op.action==='review'){
    if(item.pendingChange)fail('请先核对新的分类或内容建议，再记录风险结论');
    if(item.nature!=='risk'||!['confirmed','dismissed','resolved'].includes(op.decision)||!op.reason?.trim()||!bounded(op.reason,1000))fail('请选择风险结论并说明依据');
    if(c.stale&&op.decision!=='dismissed'){
      if(op.addOwnEvidence!==true)fail('原依据已变化，请补充本人核实依据后再记录',409);
      ownEvidence(s,source,op.reason,op.requestId,at);
    }
    reviewItem(s,source,op.decision,op.reason.trim(),at);item.human={fields:unique([...(item.human?.fields||[]),'nature']),at,reason:op.reason};item.disposition={state:'active',at};item.notificationBaseline=workItemState(s,source).notificationBasis;
  }else if(op.action==='confirm_ready'){
    if(!op.reason?.trim()||c.stale&&!c.currentEvidenceReviewed||c.pendingChange)fail('请先核对当前依据和新变化，并说明下一步');
    item.handling={state:'attention',basis:c.basis,manuallyReady:true,reason:op.reason,at};
    ensureCore(source).admission='managed';
  }else if(['take_over','wait','resume','done'].includes(op.action)){
    if(c.ignored)fail('请先恢复关注');
    if(item.pendingChange)fail('请先核对新变化');
    if(op.action==='done'&&c.stale&&!c.currentEvidenceReviewed){
      if(item.nature==='risk'||op.addOwnEvidence!==true||!op.reason?.trim())fail('原依据已变化，请补充本人核实说明后再办结',409);
      ownEvidence(s,source,op.reason,op.requestId,at);
    }
    if(op.action==='done'&&item.nature==='decision'&&!op.reason?.trim())fail('请记录本次决定和简短依据');
    if(op.action==='done'&&item.nature==='decision')item.decisions=[...(item.decisions||[]),{basis:c.basis,text:op.reason,at,actor:'本人'}];
    if(op.action==='done'&&item.nature==='risk'&&!c.closed)fail('请先在本事项记录风险解除或疑点不成立');
    if(op.action==='wait'&&(!op.reason?.trim()||!Number.isFinite(Date.parse(op.nextCheckAt))||Date.parse(op.nextCheckAt)<=Date.parse(at)))fail('等待需填写原因和未来的跟进时间');
    if(op.action==='done'){item.p1||={};item.p1.lifecycle={state:'closed',owner:'manual',reason:op.reason||'本人确认本事项已办结',at};}
    if(op.action==='wait'&&item.p1)item.p1.check={state:'scheduled',effectiveAt:op.nextCheckAt,date:op.nextCheckAt.slice(0,10),precision:'minute',origin:'legacy-input',at};
    const current=workItemState(s,source);
    item.handling={manuallyReady:item.handling?.manuallyReady===true,businessBasis:current.business.basis,...(op.action==='done'?{evidenceBasis:current.liveEvidenceBasis,staleEvidenceBasis:current.staleEvidenceBasis}:{}),state:op.action==='wait'?'waiting':op.action==='done'?'handled':op.action==='take_over'?'in_progress':'attention',reason:String(op.reason||'').slice(0,1000),nextCheckAt:op.action==='wait'?op.nextCheckAt:item.handling?.nextCheckAt||'',basis:c.basis,at};
  }else if(op.action==='split'){
    if(!op.title?.trim()||!op.summary?.trim()||!op.remainingSummary?.trim()||!op.reason?.trim()||!Array.isArray(op.sourceIds)||!op.sourceIds.length||op.sourceIds.some((id:string)=>!source.sourceIds.includes(id)))fail('拆分需填写两边内容、拆分理由，并选择原事项内的依据');
    if(!bounded(op.title,200)||!bounded(op.summary,1600)||!bounded(op.remainingSummary,1600)||!bounded(op.impact||'',1600)||!bounded(op.nextStep||'',1600)||!workItemNatures.includes(op.nature))fail('拆分内容或类型无效');
    const splitIds=op.sourceIds as string[];
    const childId='work-item-split-'+digest([s.workspaceId,op.requestId]);
    const child=structuredClone(source);child.id=childId;child.title=op.title.trim();child.excerpt=op.summary.trim();child.version=1;child.createdAt=at;child.updatedAt=at;delete child.dataPublication;
    child.sourceIds=unique(splitIds);child.workItem={...structuredClone(item),triage:null,provisional:false,nativeFollowup:false,nature:op.nature,urgency:'normal',summary:op.summary.trim(),nextStep:op.nextStep||'跟进拆分出的事项',impact:op.impact||'',semanticRevision:1,reviews:[],decisions:[],handling:{},disposition:{state:'active'},pendingChange:null,rejectedChanges:[],manualAttention:false,acknowledgedBasis:'',legacyRefs:[],businessTarget:null,reactivation:null,contentHash:'',
      evidence:item.evidence.filter((proof:Item)=>splitIds.includes(proof.sourceId)),human:{fields:['nature','title','summary'],at,reason:op.reason},history:[{at,operation:'split-from',splitFrom:source.id,reason:op.reason}],lastChangedAt:at,lastReadAt:at};
    if(!child.workItem.evidence.length)fail('未选到可追溯的拆分依据');
    if(op.nature==='risk'&&(!child.workItem.impact.trim()||!['pending','confirmed'].includes(op.riskDecision)))fail('拆分为风险时需说明影响并选择核实状态');
    s.sources.push(child);child.workItem.handling={state:'attention',manuallyReady:op.nature==='action',basis:workItemState(s,child).basis,at};
    if(op.nature==='risk'&&op.riskDecision==='confirmed'){ownEvidence(s,child,op.reason,op.requestId,at);reviewItem(s,child,'confirmed',op.reason,at);}
    child.workItem.notificationBaseline=workItemState(s,child).notificationBasis;if(!businessNature(op.nature))child.workItem.acknowledgedBasis=workItemState(s,child).basis;
    item.summary=op.remainingSummary.trim();source.excerpt=item.summary;item.human={fields:unique([...(item.human?.fields||[]),'summary']),at,reason:op.reason};item.contentHash='';item.manualAttention=false;if(!businessNature(item.nature))item.acknowledgedBasis=workItemState(s,source).basis;
    item.history.push({at,operation:'split-to',splitTo:childId,reason:op.reason});op={...op,splitSourceId:childId};
  }else if(op.action==='merge'){
    const target=s.sources.find(row=>row.id===op.targetId&&row.workItem&&active(row));
    if(!target||target.id===source.id||target.version!==op.targetVersion||!op.reason?.trim())fail('合并目标已变化或缺少理由',409);
    if([source,target].some(row=>['publishing','unknown','partial'].includes(row.dataPublication?.status)||row.dataPublication?.artifact&&row.dataPublication.status!=='verified'))fail('请先核对已有挂载执行结果，再合并事项',409);
    if(item.pendingChange&&target.workItem.pendingChange&&item.pendingChange.id!==target.workItem.pendingChange.id)fail('两个事项都有新变化，请先核对各自建议后再合并');
    if(item.association.confirmed&&target.workItem.association.confirmed&&JSON.stringify([item.association.kind,item.association.id])!==JSON.stringify([target.workItem.association.kind,target.workItem.association.id]))fail('两个事项的已确认归属不同，请先核对归属');
    target.workItem.evidence=[...new Map([...target.workItem.evidence,...item.evidence].map((e:Item)=>[e.key,e])).values()];target.sourceIds=unique(target.workItem.evidence.map((e:Item)=>e.sourceId));
    target.workItem.legacyRefs=unique([...target.workItem.legacyRefs,...item.legacyRefs]);
    target.workItem.history.push({at,operation:'merge',mergedFrom:source.id,title:source.title,summary:item.summary,reviews:item.reviews,decisions:item.decisions||[],handling:item.handling,disposition:item.disposition,pendingChange:item.pendingChange,reason:op.reason});
    if(c.nature==='risk')target.workItem.nature='risk';if(c.urgent)target.workItem.urgency='urgent';
    if(item.pendingChange&&!target.workItem.pendingChange)target.workItem.pendingChange={...structuredClone(item.pendingChange),previousDisposition:structuredClone(target.workItem.disposition||{state:'active'})};
    if(c.knownConfirmedRisk){const prior=item.reviews.findLast((review:Item)=>review.decision==='confirmed');if(prior)target.workItem.reviews.push({...structuredClone(prior),basis:'merged-'+digest([source.id,prior.basis,op.requestId]),originalBasis:prior.basis,mergedFromSourceId:source.id});}
    target.workItem.disposition={state:'active',at};target.workItem.human={fields:unique([...(target.workItem.human?.fields||[]),'nature']),at,reason:op.reason};
    target.workItem.semanticRevision++;target.workItem.lastChangedAt=at;target.version++;target.updatedAt=at;item.mergedIntoId=target.id;
    target.workItem.notificationBaseline=workItemState(s,target).notificationBasis;
    for(const row of s.sources){if(row.managementSignal?.workItemId===source.id)row.managementSignal.workItemId=target.id;for(const signal of row.intakeBatch?.signals||[])if(signal.workItemId===source.id)signal.workItemId=target.id;}
  }else fail('不支持的事项操作');
  if(['correct','p1-undo','p1-submit','reopen','restore','change-decision'].includes(op.action))invalidateCoreDerivations(s,source,at,op.action);
  if(item.p1?.lifecycle?.state==='closed'&&item.p1.lifecycle.at===at)item.p1.lifecycle.owner='manual';
  if(['done','reopen','restore','ignore','change-decision'].includes(op.action)){const core=ensureCore(source);core.instructionAt={...(core.instructionAt||{}),lifecycle:at};}
  if(op.action==='review'){const core=ensureCore(source);core.instructionAt={...(core.instructionAt||{}),riskDecision:at,...(workItemState(s,source).closed?{lifecycle:at}:{})};}
  reconcileCoreReopenProposal(s,source,at,{decided:['done','reopen','restore','ignore','change-decision'].includes(op.action)});
  item.history.push({at,operation:op.action,reason:op.reason||'',title:previousTitle,summary:before.summary,nature:before.nature,disposition:before.disposition,handling:before.handling,pendingChange:before.pendingChange});
  item.lastChangedAt=at;source.version++;source.updatedAt=at;s.revision++;s.receipts[receiptKey]={fingerprint:hash,result:{sourceId:source.id,...(p1Result||{}),...(op.splitSourceId?{splitSourceId:op.splitSourceId}:{})}};
  s.audit.push({id:'work-item-'+digest([receiptKey,hash]),time:at,operation:'work-item.'+op.action,kind:'sources',objectId:source.id,actor:'本人',before,after:structuredClone(item),revision:s.revision});return s;
}

/** Legacy projections are moved once, preserving every review and source. Names
 * and a shared project never cause an automatic semantic merge. */
export function connectLegacyWorkItems(s:V2State,at:string,{historical=false}:{historical?:boolean}={}):boolean{
  let changed=false;
  for(const source of [...s.sources]){
    if(source.archived)continue;
    if(source.managementSignal?.workItemId){
      const m=source.managementSignal,current=managementSignalState(s,source),item=s.sources.find(row=>row.id===m.workItemId&&row.workItem&&active(row));
      if(!item||m.workItemBasis===current.basis)continue;
      if(!m.workItemBasis){m.workItemBasis=current.basis;changed=true;continue;}
      if(current.available&&!current.stale){
        const sourceIds=unique([m.sourceId,...source.sourceIds]).filter(id=>s.sources.some(row=>row.id===id&&caseEvidenceAvailable(s,row)));
        if(sourceIds.length)applyWorkItemFindings(s,[{existingItemId:item.id,expectedVersion:item.version,matchReason:'同一系统提示的后续依据变化',materialChange:!current.ruleSatisfied||!workItemState(s,item).closed,title:m.triage?.title||item.title,summary:current.currentSummary,nextStep:current.ruleSatisfied?'核对当前依据，确认是否可以解除本事项':m.nextStep,impact:current.ruleSatisfied?current.currentSummary:m.triage?.impact||item.workItem.impact,nature:item.workItem.nature,urgency:current.ruleSatisfied?'normal':m.triage?.urgency||item.workItem.urgency,sourceIds,association:item.workItem.association,legacyRefs:[source.id]}],at);
      }
      m.workItemBasis=current.basis;changed=true;
    }
    if(source.managementSignal&&!source.managementSignal.workItemId){
      const m=source.managementSignal,original=s.sources.find(row=>row.id===m.sourceId);
      if(!original||!caseEvidenceAvailable(s,original)||m.priority!=='attention'||m.historical)continue;
      const current=managementSignalState(s,source);if(!current.open&&!current.previous)continue;
      const linked=sourceWorkItems(s,original.id).filter(row=>row.workItem.legacyRefs.includes(source.id));
      const target=m.target,record=target?s[target.kind as V2Kind]?.find(row=>row.id===target.id):null,project=target?.kind==='projects'?target.id:record?.projectIds?.length===1?record.projectIds[0]:original.projectIds?.length===1?original.projectIds[0]:'';
      const association:WorkAssociation={kind:target?.kind==='cases'?'case':project?'project':'unknown',id:target?.kind==='cases'?target.id:project,confirmed:!!target||!!project,reason:'沿用已有事项关联'};
      const id=linked[0]?.id||'work-item-'+digest(source.id);
      if(!linked.length){applyWorkItemFindings(s,[{id,title:source.title,summary:m.summary,nextStep:m.nextStep,impact:m.triage?.impact||'',nature:m.origin==='rule'||m.triage?.kind==='risk'?'risk':'action',urgency:m.triage?.urgency||'normal',sourceIds:unique([original.id,...source.sourceIds]).filter(id=>s.sources.some(row=>row.id===id&&caseEvidenceAvailable(s,row))),association,legacyRefs:[source.id],...(target?{businessTarget:target}:{})}],at);
        const item=s.sources.find(row=>row.id===id)!,basis=workItemState(s,item).basis;
        item.workItem.history.push({at,legacySourceId:source.id,reviews:structuredClone(m.reviews||[])});
        // Transfer only a review that is valid against the original source now.
        const last=managementSignalState(s,source).review;if(last)item.workItem.reviews.push({...last,basis,legacySourceId:source.id});
        if(historical)item.workItem.notificationBaseline=basis;
      }
      m.workItemId=id;m.workItemBasis=current.basis;changed=true;
    }
    for(const signal of source.intakeBatch?.signals||[]){
      if(signal.workItemId||source.intakeBatch.revertedAt||!['risk','followup'].includes(signal.kind)&&signal.urgency!=='urgent')continue;
      const original=s.sources.find(row=>row.id===signal.sourceId);if(!original||!caseEvidenceAvailable(s,original))continue;
      const target=s.projects.find(row=>row.id===signal.targetId),id=signal.existingItemId||'work-item-'+digest([source.id,signal.id]);
      const targetKind=(['deliverables','actions','flowNodes','cases'] as const).find(kind=>s[kind].some(row=>row.id===signal.targetId));
      const parent=targetKind?s[targetKind].find(row=>row.id===signal.targetId):null,project=target?.id||(parent?.projectIds.length===1?parent.projectIds[0]:'');
      applyWorkItemFindings(s,[{id,existingItemId:signal.existingItemId||'',expectedVersion:signal.workItemVersion,matchReason:signal.matchReason,materialChange:signal.materialChange,triage:signal.triage,title:signal.title,summary:signal.reason||signal.title,nextStep:signal.question||'核对依据并安排下一步',impact:signal.reason||'',nature:signal.kind==='risk'||signal.urgency==='urgent'?'risk':'action',urgency:signal.urgency||'normal',sourceIds:[signal.sourceId],association:{kind:project?'project':'unknown',id:project,reason:'沿用资料整理结果',confirmed:!!project},legacyRefs:[source.id+':'+signal.id],...(targetKind?{businessTarget:{kind:targetKind,id:signal.targetId}}:{})}],at);
      const item=s.sources.find(row=>row.id===id)!;item.workItem.history.push({at,legacyBatchId:source.id,reviews:structuredClone(source.intakeBatch.signalReviews||[])});
      const last=riskSignalState(s,source,signal,source.intakeBatch.signals.indexOf(signal)).review;if(last)item.workItem.reviews.push({...last,basis:workItemState(s,item).basis,legacyBatchId:source.id});
      if(historical&&!signal.existingItemId)item.workItem.notificationBaseline=workItemState(s,item).basis;
      signal.workItemId=id;changed=true;
    }
  }
  return changed;
}
