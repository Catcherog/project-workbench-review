import {assertSnapshot, asArray, clone, currentFacts, hash, nonempty, snapshotBasis, unique, valueText} from './model.mjs';
import {buildContinuity} from './continuity.mjs';

const budgets={plan:2,progress:2,blocker:1,todo:2};
const priorityRank={P0:0,P1:1,P2:2,P3:3,P4:4};
const label={plan:'计划',progress:'进展',blocker:'卡点',todo:'我的待办'};
function newest(f){return Math.max(0,...asArray(f.sourceRefs).map(e=>Date.parse(e.occurredAt??e.receivedAt??'')||0));}
function certainty(f){return f.sourceReviewVerified?'source_reviewed':f.authority==='owner_confirmed'?'owner_confirmed':f.assertionType==='forecast'?'forecast':f.authority==='unconfirmed'?'reported':'source_confirmed';}
function entryFromFact(f){
  let text=f.text||valueText(f.value);
  if(f.assertionType==='forecast'||f.field==='forecast')text='当前预测：'+text;
  else if(f.sourceReviewVerified)text='源头已审核：'+text;
  else if(f.authority==='unconfirmed')text='反馈：'+text;
  if(nonempty(f.date)&&!text.includes(f.date))text+=' · '+f.date;
  if(f.requiresRevalidation)text+='（原依据已变化，待重新核实）';
  else if(f.stale)text+='（资料待更新）';
  if(f.status==='conflict'&&f.displaySelected)text+='（已选择此来源展示，原来源差异仍保留）';
  return {id:f.id,itemId:f.itemId??null,text,date:f.date??null,certainty:certainty(f),
    ...(f.retentionBoundExcerpt===true?{retentionBoundExcerpt:true,rawExcerptUnavailable:f.rawExcerptUnavailable===true}:{}),
    critical:f.critical===true||f.requiresRevalidation===true,sourceRefs:clone(asArray(f.sourceRefs)),_time:newest(f),_protected:f.protected===true};
}
function dedupeEntries(entries){
  const map=new Map();
  for(const e of entries){
    const key=hash([e.itemId,e.text,e.certainty]);const old=map.get(key);
    if(old){old.sourceRefs=[...new Map([...old.sourceRefs,...e.sourceRefs].map(s=>[hash(s),s])).values()];old.critical ||= e.critical;}
    else map.set(key,e);
  }
  return [...map.values()];
}
function row(key,entries,fallback,severity='normal'){
  const sorted=dedupeEntries(entries).sort((a,b)=>Number(b.critical)-Number(a.critical)||Number(b._pin)-Number(a._pin)||Number(b._protected)-Number(a._protected)||(b._time??0)-(a._time??0)||a.id.localeCompare(b.id));
  const pinned=sorted.filter(e=>e.critical||e._pin), ordinary=sorted.filter(e=>!e.critical&&!e._pin);
  const visible=[...pinned,...ordinary.slice(0,Math.max(0,budgets[key]-pinned.length))];
  const hidden=ordinary.slice(Math.max(0,budgets[key]-pinned.length));
  const publicEntry=e=>{const{_time,_protected,_pin,...rest}=e;return rest;};
  return {key,label:label[key],text:visible.length?visible.map(e=>e.text).join('；'):fallback,
    entries:visible.map(publicEntry),moreEntries:hidden.map(publicEntry),
    severity:sorted.some(e=>e.critical)?'critical':severity};
}

export function buildProjectSummary(snapshot,projectId){
  assertSnapshot(snapshot);
  const project=snapshot.projects.find(p=>p.id===projectId);
  if(!project)throw Object.assign(new Error('project_not_found'),{code:'project_not_found'});
  const facts=currentFacts(snapshot,projectId),items=snapshot.items.filter(i=>i.projectId===projectId);
  const effective=facts.filter(f=>f.status!=='candidate'&&(f.status!=='conflict'||f.displaySelected||f.protected||f.authority==='owner_confirmed')&&f.assertionType!=='proposal'&&nonempty(f.text||valueText(f.value)));
  const plan=effective.filter(f=>f.field==='plan'&&f.authority!=='unconfirmed').map(entryFromFact);
  const forecast=effective.filter(f=>f.field==='forecast'||f.assertionType==='forecast').map(entryFromFact);
  if(forecast.length){plan.forEach(e=>e._pin=true);forecast.forEach(e=>e._pin=true);plan.push(...forecast);}
  if(project.stage)plan.unshift({id:'stage:'+project.id,itemId:null,text:'当前阶段：'+project.stage,date:null,certainty:'source_confirmed',critical:false,sourceRefs:[],_time:Infinity});
  const progress=effective.filter(f=>['progress','execution','delivery','review'].includes(f.field)).map(entryFromFact);
  const blockers=effective.filter(f=>['blocker','risk'].includes(f.field)).map(entryFromFact);
  const activeFact=f=>!f.itemId||!items.some(i=>i.id===f.itemId&&['closed','cancelled'].includes(i.businessState));
  const actions=effective.filter(f=>f.field==='action'&&f.actorId===snapshot.viewerId&&f.actionState!=='done'&&activeFact(f)).map(entryFromFact);
  const factItemIds=new Set(actions.map(a=>a.itemId).filter(Boolean));
  for(const item of items){
    if(item.requiresViewerAction===true&&!['closed','cancelled'].includes(item.businessState)&&!factItemIds.has(item.id))actions.push({
      id:'action:'+item.id,itemId:item.id,text:(item.actionText||item.title)+(item.dueAt&&!(item.actionText||item.title).includes(item.dueAt)?' · '+({check:'检查',requirement:'要求',commitment:'承诺',estimate:'预测'}[item.deadlineKind]||'时间')+'：'+item.dueAt:''),date:item.dueAt??null,
      certainty:'registered_action',critical:item.priority==='P0',sourceRefs:[],_time:0});
    const blocker=item.view?.fields?.blocker;
    if(nonempty(blocker)&&!['closed','cancelled'].includes(item.businessState)&&!blockers.some(e=>e.itemId===item.id))blockers.push({
      id:'blocker:'+item.id,itemId:item.id,text:blocker+(asArray(item.view.stale_fields).includes('blocker')?'（资料待更新）':''),
      date:null,certainty:'reported',critical:item.priority==='P0',sourceRefs:[],_time:0});
  }
  const coverage=clone(snapshot.projectCoverage?.[projectId]??snapshot.coverage??{status:'unavailable',checkedAt:null,reasons:[]});
  const pending=snapshot.reviews.filter(r=>r.status==='pending'&&r.projectId===projectId);
  const conflict= facts.filter(f=>f.status==='conflict');
  if(conflict.length)blockers.push({id:'conflict:'+projectId,itemId:null,text:'关键信息存在来源冲突，待核实后再决定下一步',date:null,
    certainty:'conflict',critical:conflict.some(f=>f.critical),sourceRefs:conflict.flatMap(f=>f.sourceRefs),_time:Infinity});
  let progressFallback='暂无可用的进展记录';
  if(project.status==='paused')progressFallback='项目已暂停；原计划和待处理事项保留';
  if(project.status==='closed')progressFallback='项目状态为已结项；结项依据与历史保留';
  if(project.status==='paused'||project.status==='closed')progress.unshift({
    id:'lifecycle:'+projectId,itemId:null,text:project.status==='paused'?'项目已暂停':'项目状态为已结项',date:null,
    certainty:'source_confirmed',critical:false,sourceRefs:[],_time:Infinity,_pin:true});
  const rows=[
    row('plan',plan,'正式计划或关键日期尚未明确',plan.length?'normal':'unknown'),
    row('progress',progress,progressFallback,progress.length?'normal':'unknown'),
    row('blocker',blockers,coverage.status==='complete'?'暂无已知卡点':'资料尚未完整核实，当前卡点信息可能不完整',blockers.length?'attention':coverage.status==='complete'?'normal':'unknown'),
    row('todo',actions,'当前没有已明确需要你处理的动作',actions.length?'attention':'normal'),
  ];
  return {project:clone(project),basis:snapshotBasis(snapshot,projectId),generatedAt:snapshot.generatedAt,coverage,rows,
    reviewCount:pending.length,reminders:clone(snapshot.reminders.filter(r=>r.projectId===projectId&&!['closed','cancelled'].includes(r.businessState))),
    details:{facts:clone(snapshot.facts.filter(f=>f.projectId===projectId)),items:clone(items),
      processingGaps:clone(coverage.processingGaps??[])}};
}

export function buildBootstrap(snapshot){
  assertSnapshot(snapshot);
  const reviews=snapshot.reviews.filter(r=>r.status==='pending');
  const projects=snapshot.projects.map(project=>{
    const items=snapshot.items.filter(i=>i.projectId===project.id);
    return {...clone(project),needsAttention:items.some(i=>!['closed','cancelled'].includes(i.businessState)&&(i.requiresViewerAction||i.priority==='P0'))
      ||snapshot.reminders.some(r=>r.projectId===project.id&&!['closed','cancelled'].includes(r.businessState)&&r.displayState!=='snoozed'),
      reviewCount:reviews.filter(r=>r.projectId===project.id).length};
  });
  return {schemaVersion:1,workspaceId:snapshot.workspaceId,viewerId:snapshot.viewerId,basis:snapshotBasis(snapshot),
    generatedAt:snapshot.generatedAt,coverage:clone(snapshot.coverage),projects,reviews:clone(reviews),
    continuity:buildContinuity(snapshot),
    reminders:clone(snapshot.reminders.filter(r=>!['closed','cancelled'].includes(r.businessState))).sort((a,b)=>(priorityRank[a.priority]??4)-(priorityRank[b.priority]??4)||a.id.localeCompare(b.id))};
}
