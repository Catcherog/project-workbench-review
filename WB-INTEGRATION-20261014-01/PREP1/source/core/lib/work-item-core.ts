import {stableHash,type Item} from './domain';
import type {V2State} from './v2-types';
import {itemTiming} from './work-item-progress';
import {chinaDay,chinaTime,workingDay,nextWorkMorning,lastWorkdayOfWeek,type WorkCalendar} from './work-calendar';
import {observedDeliveryReview} from './feishu-facts';

export type Priority='P0'|'P1'|'P2'|'P3';
export type NeedActor='self'|'colleague'|'none';
export type CoreProof={sourceId:string;fingerprint:string;quote:string;kind?:'text'|'image';attachmentId?:string;locator?:unknown};
export type NeedAssessment={
  id:string; occurredAt:string; proof:CoreProof[]; needKey:string; description:string; actor:NeedActor;
  actualAction:boolean; substantiveProgress:boolean; executableArrangement:boolean;
  currentHandled:boolean; noIntervention:boolean; goalSatisfied:boolean; remainingActions:string[];
  priority:'P1'|'P2'|'P3'; priorityReason:string; urgent:boolean; suggestP0:boolean;
  steps:{id:string;title:string;ownerId:string;state:'needed'|'waiting'|'done';sourceIds:string[]}[];
  temporal?:{kind:'check'|'deadline';key:string;at:string};
  reassessmentKey?:string;
};
const fail=(message:string,status=422):never=>{throw Object.assign(Error(message),{status});};
export const coreDigest=(value:unknown)=>stableHash(JSON.stringify(value))+stableHash('core:'+JSON.stringify(value));
export const coreProofFingerprint=(row:Item)=>coreDigest([row.excerpt||'',[...(row.attachments||[]),...(row.intakeDocument?.images||[])].map((a:Item)=>[a.id,a.sha256]),!!row.archived,!!row.personalMessage?.deleted,!!row.caseChat?.raw?.deleted,!!row.inputEnvelope?.effectWithdrawn]);
const closed=(row:Item)=>{
  const item=row.workItem,life=item.p1?.lifecycle?.state;
  if(life)return life==='closed';
  return item.core?.admission==='withdrawn'||!item.pendingChange&&(item.handling?.state==='handled'||item.nature==='risk'&&['resolved','dismissed'].includes(item.reviews?.at(-1)?.decision));
};
export function coreState(row:Item) {
  const defaults={
    schemaVersion:1,admission:'managed',priority:{base:row.workItem.urgency==='urgent'?'P1':'P2',owner:'legacy',epoch:0,reason:'沿用已有事项，等待有来源的等级判断'},
    cycle:{id:coreDigest([row.id,'initial']),needKey:row.id,count:0,epoch:0,escalated:false,temp:null,notices:[]},
    need:{key:row.id,actor:'self',description:row.workItem.nextStep||row.workItem.summary,arranged:false},
    processedEvidence:[],history:[],checks:{},pause:null,assessment:null,
  },current=row.workItem.core;
  return current?{...defaults,...current,priority:{...defaults.priority,...current.priority},cycle:{...defaults.cycle,...current.cycle},need:{...defaults.need,...current.need},checks:{...current.checks},history:current.history||[],processedEvidence:current.processedEvidence||[]}:defaults;
}
export function ensureCore(row:Item){const value=coreState(row);if(row.workItem.core)Object.assign(row.workItem.core,value);else row.workItem.core=structuredClone(value);return row.workItem.core;}
export function effectivePriority(row:Item):Priority{
  const c=coreState(row);return c.cycle.temp&&c.cycle.temp.priorityEpoch===c.priority.epoch?c.cycle.temp.level:c.priority.base;
}
export function validCoreProofs(s:V2State,proof:CoreProof[]) {
  return Array.isArray(proof)&&proof.length>0&&proof.every(p=>{
    const row=s.sources.find(r=>r.id===p.sourceId&&!r.workItem&&!r.archived);
    return !!row&&!row.inputEnvelope?.effectWithdrawn&&!row.personalMessage?.deleted&&!row.caseChat?.raw?.deleted&&coreProofFingerprint(row)===p.fingerprint&&!!p.quote?.trim()&&(p.kind==='image'?!!p.attachmentId&&[...(row.attachments||[]),...(row.intakeDocument?.images||[])].some((a:Item)=>a.id===p.attachmentId):String(row.excerpt||'').includes(p.quote));
  });
}
/** A closed item's proposal is a review of this evidence, never permission to resume work. */
export function coreReopenProposal(s:V2State,row:Item){
  const c=coreState(row),proposal=c.reopenProposal;
  if(!proposal?.id||!Number.isFinite(Date.parse(proposal.at))||!closed(row)||!validCoreProofs(s,proposal.proof))return null;
  const decidedAt=Math.max(Date.parse(row.workItem.p1?.lifecycle?.at||'')||0,Date.parse(c.instructionAt?.lifecycle||'')||0);
  return decidedAt>Date.parse(proposal.at)?null:proposal;
}
export function reconcileCoreReopenProposal(s:V2State,row:Item,at:string,{decided=false}:{decided?:boolean}={}){
  if(!row.workItem.core?.reopenProposal)return;
  const c=ensureCore(row);
  if(c.reopenProposal&&(decided||!coreReopenProposal(s,row))){
    c.history.push({at,kind:'reopen-proposal-retired',proposal:structuredClone(c.reopenProposal),reason:decided?'本次决定已处理':'当前状态或来源不再支持待审'});
    c.reopenProposal=null;
    if(c.deferredNotification?.kind==='review')c.deferredNotification=null;
  }
}
function treatmentEvidenceKey(s:V2State,proof:CoreProof[]){
  return coreDigest(proof.map(p=>{
    let source=s.sources.find(r=>r.id===p.sourceId);const seen=new Set<string>();
    while(source?.intakeDocument?.originalSourceId&&!seen.has(source.id)){seen.add(source.id);const original=s.sources.find(r=>r.id===source!.intakeDocument.originalSourceId);if(!original)break;source=original;}
    const message=source?.personalMessage||source?.caseChat||source?.riskEvidence?.message;
    const identity=message?.messageId?[message.scope,message.accountId,message.messageId]:source?.id||p.sourceId;
    const image=p.kind==='image'?source?.attachments?.find((a:Item)=>a.id===p.attachmentId)?.sha256||source?.intakeDocument?.inputHash||p.attachmentId:null;
    // An AI paraphrase of the same pixels is not a new business event.
    return image?['image',image]:[identity,null,p.quote];
  }).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b))));
}
const cycleReset=(c:Item)=>{c.cycle.count=0;c.cycle.epoch++;};
export function applyNeedAssessment(s:V2State,row:Item,a:NeedAssessment,at:string){
  if(!a?.id||!a.needKey?.trim()||!a.description?.trim()||!Number.isFinite(Date.parse(a.occurredAt))||!validCoreProofs(s,a.proof)||!['self','colleague','none'].includes(a.actor)||!['P1','P2','P3'].includes(a.priority)||!a.priorityReason?.trim()||!Array.isArray(a.remainingActions)||!Array.isArray(a.steps))fail('推进判断缺少有效来源、当前需要或责任');
  for(const key of ['actualAction','substantiveProgress','executableArrangement','currentHandled','noIntervention','goalSatisfied','urgent','suggestP0'] as const)if(typeof a[key]!=='boolean')fail('推进判断格式无效');
  if(new Set(a.steps.map(step=>step.id)).size!==a.steps.length||a.steps.some(step=>!step.id||!step.title||!['needed','waiting','done'].includes(step.state)||step.ownerId&&!s.people.some(p=>p.id===step.ownerId&&!p.archived)||!step.sourceIds.length||step.sourceIds.some(id=>!a.proof.some(p=>p.sourceId===id))))fail('步骤缺少有效责任或依据');
  const c=ensureCore(row),evidenceKey=treatmentEvidenceKey(s,a.proof);
  if(c.assessment?.id===a.id)return false;
  // Out-of-order evidence is retained by intake, but cannot replace newer decisions.
  if(c.assessment&&!a.temporal&&a.occurredAt<(c.assessment.sourceOccurredAt||c.assessment.occurredAt)){c.history.push({at,kind:'late-assessment',id:a.id,proof:a.proof});c.checks={...c.checks,needsRecheck:true,reason:'迟到资料已保留，需结合较新事实重新核对'};return true;}
  const fresh=!c.processedEvidence.includes(evidenceKey),temporalNew=!!a.temporal?.key&&!(c.temporalKeys||[]).includes(a.temporal.key),reassessmentNew=!!a.reassessmentKey&&a.reassessmentKey!==c.reassessedKey;
  if(!fresh&&!temporalNew&&!reassessmentNew){if(c.assessment?.evidenceKey===evidenceKey)c.assessment.proof=structuredClone(a.proof);c.checks={...c.checks,lastSuccess:at,error:''};return true;}
  const newProof=a.proof.filter(p=>!(c.assessment?.proof||[]).some((old:CoreProof)=>old.sourceId===p.sourceId&&old.quote===p.quote));
  const acknowledgementOnly=newProof.length>0&&newProof.every(p=>p.kind!=='image'&&/^(?:收到|好的|好|了解|知道了|在处理|正在处理|继续待定|晚点处理|条件还不具备|暂时没有新进展|没有新进展)+$/.test(p.quote.replace(/[，。！!,.、\s]/g,'')));
  if(acknowledgementOnly&&!temporalNew&&!reassessmentNew){if(fresh)c.processedEvidence.push(evidenceKey);c.history.push({at,kind:'reply-recorded',reason:'已回复；未据此清零、停催、改级或结束',proof:a.proof});c.checks={...c.checks,lastSuccess:at,error:''};return true;}
  const wasArranged=c.need.arranged,changedNeed=c.need.key!==a.needKey;
  if(changedNeed){
    c.history.push({at,kind:'need-cycle',previous:structuredClone(c.cycle),reason:a.description,proof:a.proof});
    c.cycle={id:coreDigest([row.id,a.needKey,evidenceKey]),needKey:a.needKey,count:0,epoch:c.cycle.epoch+1,escalated:false,temp:null,notices:[]};
  }else if(wasArranged&&!a.currentHandled&&!a.noIntervention){
    c.cycle={id:coreDigest([row.id,a.needKey,evidenceKey]),needKey:a.needKey,count:0,epoch:c.cycle.epoch+1,escalated:false,temp:null,notices:[]};
  }
  const timing=itemTiming(s,row,at),hasTime=[timing.check,timing.completion,...timing.requirements].some(n=>n.state==='scheduled'&&!n.completedAt&&!n.needsReview&&(n.effectiveAt?Date.parse(n.effectiveAt)>Date.parse(at):!!n.date&&n.date>=chinaDay(at)));
  const effective=fresh&&(a.actualAction||a.substantiveProgress||a.executableArrangement);
  if(effective)cycleReset(c);
  const arranged=a.noIntervention||a.currentHandled&&hasTime;
  if(arranged)c.cycle.temp=null;
  c.need={key:a.needKey,actor:a.actor,description:a.description,arranged,remainingActions:a.remainingActions,at};
  if(c.priority.owner!=='manual'&&c.priority.base!==a.priority){c.priority={base:a.priority,owner:'auto',reason:a.priorityReason,at,epoch:c.priority.epoch+1};c.cycle.temp=null;}
  c.steps=structuredClone(a.steps);c.assessment={...structuredClone(a),evidenceKey,at};if(fresh)c.processedEvidence.push(evidenceKey);if(temporalNew)c.temporalKeys=[...(c.temporalKeys||[]),a.temporal!.key];
  if(reassessmentNew)c.reassessedKey=a.reassessmentKey;
  if(c.priority.base==='P0'&&c.fullFocus&&!a.noIntervention&&(a.substantiveProgress||changedNeed||a.urgent))c.p0Event={key:evidenceKey,at,reason:a.description};
  c.checks={...c.checks,lastSuccess:at,error:'',coverage:'已核对本次实际可读来源'};
  c.history.push({at,kind:'assessment',id:a.id,effective,arranged,proof:a.proof});
  const target=row.workItem.businessTarget?.kind==='deliverables'?s.deliverables.find(d=>d.id===row.workItem.businessTarget.id&&!d.archived):null;
  const deliverySatisfied=!row.workItem.nativeFollowup||!!target&&observedDeliveryReview(target)==='已审核'&&target.flowNodeIds?.some((id:string)=>s.flowNodes.some(n=>n.id===id&&!n.archived));
  const autoEnd=a.goalSatisfied&&a.remainingActions.length===0&&a.steps.every(step=>step.state==='done')&&!row.workItem.pendingChange&&deliverySatisfied;
  if(autoEnd&&!closed(row)){
    c.admission=c.admission==='candidate'?'withdrawn':c.admission;c.cycle.temp=null;
    row.workItem.p1||={};row.workItem.p1.lifecycle={state:'closed',owner:'auto',reason:c.admission==='withdrawn'?'已解决，无需纳入':'目标已满足，无剩余动作',at,evidenceKey};
    c.resultNotice={id:coreDigest([row.id,evidenceKey,'closed']),text:row.workItem.p1.lifecycle.reason,at};
  }else if(!autoEnd&&closed(row)&&row.workItem.p1?.lifecycle?.owner==='auto'&&fresh){
    row.workItem.p1.lifecycle={state:'open',owner:'auto',reason:'新的有效证据表明仍有后续',at,evidenceKey};
    if(c.admission==='withdrawn')c.admission='candidate';
    if(row.workItem.p1.check?.effectiveAt&&Date.parse(row.workItem.p1.check.effectiveAt)<=Date.parse(at))row.workItem.p1.check.needsReview=true;
  }else if(!autoEnd&&closed(row)&&fresh){c.reopenProposal={id:coreDigest([row.id,evidenceKey,'reopen']),reason:a.description,proof:a.proof,at};}
  reconcileCoreReopenProposal(s,row,at,{decided:autoEnd});
  return true;
}

/** The caller is the authenticated local-user path. Models/colleagues do not call this. */
export function applyCoreDecision(s:V2State,row:Item,op:Item,at:string,calendar?:WorkCalendar,eventAt=at){
  const c=ensureCore(row);
  if(op.action==='core-admit'){
    if(c.admission!=='candidate')fail('当前不是待纳入候选',409);c.admission='managed';c.admittedAt=at;
  }else if(op.action==='core-priority'){
    if(!['P0','P1','P2','P3'].includes(op.priority))fail('请选择有效优先级');
    c.priority={base:op.priority,owner:'manual',at,reason:op.reason||'本人指定',epoch:c.priority.epoch+1};c.cycle.temp=null;
    c.fullFocus=op.priority==='P0'&&op.fullFocus===true;
  }else if(op.action==='core-pause'){
    if(op.until&&(!Number.isFinite(Date.parse(op.until))||Date.parse(op.until)<=Date.parse(at)))fail('恢复时间需要在当前时间之后');
    const until=op.manualResume?'':op.until||nextWorkMorning(calendar,at);
    c.pause={at,until:until||'',manual:op.manualResume===true,needsCalendar:!op.manualResume&&!until,reason:op.reason||'本人暂停'};
    cycleReset(c);
  }else if(op.action==='core-resume'){
    c.pause=null;cycleReset(c);c.resumedAt=at;
  }else if(op.action==='core-weekly'){
    if(!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(op.time||'')||op.weekday!==undefined&&(!Number.isInteger(op.weekday)||op.weekday<1||op.weekday>7))fail('周度检查需要有效时间和星期');
    c.weekly={time:op.time,weekday:op.weekday??null,at};
  }else fail('不支持的推进操作');
  const decisionKey=({'core-admit':'admission','core-priority':'priority','core-pause':'pause','core-resume':'pause','core-weekly':'weekly'} as Record<string,string>)[op.action];
  c.instructionAt={...(c.instructionAt||{}),[decisionKey]:eventAt};c.lastInstructionAt=Object.values(c.instructionAt).sort().at(-1);
  c.history.push({at,kind:op.action,reason:op.reason||'',priority:c.priority.base,pause:c.pause});
}

export function resumeDuePause(row:Item,calendar:WorkCalendar|undefined,at:string){
  const c=ensureCore(row);if(!c.pause||c.pause.manual)return false;
  if(c.pause.needsCalendar){const until=nextWorkMorning(calendar,c.pause.at);if(!until)return false;c.pause.until=until;c.pause.needsCalendar=false;}
  if(Date.parse(c.pause.until)>Date.parse(at))return false;
  c.history.push({at,kind:'pause-resumed',pause:c.pause});c.pause=null;cycleReset(c);c.resumedAt=at;return true;
}

export function coreTemporalTrigger(s:V2State,row:Item,at:string){
  if(closed(row)||row.archived||row.workItem.disposition?.state==='ignored')return null;
  const c=coreState(row),timing=itemTiming(s,row,at),check=timing.check,checkKey=coreDigest(check);
  if(check.state==='scheduled'&&!check.completedAt&&!check.needsReview&&check.effectiveAt&&Date.parse(check.effectiveAt)<=Date.parse(at)&&!c.checkedArrangements?.includes(checkKey))return {kind:'check' as const,key:'check:'+checkKey,at};
  if(timing.completionDue.length)return {kind:'deadline' as const,key:'deadline:'+coreDigest(timing.completionDue.map(v=>[v.node.date,v.node.time,v.node.origin,v.label])),at};
  return null;
}

export function coreNotice(s:V2State,row:Item,calendar:WorkCalendar|undefined,at:string,{recovery=false}:{recovery?:boolean}={}) {
  const c=coreState(row),day=chinaDay(at),time=chinaTime(at),priority=effectivePriority(row),working=workingDay(calendar,day),timing=itemTiming(s,row,at);
  const quiet=(reason:string,extra:Record<string,unknown>={})=>({eligible:false,reason,...extra});
  if(s.workspaceType==='restored'||row.archived||row.workItem.mergedIntoId||row.workItem.disposition?.state==='ignored')return quiet('当前工作区或事项不参与自动执行');
  const check=timing.check,explicit=!closed(row)&&check.state==='scheduled'&&!check.completedAt&&!check.needsReview&&!!check.effectiveAt&&Date.parse(check.effectiveAt)<=Date.parse(at)&&!c.checkedArrangements?.includes(coreDigest(check));
  const urgent=(!!c.assessment?.urgent||c.dependencyUrgent===true)&&!closed(row),suggestP0=!closed(row)&&!!c.assessment?.suggestP0&&!c.fullFocus;
  const firstP0=suggestP0&&!c.p0NotifiedEvidence?.includes(c.assessment.evidenceKey);
  const focusChange=!closed(row)&&priority==='P0'&&c.fullFocus&&c.p0Event&&!c.p0ChangeNotified?.includes(c.p0Event.key);
  const result=closed(row)&&c.resultNotice&&!c.resultNotice.deliveredAt;
  const reopenReview=coreReopenProposal(s,row),reviewQueue=c.admission==='candidate'||row.workItem.pendingChange||reopenReview;
  if(!['action','risk','decision'].includes(row.workItem.nature)&&!row.workItem.manualAttention&&!explicit&&!reviewQueue&&!result)return quiet('背景资料保留，不生成常规催办');
  if(closed(row)&&!result&&!reopenReview)return quiet('本地事项已结束');
  if(c.pause&&!urgent&&!result)return quiet(c.pause.needsCalendar?'暂停中；恢复时间所需工作日历尚未核实':'已暂停常规提醒');
  if(!result&&!explicit&&!urgent&&!suggestP0&&!reviewQueue&&(c.need.arranged||c.need.actor!=='self'))return quiet('当前无需本人介入；继续记录对应责任步骤');
  if(!result&&!explicit&&!urgent&&!suggestP0&&!focusChange&&!reopenReview&&priority==='P0'&&c.fullFocus)return quiet('已明确全力处理，有实质变化或明确检查再通知');
  const deferred=c.deferredNotification,usableDeferred=deferred&&deferred.cycleId===c.cycle.id&&deferred.cycleEpoch===c.cycle.epoch&&deferred.priorityEpoch===c.priority.epoch;
  let slot='',kind='regular';
  if(result){slot='result:'+c.resultNotice.id;kind='result';}
  else if(reopenReview){slot=day+':09:00';kind='review';}
  else if(explicit){slot='check:'+coreDigest(check);kind='explicit';}
  else if((urgent||firstP0)&&!c.urgentNotifiedEvidence?.includes(c.assessment?.evidenceKey||c.cycle.id)){slot='urgent:'+(c.assessment?.evidenceKey||c.cycle.id);kind='urgent';}
  else if(focusChange){slot='change:'+c.p0Event.key;kind='material';}
  else if(usableDeferred){const until=deferred.until||nextWorkMorning(calendar,deferred.createdAt,chinaTime(deferred.createdAt)<'09:00');if(!until)return quiet('延期通知所需工作日历尚未核实',{calendarGap:true});if(Date.parse(until)>Date.parse(at))return quiet('普通通知等待下一实际工作时段',{deferredUntil:until});slot=deferred.slot;kind=deferred.kind;}
  else if(recovery&&priority==='P1'){slot=day+':'+(time>='14:00'?'14:00':'09:00');kind='recovery';}
  else if(reviewQueue){slot=day+':'+(suggestP0&&time>='14:00'?'14:00':'09:00');kind='review';}
  else if(priority==='P3'){
    const weekday=(new Date(day+'T12:00:00Z').getUTCDay()+6)%7+1,last=lastWorkdayOfWeek(calendar,day),scheduled=c.weekly?.weekday?weekday===c.weekly.weekday:last===day;
    if(last===null&&!c.weekly?.weekday)return quiet('本周完整工作日历尚未核实',{calendarGap:true});
    if(!scheduled||time<(c.weekly?.time||'14:00'))return quiet('尚未到本周复查时间');
    slot=day+':'+(c.weekly?.time||'14:00');
  }else if(time>='09:00')slot=day+':'+((priority==='P1'||suggestP0||priority==='P0')&&time>='14:00'?'14:00':'09:00');
  if(!slot)return quiet('尚未到合法提醒时间');
  const id=coreDigest([row.id,c.cycle.id,c.cycle.epoch,slot,...(kind==='review'&&reopenReview?[reopenReview.id]:[])]);
  if((c.deliveredSlots||[]).includes(c.cycle.id+':'+slot)||(c.deliveredSlots||[]).includes(slot)||(c.cycle.notices||[]).includes(id))return quiet('本轮已取得通知回执');
  const counts=!result&&c.admission==='managed'&&c.need.actor==='self'&&!c.need.arranged&&!closed(row)&&!['review','material'].includes(kind);
  if(!explicit&&!urgent&&!firstP0){
    if(working===null)return quiet('工作日历尚未核实',{calendarGap:true});
    if(!working||time<'09:00'||time>='18:00'){
      const until=nextWorkMorning(calendar,at,time<'09:00');
      return quiet('普通通知延至下一实际工作日 9:00',{deferredUntil:until,deferredNotification:{slot,kind,until,cycleId:c.cycle.id,cycleEpoch:c.cycle.epoch,priorityEpoch:c.priority.epoch,createdAt:deferred?.createdAt||at}});
    }
  }
  return {eligible:true,id,slot,kind,counts,cycleId:c.cycle.id,cycleEpoch:c.cycle.epoch,priorityEpoch:c.priority.epoch,priority,assessmentKey:c.assessment?.evidenceKey||c.cycle.id,checkKey:explicit?coreDigest(check):'',reopenProposalId:kind==='review'?reopenReview?.id||'':'',reason:result?c.resultNotice.text:reopenReview?'重新打开待审核：'+reopenReview.reason:c.need.description,title:row.title,at};
}

/** Called only after a verifiable successful channel receipt. Queueing is not success. */
export function countCoreNotice(row:Item,notice:Item,at:string){
  const c=ensureCore(row);c.deliveryHistory||=[];
  if(c.deliveryHistory.some((x:Item)=>x.id===notice.id))return false;
  const current=!closed(row)&&!c.pause&&notice.cycleId===c.cycle.id&&notice.cycleEpoch===c.cycle.epoch&&notice.priorityEpoch===c.priority.epoch;
  const counted=current&&notice.counts&&c.admission==='managed'&&c.need.actor==='self'&&!c.need.arranged;
  c.deliveryHistory.push({id:notice.id,slot:notice.slot,at,counted,qualified:notice.counts,cycleId:notice.cycleId,cycleEpoch:notice.cycleEpoch,priorityEpoch:notice.priorityEpoch,reason:counted?'有效提醒':'结果通知、无需介入或期间决定已变化'});
  c.deliveredSlots=[...(c.deliveredSlots||[]),notice.cycleId+':'+notice.slot];c.cycle.notices.push(notice.id);
  if(['explicit','urgent'].includes(notice.kind))c.deliveredSlots.push(notice.cycleId+':'+chinaDay(at)+':'+(['P0','P1'].includes(effectivePriority(row))&&chinaTime(at)>='14:00'?'14:00':'09:00'));
  if(c.deferredNotification?.slot===notice.slot)c.deferredNotification=null;
  if(notice.kind==='result'&&c.resultNotice?.id===notice.slot.slice(7))c.resultNotice.deliveredAt=at;
  if(notice.checkKey)c.checkedArrangements=[...(c.checkedArrangements||[]),notice.checkKey];
  if(notice.kind==='urgent'){c.urgentNotifiedEvidence=[...(c.urgentNotifiedEvidence||[]),notice.assessmentKey];c.p0NotifiedEvidence=[...(c.p0NotifiedEvidence||[]),notice.assessmentKey];}
  if(notice.kind==='material')c.p0ChangeNotified=[...(c.p0ChangeNotified||[]),notice.slot.slice('change:'.length)];
  if(counted){c.cycle.count++;if(c.cycle.count>=3&&!c.cycle.escalated){c.cycle.escalated=true;c.cycle.escalationEpoch=c.priority.epoch;const p=effectivePriority(row);if(p==='P3'||p==='P2')c.cycle.temp={level:p==='P3'?'P2':'P1',priorityEpoch:c.priority.epoch,at,reason:'同一需要第三次有效提醒'};}}
  return true;
}

/** Re-evaluate effects after a correction; never restore the whole item snapshot. */
export function invalidateCoreDerivations(s:V2State,row:Item,at:string,reason:string){
  const c=ensureCore(row);c.checks={...c.checks,needsRecheck:true,reason,recheckKey:coreDigest([row.id,reason,at])};
  if(c.assessment&&!validCoreProofs(s,c.assessment.proof)){
    c.history.push({at,kind:'assessment-invalidated',assessment:structuredClone(c.assessment),reason});
    const escalationEpoch=c.cycle.escalationEpoch??c.cycle.temp?.priorityEpoch;
    c.assessment=null;c.need.arranged=false;c.cycle.temp=null;
    const lastValid=c.history.filter((e:Item)=>e.kind==='assessment'&&e.effective&&validCoreProofs(s,e.proof)||['core-pause','core-resume','pause-resumed'].includes(e.kind)).map((e:Item)=>e.at).sort().at(-1)||'';
    const count=(c.deliveryHistory||[]).filter((n:Item)=>n.counted&&n.cycleId===c.cycle.id&&n.at>lastValid).length;
    c.cycle.count=count;c.cycle.epoch++;
    if(count>=3&&c.cycle.escalated&&escalationEpoch===c.priority.epoch&&['P2','P3'].includes(c.priority.base))c.cycle.temp={level:c.priority.base==='P3'?'P2':'P1',priorityEpoch:c.priority.epoch,at,reason:'按仍有效的发送事实复核临时催办等级'};
  }
  for(const source of s.sources)if(source.reminderRun?.core&&source.reminderRun.items.some((i:Item)=>i.workItemId===row.id)){
    for(const item of source.reminderRun.items.filter((i:Item)=>i.workItemId===row.id))item.needsRecheck=true;
  }
  c.history.push({at,kind:'correction-recheck',reason});
  reconcileCoreReopenProposal(s,row,at);
}
