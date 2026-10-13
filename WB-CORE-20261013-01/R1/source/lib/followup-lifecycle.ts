import {deliveryRecorded} from './feishu-facts';
import type {Item} from './domain';
import type {V2Kind, V2State} from './v2-types';
import {getProjectGates, gateDate} from './project-gates';
import {feedbackTime, feedbackRelated, isCommentFeedback} from './comment-feedback';
import {caseEvidenceAvailable} from './case-evidence';
import {materialSourceIdentityKey, intakeProgressField} from './material-intake';
import {intakeSignalMatches,isRiskSignal,riskSignalState} from './risk-signals';
import {workItemFollowup,workItemOwnsFeedback,workItemState,applyWorkItemOperation} from './work-items';

export type FollowupRef = {kind:V2Kind; targetId:string};
export type HandlingState = 'attention'|'waiting'|'in_progress'|'handled';
export type FollowupSource = {id:string; version:number; fingerprint:string; available:boolean; eventAt:string; title:string};
export type FollowupProjection = FollowupRef & {
  itemKey:string; title:string; projectIds:string[]; caseId?:string; handlingState:HandlingState;
  urgent:boolean; reason:string; reasons:string[]; waitingReason:string; nextCheckAt:string;
  primaryAction:'review_feedback'|'prepare_reminder'|'clarify'|'review_result'|'reconcile'|'inspect';
  feedbackState:'none'|'clear'|'vague'|'conflict'|'stale'; clarification:string;
  reminderEligible:boolean; notificationBasis:string; basis:string; evidenceBasis:string;
  suppressNotification?:boolean;
  feedbackBasis:string; gateBasis:string; sources:FollowupSource[]; pendingReply:boolean;
  executionSourceIds:string[]; active:boolean;
  businessStates:{feedback:string; submission:string; professionalReview:string; acceptance:string; node:string; syncApproval:string};
};
export type FollowupOperation = FollowupRef & {workspaceId:string; requestId:string; expectedBasis:string;
  action:'take_over'|'review_feedback'|'reschedule'; nextCheckAt?:string; reason?:string};
const text=(v:unknown):string=>typeof v==='string'?v.trim():'';
const ids=(v:unknown):string[]=>Array.isArray(v)?v.filter(x=>typeof x==='string'):[];
const canonical=(v:unknown):string=>JSON.stringify(v,(_k,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,x[k]])):x);
/** Display/concurrency fingerprint; outbound approvals additionally use SHA-256. */
export function followupFingerprint(value:unknown):string {
  const input=canonical(value);let a=2166136261,b=5381;
  for(let i=0;i<input.length;i++){a=Math.imul(a^input.charCodeAt(i),16777619);b=Math.imul(b,33)^input.charCodeAt(i);}
  return (a>>>0).toString(36)+'-'+(b>>>0).toString(36);
}
export const followupItemKey=(workspaceId:string,ref:FollowupRef)=>[workspaceId,ref.kind,ref.targetId].map(encodeURIComponent).join(':');
export const followupDay=(now=Date.now())=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(now));
const dayTime=(day:unknown)=>gateDate(day)?Date.parse(day+'T09:00:00+08:00'):NaN;
function fail(message:string,status=409):never{throw Object.assign(new Error(message),{status});}
const accepted=(r:Item)=>deliveryRecorded(r)||['已验收','通过','验收通过','已通过'].includes(r.acceptanceStatus);
function closed(r:Item,kind:V2Kind){return r.archived||r.mergedIntoId||['已关闭','已解除','已取消'].includes(r.status)||(['deliverables','actions','milestones'].includes(kind)&&accepted(r));}
/** Only an explicit, unambiguous relation canonicalizes a Tasks action. */
export function canonicalFollowupRef(s:V2State,ref:FollowupRef):FollowupRef {
  const clean={kind:ref.kind,targetId:ref.targetId};
  if(ref.kind!=='actions')return clean;
  const a=s.actions.find(r=>r.id===ref.targetId&&!r.archived);
  const matches=a?s.deliverables.filter(d=>!d.archived&&(ids(a.outputIds).includes(d.id)||ids(d.actionIds).includes(a.id))&&(d.projectIds.some(id=>a.projectIds.includes(id))||!!d.caseId&&d.caseId===a.caseId)):[];
  return matches.length===1?{kind:'deliverables',targetId:matches[0].id}:clean;
}
const relatedActions=(s:V2State,ref:FollowupRef)=>ref.kind==='deliverables'?s.actions.filter(a=>!a.archived&&canonicalFollowupRef(s,{kind:'actions',targetId:a.id}).targetId===ref.targetId):[];
function sourceRef(s:V2State,sourceId:string):FollowupSource {
  const src=s.sources.find(r=>r.id===sourceId);
  const available=!!src&&caseEvidenceAvailable(s,src)&&!s.sources.some(r=>!r.archived&&r.confirmed&&r.supersedesId===sourceId);
  return {id:sourceId,version:src?.version||0,title:src?.title||'来源不可用',available,
    fingerprint:src?followupFingerprint([materialSourceIdentityKey(s,src),available]):'missing',
    eventAt:feedbackTime(src?.feedback?.eventAt||src?.occurredAt)};
}

/** Pure, clock-injected decision. Reads the existing workspace and evidence only. */
export function buildFollowup(s:V2State,input:FollowupRef,now=Date.now()):FollowupProjection {
  if(!Number.isFinite(now))fail('当前时钟无效',422);
  const ref=canonicalFollowupRef(s,input),row=s[ref.kind]?.find(r=>r.id===ref.targetId);
  if(!row)fail('待处理对象不存在',404);
  if(row.workItem)return workItemFollowup(s,row,now);
  const related=relatedActions(s,ref),targetIds=[row.id,...related.map(r=>r.id)],itemKey=followupItemKey(s.workspaceId,ref);
  const meta=row.followupHandling?.workspaceId===s.workspaceId?row.followupHandling:{};
  const today=followupDay(now),projectIds=ref.kind==='projects'?[row.id]:row.projectIds;
  const gates=projectIds.map(id=>s.projects.find(p=>p.id===id&&!p.archived)).filter((p):p is Item=>!!p).map(p=>({projectId:p.id,...getProjectGates(s,p).next}));
  const gateBasis=followupFingerprint(gates),gateDates=gates.map(g=>g.date).filter((d):d is string=>!!d).sort();
  const relevant=(value:any)=>!value.workItemId&&(['risk','followup','clarify'].includes(value.kind)?intakeSignalMatches(s,value,ref.kind,targetIds):targetIds.includes(value.targetId)&&(!value.kind||value.kind===ref.kind||value.kind==='actions'&&related.some(a=>a.id===value.targetId)));
  const comments=['actions','deliverables'].includes(ref.kind)?s.sources.filter(src=>isCommentFeedback(src)&&!workItemOwnsFeedback(s,src.id)&&(feedbackRelated(s,src,row)||related.some(a=>feedbackRelated(s,src,a)))&&!src.feedback.observationOnly):[];
  const batches=s.sources.filter(src=>src.intakeBatch&&[...(src.intakeBatch.autoUpdates||[]),...(src.intakeBatch.evidenceRefresh||[]),...(src.intakeBatch.pending||[]),...(src.intakeBatch.signals||[])].some(relevant));
  const provenance=row.intakeFeedback,batch=s.sources.find(src=>src.id===provenance?.batchId),job=batch?.intakeBatch;
  const batchRefs=batches.flatMap(src=>[...(src.intakeBatch.autoUpdates||[]),...(src.intakeBatch.evidenceRefresh||[]),...(src.intakeBatch.pending||[]),...(src.intakeBatch.signals||[])].filter(relevant).flatMap((v:any)=>[v.sourceId,...(v.supportingSources||[]).map((r:any)=>r.sourceId)])).filter(Boolean) as string[];
  const refs=[...new Set([...ids(row.sourceIds),...comments.map(src=>src.id),...batchRefs,...(provenance?.sourceId?[provenance.sourceId]:[])])].sort().map(id=>sourceRef(s,id));
  const sourceKeys=refs.map(r=>[r.id,r.fingerprint,r.available]);
  const feedbackBasis=followupFingerprint([sourceKeys,batches.map(b=>[b.id,!!b.archived,!!b.intakeBatch.revertedAt,(b.intakeBatch.pending||[]).filter(relevant),(b.intakeBatch.signals||[]).filter(relevant)]),provenance]);
  const signals=batches.filter(b=>!b.archived&&!b.intakeBatch.revertedAt).flatMap(b=>(b.intakeBatch.signals||[]).filter((v:Item,index:number)=>relevant(v)&&(!isRiskSignal(v)||riskSignalState(s,b,v,index).open)).filter((v:any)=>!v.sourceId||refs.some(r=>r.id===v.sourceId&&r.available)));
  const pending=batches.filter(b=>!b.archived&&!b.intakeBatch.revertedAt).flatMap(b=>(b.intakeBatch.pending||[]).filter(relevant).filter((v:any)=>!v.sourceId||refs.some(r=>r.id===v.sourceId&&r.available)));
  const urgentSignals=signals.filter((v:any)=>v.urgency==='urgent');
  const unverifiedUrgent=batches.some(batch=>(batch.intakeBatch.signals||[]).some((signal:Item,index:number)=>urgentSignals.includes(signal)&&riskSignalState(s,batch,signal,index).needsVerification));
  const parentCase=row.caseId?s.cases.find(c=>c.id===row.caseId):undefined;
  const certain=(r:Item)=>r.confirmed!==false&&!r.stale&&!['suggestion','hypothesis'].includes(r.classification||r.draftClassification);
  const urgent=certain(row)&&(row.status==='需要升级协调'||ref.kind==='risks'&&row.confirmed===true&&row.impact==='高'||ref.kind==='decisions'&&row.confirmed===true&&!!gateDate(row.deadline)&&row.deadline<=today||related.some(a=>certain(a)&&a.status==='需要升级协调'))||urgentSignals.length>0;
  const matchesItem=(i:any)=>{const kind=i.kind||(s.deliverables.some(d=>d.id===i.targetId)?'deliverables':'actions');return kind===ref.kind&&i.targetId===row.id||kind==='actions'&&related.some(a=>a.id===i.targetId);};
  // Core collaboration is projected on the stable work item, with per-operation
  // ownership and necessity. It must not become a second legacy waiting cycle.
  const runs=s.sources.filter(src=>!src.reminderRun?.core&&src.reminderRun?.workspaceId===s.workspaceId&&src.reminderRun.items.some(matchesItem));
  const unknown=runs.filter(src=>src.reminderRun.items.some((i:any)=>matchesItem(i)&&i.createTask&&['sending','sent'].includes(i.taskStage))||src.reminderRun.messages.some((m:any)=>['sending','sent'].includes(m.stage))||['partial','needs_reconcile','sending'].includes(src.reminderRun.status)&&(src.reminderRun.items.some((i:any)=>i.createTask&&i.taskStage==='readback_verified')||src.reminderRun.messages.some((m:any)=>m.stage==='readback_verified')));
  const sent=runs.flatMap(src=>src.reminderRun.items.filter(matchesItem).flatMap((i:any)=>{
    const messages=src.reminderRun.messages.filter((m:any)=>i.recipientIds.includes(m.recipientId));
    if(!messages.length||!messages.every((m:any)=>m.stage==='readback_verified'))return [];
    const at=feedbackTime(messages.map((m:any)=>m.sentAt||m.sendAttemptedAt||src.reminderRun.approvedAt||m.readAt).filter(Boolean).sort().at(-1)||src.reminderRun.finishedAt);
    return at?[{sourceId:src.id,at,context:i.followupContext}]:[];
  })).sort((a,b)=>Date.parse(b.at)-Date.parse(a.at))[0];
  const sourceChanged=!!sent?.context&&canonical(sent.context.sources)!==canonical(sourceKeys);
  const gateChanged=!!sent?.context&&sent.context.gateBasis!==gateBasis;
  const latestComment=comments.filter(src=>!src.archived&&!src.feedback.deleted).slice().sort((a,b)=>Date.parse(b.feedback.eventAt||0)-Date.parse(a.feedback.eventAt||0))[0];
  const awaitingReply=!!sent||!!meta.schedule||!!meta.pickedUpAt||!!row.followUp||!!row.checkAt||row.status==='等待他人反馈';
  const responseAfterSend=comments.some(src=>!src.archived&&!src.feedback.deleted&&(sent?!!feedbackTime(src.feedback.eventAt)&&Date.parse(src.feedback.eventAt)>Date.parse(sent.at):awaitingReply||src.feedback.analysis?.viewerAction===true||src.feedback.analysis?.kind==='needs_confirmation'));
  const feedbackReviewed=meta.reviewedFeedbackBasis===feedbackBasis||(comments.length>0||!!job)&&(!provenance||!!job?.reviewedAt)&&comments.every(src=>src.feedback.reviewedVersion===src.feedback.contentVersion);
  const pendingReply=!feedbackReviewed&&(sourceChanged||responseAfterSend||awaitingReply&&!!provenance&&(!sent||!!feedbackTime(provenance.occurredAt)&&Date.parse(provenance.occurredAt)>Date.parse(sent.at)));
  const replaced=(id:string)=>{const old=s.sources.find(src=>src.id===id),origin=old?.intakeDocument?.originalSourceId;return !!origin&&refs.some(r=>r.id!==id&&r.available&&s.sources.find(src=>src.id===r.id)?.intakeDocument?.originalSourceId===origin);};
  const unavailable=refs.some(r=>!r.available&&!replaced(r.id)),reverted=!!provenance&&(!job||batch?.archived||job.revertedAt||provenance.state==='该批更新已撤回');
  const conflict=pending.length>0||signals.some((v:any)=>v.kind==='clarify')||latestComment?.feedback.analysis?.uncertainties?.length>0;
  const source=refs.find(r=>r.id===provenance?.sourceId),occurred=feedbackTime(provenance?.occurredAt||source?.eventAt),origin=s.sources.find(src=>src.id===source?.id);
  const progress=text(row[intakeProgressField(ref.kind)]),forecast=gateDate(row.forecast);
  const trusted=!!source?.available&&!!job&&!reverted&&['ready','partial'].includes(job.status)&&[...(job.autoUpdates||[]),...(job.evidenceRefresh||[])].some((u:any)=>u.targetId===row.id&&u.sourceId===source.id)&&origin?.intakeDocument?.complete!==false&&!!text(provenance?.quote)&&text(origin?.excerpt).includes(provenance.quote);
  const predatesRequest=!!sent&&!!occurred&&Date.parse(occurred)<=Date.parse(sent.at);
  const old=predatesRequest&&(sourceChanged||!!feedbackTime(provenance?.at)&&Date.parse(provenance.at)>Date.parse(sent!.at));
  const stale=unavailable||reverted||old||!!occurred&&Date.parse(occurred)>now;
  const gateConcern=signals.some((v:any)=>v.kind==='risk')||[row,...related].some(r=>text(r.blocker)&&!['无','暂无','已解除'].includes(text(r.blocker)));
  const clear=trusted&&!stale&&!predatesRequest&&!conflict&&!gateConcern&&!!occurred&&!!progress&&!/^(正在|在)?(处理|跟进|推进|进行中)[。！! ]*$/.test(progress)&&!!forecast&&forecast>today&&gateDates.length===gates.length&&gates.length>0&&forecast<gateDates[0]&&(!latestComment||Date.parse(latestComment.feedback.eventAt)<=Date.parse(occurred));
  const historicalOnly=!!sent&&!sourceChanged&&!responseAfterSend&&(!provenance||predatesRequest);
  const feedbackState=stale?'stale':conflict?'conflict':clear?'clear':historicalOnly?'none':comments.length||provenance?'vague':'none';
  const gaps=[...new Set(pending.map((p:any)=>p.reason).concat(signals.filter((v:any)=>v.kind==='clarify'||v.kind==='followup').map((v:any)=>v.question)).filter(Boolean))] as string[];
  const clarification=feedbackState==='vague'||feedbackState==='conflict'?(gaps.join('；')||`请补充「${row.title}」的具体进展、整项预计完成时间、当前阻碍及成果入口。`):'';
  const result=s.sources.filter(src=>!src.archived&&src.resultReview?.deliverableId===row.id).slice().sort((a,b)=>text(b.collectedAt).localeCompare(text(a.collectedAt)))[0];
  const needsAcceptance=false;
  const formalDates=[row.checkAt,row.dueAt,row.plannedEnd,row.committed,row.deadline,...gateDates].filter(v=>gateDate(v)).sort();
  const evidenceBasis=followupFingerprint([ref,row.title,row.owner,row.ownerId,projectIds,row.caseId,row.status,row.blocker,row.followUp,row.nextAction,row.forecast,progress,row.submissionStatus,row.acceptanceStatus,row.deliveryReview,formalDates,sourceKeys,gateBasis,feedbackBasis,signals,related.map(a=>[a.id,a.status,a.blocker]),parentCase&&[parentCase.status,parentCase.myRole],result?.resultReview?.status]);
  let nextCheckAt='';
  if(clear)nextCheckAt=new Date(Math.min(dayTime(forecast),dayTime(gateDates[0]))).toISOString();
  else if(sent){const futureDates=formalDates.map(dayTime).filter(n=>n>Date.parse(sent.at));nextCheckAt=new Date(Math.min(Date.parse(sent.at)+86400000,...futureDates)).toISOString();}
  let scheduleCapped=false;
  if(meta.schedule?.evidenceBasis===evidenceBasis){
    // A handling-time adjustment does not move a formal due date or gate.
    const anchor=Date.parse(sent?.at||meta.schedule.createdAt||meta.schedule.at),limits=[row.dueAt,row.plannedEnd,row.committed,row.deadline,...gateDates].map(dayTime).filter(n=>n>anchor);
    const effective=Math.min(Date.parse(meta.schedule.at),...limits);nextCheckAt=new Date(effective).toISOString();scheduleCapped=effective<Date.parse(meta.schedule.at);
  }
  const due=!!nextCheckAt&&Date.parse(nextCheckAt)<=now;
  const formalChanged=!!sent?.context&&sent.context.formalDates!==followupFingerprint(formalDates);
  const reasons:string[]=[];
  if(unknown.length)reasons.push('外部执行结果待核对；先回读原批次');
  if(urgent)reasons.push(urgentSignals.length?unverifiedUrgent?'有依据的重大疑点待核实，可能影响关口':'已核实风险尚未解除，仍需跟进':'紧急问题尚未解除');
  if(pendingReply)reasons.push('已有相关反馈或来源变化，待你核对');
  if(stale)reasons.push(unavailable||reverted?'所据反馈已更正、撤回或不可用':'反馈时间过早、过期或不可靠，不能覆盖当前跟进');
  if(conflict)reasons.push('反馈存在冲突或信息缺口，需核对');
  if(gateConcern&&!urgent)reasons.push('仍有风险或阻碍依据，关口影响待核对');
  const clarificationNeeded=feedbackState==='vague'&&(responseAfterSend||sourceChanged||!sent&&comments.length>0);
  if(clarificationNeeded)reasons.push('反馈信息尚不完整，补问草稿待审核');
  if(gateChanged||formalChanged)reasons.push('关口或正式日期已变化，需重新核对跟进安排');
  if(due)reasons.push('已到下次跟进时间');
  if(scheduleCapped)reasons.push('人工跟进时间晚于正式期限，仍按较早期限返回复核');
  if(needsAcceptance)reasons.push('成果已提交，待人工核对验收');
  const done=closed(row,ref.kind)&&!needsAcceptance;
  let handlingState:HandlingState=done?'handled':urgent&&meta.pickedUpAt?'in_progress':'attention';
  const safeWait=!urgent&&!unknown.length&&!pendingReply&&!stale&&!conflict&&!gateConcern&&(!clarificationNeeded||meta.schedule?.evidenceBasis===evidenceBasis)&&!gateChanged&&!formalChanged&&!needsAcceptance&&!due;
  if(!done&&safeWait&&!!nextCheckAt&&(!!sent||clear||!!meta.schedule))handlingState='waiting';
  const waitingReason=clear?'已有明确反馈，暂缓重复催办':sent?'已催办，等待外部反馈':meta.schedule?'按人工调整时间跟进':'';
  if(handlingState==='waiting')reasons.unshift(waitingReason);
  const reminderEligible=!done&&!unknown.length&&!needsAcceptance&&!stale&&!conflict&&handlingState!=='waiting'&&(!clear||due||gateChanged||formalChanged||urgent);
  const notificationBasis=followupFingerprint([row.status,row.impact,row.blocker,related.filter(a=>a.status==='需要升级协调').map(a=>[a.id,a.status,a.blocker]),urgentSignals.map((v:any)=>[v.sourceId,refs.find(r=>r.id===v.sourceId)?.fingerprint,v.kind,v.title,v.reason]),gateBasis]);
  const eligible=reminderEligible&&(!clear||due||gateChanged||formalChanged||urgent)&&!(urgent&&!!sent&&sent.context?.notificationBasis===notificationBasis);
  const active=!done&&!row.taskObservationOnly&&(!parentCase||!parentCase.archived&&parentCase.status!=='已关闭'&&parentCase.myRole!=='关注');
  return {...ref,itemKey,title:row.title,projectIds,caseId:ref.kind==='cases'?row.id:row.caseId,handlingState,urgent:active&&urgent,reason:reasons[0]||'核对当前进展与下一步',reasons,waitingReason,nextCheckAt,
    primaryAction:unknown.length?'reconcile':needsAcceptance?'review_result':pendingReply||stale||conflict?'review_feedback':clarification?'clarify':'prepare_reminder',feedbackState,clarification,reminderEligible:active&&eligible,notificationBasis,
    basis:followupFingerprint([evidenceBasis,meta,sent,unknown.map(x=>[x.id,x.reminderRun.status]),handlingState,nextCheckAt,due]),evidenceBasis,feedbackBasis,gateBasis,sources:refs,pendingReply,executionSourceIds:unknown.map(x=>x.id),active,
    businessStates:{feedback:progress||text(row.executionStatus),submission:text(row.submissionStatus),professionalReview:text(row.deliveryReview||row.reviewStatus),acceptance:text(row.acceptanceStatus),node:text(row.nodeStatus),syncApproval:'独立审核，处理状态不授予同步批准'}};
}

export function followupContext(p:FollowupProjection,s:V2State){
  const row=s[p.kind].find(r=>r.id===p.targetId)!;
  const gates=p.projectIds.map(id=>s.projects.find(r=>r.id===id)).filter((p):p is Item=>!!p).map(p=>getProjectGates(s,p).next?.date).filter(Boolean);
  return {sources:p.sources.map(r=>[r.id,r.fingerprint,r.available]),gateBasis:p.gateBasis,notificationBasis:p.notificationBasis,formalDates:followupFingerprint([row.checkAt,row.dueAt,row.plannedEnd,row.committed,row.deadline,...gates].filter(v=>gateDate(v)).sort())};
}

/** Handling metadata only. No feedback, acceptance, node or sync status is changed. */
export function applyFollowupOperation(input:V2State,op:FollowupOperation,now=Date.now()):V2State {
  if(op.workspaceId!==input.workspaceId)fail('工作区不匹配');
  if(!op.requestId||op.requestId.length>160||!['take_over','review_feedback','reschedule'].includes(op.action))fail('处理操作或请求标识无效',422);
  const key='followup:'+input.workspaceId+':'+op.requestId,fingerprint=canonical(op),receipt=input.receipts[key];
  if(receipt){if(receipt.fingerprint!==fingerprint)fail('同一请求标识不能改变操作内容');return input;}
  const p=buildFollowup(input,op,now);if(p.basis!==op.expectedBasis)fail('事项、依据或跟进安排已变化，请刷新后再操作');
  if(!p.active)fail('此事项已不在当前处理范围');
  const topic=input.sources.find(row=>row.id===p.targetId&&row.workItem);
  if(p.kind==='sources'&&topic){
    const next=applyWorkItemOperation(input,{workspaceId:input.workspaceId,sourceId:topic.id,expectedVersion:topic.version,expectedBasis:workItemState(input,topic,now).basis,requestId:'followup-'+followupFingerprint(op),action:op.action==='reschedule'?'wait':op.action==='review_feedback'?'resume':'take_over',reason:op.reason||'',nextCheckAt:op.nextCheckAt||''},new Date(now).toISOString());
    next.receipts[key]={fingerprint,result:{itemKey:p.itemKey,action:op.action}};return next;
  }
  const next=structuredClone(input),row=next[p.kind].find(r=>r.id===p.targetId)!;
  const before=row.followupHandling||null,meta=before?.workspaceId===next.workspaceId?{...before}:{schemaVersion:1,workspaceId:next.workspaceId};
  if(op.action==='take_over')meta.pickedUpAt=new Date(now).toISOString();
  if(op.action==='review_feedback'){
    meta.reviewedFeedbackBasis=p.feedbackBasis;
    for(const proof of p.sources){
      const source=next.sources.find(src=>src.id===proof.id);if(!source||!isCommentFeedback(source))continue;
      const origin=canonicalFollowupRef(next,{kind:source.feedback.channel==='meegle-deliverable-comment'?'deliverables':'actions',targetId:source.feedback.targetId});
      if(origin.kind!==p.kind||origin.targetId!==p.targetId)continue;
      source.feedback.reviewedVersion=source.feedback.contentVersion;source.feedback.reviewedAt=new Date(now).toISOString();source.version=(source.version||1)+1;
    }
  }
  if(op.action==='reschedule'){
    const at=feedbackTime(op.nextCheckAt);if(!at||!gateDate(op.nextCheckAt?.slice(0,10))||Date.parse(at)<=now||!text(op.reason)||text(op.reason).length>600)fail('请填写含时区的未来跟进时间和调整理由',422);
    meta.schedule={at,reason:text(op.reason),evidenceBasis:p.evidenceBasis,createdAt:new Date(now).toISOString()};
  }
  meta.version=(meta.version||0)+1;row.followupHandling=meta;row.version=(row.version||1)+1;
  next.revision++;next.receipts[key]={fingerprint,result:{itemKey:p.itemKey,action:op.action}};
  next.audit.push({id:key,time:new Date(now).toISOString(),operation:'followup.'+op.action,objectId:row.id,actor:'本人',before,after:meta,revision:next.revision});
  return next;
}
