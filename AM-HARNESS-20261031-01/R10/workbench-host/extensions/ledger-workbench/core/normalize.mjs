import {asArray, clone, dateString, hash, nonempty, string, valueText, assertSnapshot, unique, reviewSourceBasis, LedgerError} from './model.mjs';

const authorities = new Set(['unconfirmed','source_confirmed','owner_confirmed']);
const businessStates = new Set(['open','waiting','paused','closed','cancelled']);
const projectStates = new Set(['active','paused','closed','unknown']);
const fieldMap = {risk:'blocker',blockers:'blocker',todo:'action',my_action:'action',current_progress:'progress',reported_feedback:'progress'};

function assigneeList(value){
  if(typeof value==='string'){try{value=JSON.parse(value);}catch{return[];}}
  return asArray(value).filter(nonempty);
}

function evidence(raw = {}, now=null) {
  const rawExpiresAt=dateString(raw.rawExpiresAt??raw.raw_expires_at_ms??raw.expiresAtMs);
  const expired=rawExpiresAt&&(!now||Date.parse(now)>=Date.parse(rawExpiresAt));
  const rawAvailable=(raw.rawAvailable===true||raw.raw_available===true)&&!expired;
  return {
    sourceId:string(raw.sourceId ?? raw.source_id), objectId:string(raw.objectId ?? raw.object_id),
    version:String(raw.version ?? ''), quote:rawAvailable&&typeof raw.quote==='string'?raw.quote:null,
    rawAvailable,rawExpiresAt,
    verification:string(raw.verification), url:typeof raw.url === 'string' ? raw.url : null,
    occurredAt:dateString(raw.occurredAt ?? raw.occurred_at_ms), receivedAt:dateString(raw.receivedAt ?? raw.received_at_ms),
    stale:raw.stale === true,
  };
}

function normalizedFact(raw, projectId, itemId, effectiveIds, conflictingIds, now) {
  const id=string(raw.id ?? raw.fact_id), rawField=string(raw.field);
  const refs=asArray(raw.sourceRefs).length ? raw.sourceRefs.map(r=>evidence(r,now)) : [evidence(raw.evidence,now)];
  const authority=authorities.has(raw.authority) ? raw.authority : 'unconfirmed';
  const retentionBoundExcerpt=raw.retentionBoundExcerpt===true;
  const rawExcerptUnavailable=retentionBoundExcerpt&&!refs.some(r=>r.rawAvailable===true&&typeof r.quote==='string');
  const text=rawExcerptUnavailable?'原文暂不可用，待刷新':typeof raw.text === 'string' ? raw.text : valueText(raw.value);
  const displayableReport=['progress','reported_feedback','current_progress','forecast','blocker','risk','execution','delivery'].includes(rawField);
  return {
    id,projectId:raw.projectId ?? projectId ?? null,itemId:raw.itemId ?? itemId ?? null,
    field:fieldMap[rawField] ?? rawField, value:rawExcerptUnavailable?text:clone(raw.value ?? text),text,
    ...(retentionBoundExcerpt?{retentionBoundExcerpt:true,rawExcerptUnavailable}:{}),
    assertionType:['reported','forecast','proposal'].includes(raw.assertionType ?? raw.assertion_type) ? (raw.assertionType ?? raw.assertion_type) : 'reported',
    authority,protected:raw.protected === true,stale:raw.stale === true || refs.some(r=>r.stale),
    status:raw.status ?? (conflictingIds.has(id) ? 'conflict' : effectiveIds.has(id) || authority==='unconfirmed'||displayableReport ? 'effective' : 'candidate'),
    sourceRefs:refs,factIds:asArray(raw.factIds).length ? [...raw.factIds] : [id],
    date:typeof raw.date === 'string' ? raw.date : null,
    critical:raw.critical === true,actorId:string(raw.actorId),actionState:raw.actionState ?? 'open',
    sourceReviewVerified:(raw.sourceReviewVerified === true && authority !== 'unconfirmed')
      ||(rawField==='review'&&authority==='source_confirmed'&&raw.value==='已审核'),
  };
}

function normalizeItem(raw, viewerId) {
  const projectId=raw.projectId ?? raw.project_ref ?? null;
  const explicit=raw.businessState ?? raw.business_state;
  const view=raw.view && typeof raw.view === 'object' ? clone(raw.view) : {};
  const isClosed=(raw.state === 'closed' && nonempty(raw.close_evidence)) || view.business_completed === true;
  const businessState=businessStates.has(explicit) ? explicit : raw.state==='cancelled'?'cancelled':isClosed ? 'closed' : raw.paused ? 'paused' : ['waiting','awaiting_response'].includes(raw.state) ? 'waiting' : 'open';
  const explicitAction=raw.requiresViewerAction === true || raw.requires_owner_action === true;
  const actorId=string(raw.actorId ?? raw.action_actor_id);
  return {
    id:string(raw.id),projectId,title:string(raw.title ?? raw.description),
    version:Number.isSafeInteger(raw.version) ? raw.version : 0,
    semanticVersion:Number.isSafeInteger(raw.semanticVersion) ? raw.semanticVersion : Number.isSafeInteger(raw.semantic_version) ? raw.semantic_version : null,
    businessState,priority:/^P[0-4]$/.test(raw.priority) ? raw.priority : 'P2',
    requiresViewerAction:explicitAction && (!actorId || actorId===viewerId),actorId,
    actionText:string(raw.actionText ?? raw.owner_action),
    dueAt:typeof (raw.dueAt ?? raw.deadline) === 'string' ? (raw.dueAt ?? raw.deadline) : null,
    nextCheckAt:dateString(raw.nextCheckAt ?? (typeof raw.next_check === 'number' && Number.isFinite(raw.next_check) ? raw.next_check * 1000 : null)),
    deadlineKind:string(raw.deadlineKind ?? raw.deadline_kind) || 'unspecified',
    assignees:assigneeList(raw.assignees),view,
  };
}

function coverageFrom(input, queries) {
  const supplied=input.coverage ?? {};
  const reasons=[...asArray(supplied.reasons)].filter(nonempty);
  let status=['complete','partial','stale','unavailable'].includes(supplied.status) ? supplied.status : 'complete';
  let checkedAt=dateString(supplied.checkedAt);
  if (!queries.length && !input.coverage) {status='unavailable';reasons.push('尚未取得项目来源覆盖状态');}
  const processingGaps=[];
  for (const {result:q} of queries) {
    for(const raw of asArray(q.coverage?.processingGaps)){
      const ref=evidence({sourceId:raw.sourceId,objectId:raw.objectId,version:raw.sourceVersion,
        quote:raw.text,rawAvailable:raw.rawAvailable,expiresAtMs:raw.expiresAtMs},dateString(input.generatedAt));
      processingGaps.push({id:string(raw.id),kind:'processing',projectIds:asArray(raw.projectIds).filter(nonempty),
        reason:string(raw.reason),gapCode:string(raw.gapCode),text:ref.quote??'原文暂不可用，待刷新',
        retentionBoundExcerpt:true,rawExcerptUnavailable:!ref.rawAvailable,sourceRefs:[ref]});
    }
    reasons.push(...asArray(q.incomplete_reasons).filter(nonempty));
    if (asArray(q.incomplete_reasons).length || q.coverage?.processing_pending || q.coverage?.needs_refresh_or_review) {
      if(status==='complete')status='partial';
    }
    const sources=asArray(q.freshness?.sources);
    if(sources.some(s=>s.stale || s.availability !== 'ok')) {
      if(status!=='unavailable')status='stale';
      reasons.push('部分来源尚未完成最新核对，保留最近有效信息');
    }
    for(const source of sources){
      const boundary=dateString(source.collected_through_ms??source.last_checked_ms);
      if(boundary&&(!checkedAt||boundary<checkedAt))checkedAt=boundary;
    }
  }
  if(!checkedAt&&queries.length){if(status==='complete')status='partial';reasons.push('来源覆盖时点尚未明确');}
  return {status,checkedAt,reasons:unique(reasons),...(processingGaps.length?{
    processingGaps:[...new Map(processingGaps.map(g=>[g.id,g])).values()]}:{})};
}

/** Pure adapter for data returned by the already-authorized native AM bridge. */
export function normalizeAmSnapshot(input) {
  if(!input||typeof input!=='object'||Array.isArray(input))throw new LedgerError('snapshot_schema');
  if(input?.schemaVersion===1 && Array.isArray(input.facts))return clone(assertSnapshot(input));
  const workspaceId=string(input?.workspaceId ?? input?.tenant),viewerId=string(input?.viewerId ?? input?.owner);
  const generatedAt=dateString(input?.generatedAt) ?? new Date(0).toISOString();
  const projects=asArray(input?.projects).map(p=>({
    id:string(p.id ?? p.key ?? p.project_ref),title:string(p.title ?? p.name),
    kind:p.kind==='outside'||p.subject_kind==='outside'?'outside':'project',
    status:projectStates.has(p.status)?p.status:'unknown',stage:string(p.stage),
  }));
  const projectIds=new Set(projects.map(p=>p.id));
  const items=asArray(input?.items ?? input?.actionItems).map(i=>normalizeItem(i,viewerId)).filter(i=>!i.projectId||projectIds.has(i.projectId));
  const queries=Array.isArray(input?.factQueries) ? input.factQueries : Object.entries(input?.queries ?? {}).map(([projectId,result])=>({projectId,result}));
  const facts=[];const reviews=asArray(input?.reviews).map(clone);const coverage=coverageFrom(input ?? {},queries);
  const projectCoverage=Object.fromEntries(projects.map(p=>[p.id,coverageFrom(input,queries.filter(q=>q.projectId===p.id))]));
  for(const {projectId,itemId,result:q} of queries) {
    if(!projectIds.has(projectId))continue;
    const effectiveIds=new Set(asArray(q.effective).flatMap(e=>asArray(e.fact_ids)));
    const materialConflicts=asArray(q.conflicts).filter(c=>c.material===true || (c.kind==='confirmed_conflict' && ['plan','review','node','decision','owner'].includes(c.field)));
    const conflictingIds=new Set(materialConflicts.flatMap(c=>asArray(c.fact_ids)));
    for(const raw of asArray(q.facts)) {
      const f=normalizedFact(raw,projectId,itemId,effectiveIds,conflictingIds,generatedAt);
      if(f.id)facts.push(f);
      if(!f.text && ['plan','progress','blocker','action','forecast'].includes(f.field)){
        coverage.reasons.push('部分结构化字段尚未映射为摘要，原值保留在依据中');
        projectCoverage[projectId].reasons.push('部分结构化字段尚未映射为摘要，原值保留在依据中');
      }
    }
    for(const conflict of materialConflicts) {
      const selected=facts.filter(f=>conflict.fact_ids.includes(f.id));
      const refs=selected.flatMap(f=>f.sourceRefs);
      const expired=refs.some(r=>r.rawExpiresAt&&Date.parse(generatedAt)>=Date.parse(r.rawExpiresAt));
      reviews.push({id:'conflict:'+hash([projectId,itemId??null,conflict.field]).slice(0,24),projectId,itemId:itemId??null,
        kind:'conflict',question:'这些来源对同一项信息存在差异，需要采用哪项判断？',reason:conflict.kind,
        excerpt:expired?'原文已过期，请刷新来源后再处理':selected.map(f=>f.text).filter(Boolean).join('\n'),evidence:refs,
        choices:expired?[]:selected.map(f=>({id:f.id,label:f.text||'查看该来源',value:{kind:'select',factId:f.id}})),
        basis:hash(selected),status:'pending',factIds:selected.map(f=>f.id)});
    }
  }
  // A verified catalog extraction can expose the existing ledger columns verbatim.
  // No dates, completion, item IDs or formal approval are inferred from this text.
  for(const raw of asArray(input?.projects)) {
    const projectId=string(raw.id ?? raw.key ?? raw.project_ref);
    const verified=raw.ledgerProjectionVerified===true || (raw.read_status==='ok' && nonempty(raw.source_revision));
    if(!verified)continue;
    if(!nonempty(raw.source_revision??raw.content_fingerprint)){
      coverage.reasons.push('台账列缺少来源版本，尚未纳入当前摘要');continue;
    }
    const sourceRef={sourceId:'ledger:'+projectId,objectId:projectId,version:String(raw.source_revision??raw.content_fingerprint??''),
      quote:null,rawAvailable:false,rawExpiresAt:null,verification:'structured_source_read',url:null,
      occurredAt:dateString(raw._sync_observed_at),receivedAt:dateString(raw._sync_observed_at),stale:false};
    for(const [column,field] of [['关键日期','plan'],['项目进展','progress'],['待办','action']]) {
      if(!nonempty(raw[column]))continue;
      facts.push({id:'ledger:'+hash([projectId,column,sourceRef.version]).slice(0,24),projectId,itemId:null,field,
        value:raw[column],text:raw[column],assertionType:'reported',authority:'source_confirmed',protected:false,stale:false,
        status:'effective',sourceRefs:[sourceRef],factIds:[],critical:false,
        ...(field==='action'?{actorId:viewerId,actionState:'open'}:{})});
    }
  }
  for(const raw of asArray(input?.semanticReviews)) {
    const kind=['conflict','ambiguity','association'].includes(raw.kind)?raw.kind:'association';
    const allowed=kind==='association'?asArray(raw.choices).filter(c=>projectIds.has(c.subjectId)):asArray(raw.choices);
    const ref=evidence({source_id:raw.sourceId,object_id:raw.objectId,version:raw.sourceVersion,quote:raw.text,
      raw_available:raw.rawAvailable,raw_expires_at_ms:raw.expiresAtMs,verification:'verbatim_at_extraction'},generatedAt);
    const expired=raw.expiresAtMs&&Date.parse(generatedAt)>=raw.expiresAtMs;
    reviews.push({id:string(raw.id),projectId:projectIds.has(raw.projectId)?raw.projectId:null,itemId:raw.itemId??null,
      kind,question:string(raw.question)||(kind==='association'?'这条反馈属于哪个项目或事项？':kind==='conflict'?'原事项依据已变化，需要重新核对当前依据':'这条反馈中的关键含义需要核对'),reason:string(raw.reason),
      excerpt:raw.rawAvailable===false||expired?'原文已不可用，请刷新来源后再处理':string(raw.text),evidence:[ref],
      choices:raw.rawAvailable===false||expired?[]:allowed.map(c=>kind==='association'?{id:c.subjectId,label:c.title||c.subjectId,value:{kind:'associate',projectId:c.subjectId}}:clone(c)),
      basis:string(raw.reviewHash),status:'pending',factIds:[],expiresAtMs:raw.expiresAtMs??null});
  }
  // Display choices do not modify the FactEngine's fact authority/status or its execution guards.
  for(const decision of asArray(input?.reviewDecisions)){
    const review=reviews.find(r=>r.id===decision.reviewId&&r.basis===decision.reviewHash&&r.status==='pending');
    if(!review||review.kind!=='conflict')continue;
    const actual=unique(asArray(review.factIds)).sort(),claimed=unique(asArray(decision.factIds)).sort();
    if(hash(actual)!==hash(claimed)||!actual.includes(decision.selectedFactId)||decision.sourceIdentityHash!==reviewSourceBasis(review))continue;
    review.status='resolved';review.resolution={kind:'display_selection',selectedFactId:decision.selectedFactId};
    for(const f of facts.filter(f=>actual.includes(f.id)))f.displaySelected=f.id===decision.selectedFactId;
  }
  const itemById=new Map(items.map(i=>[i.id,i]));
  const reminders=asArray(input?.reminders).flatMap(raw=>{
    const item=itemById.get(raw.itemId??raw.item_id);
    if(!item||!item.projectId)return[];
    const metadata=raw.metadata?.basis===raw.basis?raw.metadata:{};
    const display={...raw,...metadata};
    let displayState=['read','snoozed'].includes(display.displayState)?display.displayState:'unread';
    if(displayState==='snoozed'&&display.snoozedUntil&&Date.parse(display.snoozedUntil)<=Date.parse(generatedAt))displayState=display.readAt?'read':'unread';
    const r={id:string(raw.id),itemId:item.id,projectId:item.projectId,title:string(raw.title)||item.title,
      body:string(raw.body??raw.text),priority:/^P[0-4]$/.test(raw.priority)?raw.priority:item.priority,
      dueAt:raw.dueAt??null,displayState,snoozedUntil:display.snoozedUntil??null,businessState:item.businessState,
      kind:string(raw.kind),severity:string(raw.severity)||'attention'};
    return[{...r,basis:raw.basis||hash(r)}];
  });
  if(input.reminderCoverage&&input.reminderCoverage.status!=='complete'){
    if(coverage.status==='complete')coverage.status='partial';
    coverage.reasons.push(...asArray(input.reminderCoverage.reasons).filter(nonempty),'关注事项尚未完成全部核对');
    for(const value of Object.values(projectCoverage)){
      if(value.status==='complete')value.status='partial';
      value.reasons.push(...asArray(input.reminderCoverage.reasons).filter(nonempty),'关注事项尚未完成全部核对');
    }
  }
  coverage.reasons=unique(coverage.reasons);
  if(coverage.reasons.length&&coverage.status==='complete')coverage.status='partial';
  for(const value of Object.values(projectCoverage)){
    value.reasons=unique(value.reasons);if(value.reasons.length&&value.status==='complete')value.status='partial';
  }
  const dedupe=list=>[...new Map(list.map(v=>[v.id,v])).values()];
  return assertSnapshot({schemaVersion:1,workspaceId,viewerId,revision:input.revision??hash([facts,items,reviews]),generatedAt,
    coverage,projectCoverage,projects:dedupe(projects),items:dedupe(items),facts:dedupe(facts),reviews:dedupe(reviews),reminders:dedupe(reminders),
    sources:asArray(input.sources).map(clone),decisions:asArray(input.decisions).map(clone),receipts:asArray(input.receipts).map(clone)});
}
