import {assertSnapshot, asArray, changeReceipt, clone, currentFacts, fieldBasis, finishMutation, hash, LedgerError,
  mergeEvidence, nonempty, sourceKey, unique, valueText} from './model.mjs';

const acceptedFields=new Set(['plan','forecast','progress','blocker','risk','action','delivery','review','node','decision','owner','background']);
const formalFields=new Set(['plan','review','node','decision','owner']);
const liveStatuses=new Set(['effective','candidate','conflict']);

function markCoverage(s,projectIds,status,reason){
  s.coverage={...s.coverage,status:s.coverage?.status==='unavailable'?'unavailable':status,reasons:unique([...asArray(s.coverage?.reasons),reason])};
  if(s.projectCoverage){
    const ids=projectIds.length?projectIds:Object.keys(s.projectCoverage);
    for(const id of ids){const value=s.projectCoverage[id];if(value)s.projectCoverage[id]={...value,status:value.status==='unavailable'?'unavailable':status,reasons:unique([...asArray(value.reasons),reason])};}
  }
}

function validateOrdinaryCandidate(c){
  if(!c||!nonempty(c.id)||!acceptedFields.has(c.field)||!['reported','forecast','proposal'].includes(c.assertionType))return'candidate_schema';
  if(c.authority&&c.authority!=='unconfirmed')return'authority_elevation';
  if(c.protected||c.sourceReviewVerified)return'authority_elevation';
  if(c.assertionType==='forecast'&&c.field==='plan')return'forecast_cannot_replace_plan';
  if(!nonempty(c.text||valueText(c.value)))return'candidate_text_missing';
  const refs=asArray(c.sourceRefs);
  if(!refs.length)return'evidence_required';
  if(refs.some(r=>!nonempty(r.sourceId)||!nonempty(r.objectId)||!nonempty(r.version)||r.verification!=='verbatim_at_extraction'
    ||(r.rawAvailable!==false&&!nonempty(r.quote))))return'evidence_unverified';
  return null;
}

function updateSources(s,updates){
  s.sources=asArray(s.sources);
  for(const u of updates){
    if(!nonempty(u.sourceId)||!nonempty(u.objectId)||!nonempty(u.version))throw new LedgerError('source_update_schema');
    const index=s.sources.findIndex(v=>v.sourceId===u.sourceId&&v.objectId===u.objectId);
    const old=index<0?null:s.sources[index];
    if(old&&u.version!==old.version&&u.expectedVersion!==old.version)throw new LedgerError('source_version_changed');
    if(old&&u.expectedVersion!==undefined&&u.expectedVersion!==old.version)throw new LedgerError('source_version_changed');
    if(old?.version===u.version&&old.withdrawn&&!u.withdrawn)throw new LedgerError('withdrawn_source_not_restored_implicitly');
    if(index<0)s.sources.push(clone(u));else s.sources[index]={...old,...clone(u)};
    if(u.withdrawn||(u.availability&&u.availability!=='ok')){
      const projectIds=unique(s.facts.filter(f=>asArray(f.sourceRefs).some(r=>r.sourceId===u.sourceId&&r.objectId===u.objectId)).map(f=>f.projectId).filter(Boolean));
      markCoverage(s,projectIds,u.withdrawn?'partial':'stale',u.withdrawn?'部分原始依据已撤回，相关事项需重新核实':'部分来源读取未完成，保留最近有效信息');
    }
    for(const f of s.facts){
      if(!liveStatuses.has(f.status))continue;
      const affected=asArray(f.sourceRefs).filter(r=>r.sourceId===u.sourceId&&r.objectId===u.objectId);
      if(!affected.length)continue;
      if(u.availability&&u.availability!=='ok'&&!u.withdrawn){f.stale=true;continue;}
      const retained=asArray(f.sourceRefs).filter(r=>r.sourceId!==u.sourceId||r.objectId!==u.objectId||(!u.withdrawn&&r.version===u.version));
      if(retained.length){f.sourceRefs=retained;continue;}
      if(f.protected||f.authority==='owner_confirmed'){
        f.stale=true;f.requiresRevalidation=true;
      }else{
        f.status=u.withdrawn?'withdrawn':'superseded';
        f.inactiveReason=u.withdrawn?'source_withdrawn':'source_revised';
      }
    }
  }
}

function normalizedCandidate(c){
  return {id:c.id,itemId:c.itemId??null,projectId:c.projectId??null,field:c.field==='risk'?'blocker':c.field,
    value:clone(c.value??c.text),text:c.text||valueText(c.value),assertionType:c.assertionType,authority:'unconfirmed',
    protected:false,stale:asArray(c.sourceRefs).some(r=>r.stale),status:'effective',sourceRefs:clone(c.sourceRefs),factIds:[c.id],
    date:c.date??null,critical:c.critical===true,actorId:c.actorId??'',actionState:c.actionState??'open'};
}

function reviewFor(s,c,kind,reason){
  const identity=[c.itemId??null,c.projectId??null,c.field,kind,reason];
  const id='review:'+hash(identity).slice(0,24);
  const question=kind==='association'?'这条反馈属于哪个项目或事项？':kind==='conflict'?'这项关键信息存在冲突，需要采用哪项判断？':c.ambiguity?.question||'这条反馈中影响下一步判断的含义是什么？';
  let choices;
  if(kind==='association')choices=s.projects.map(p=>({id:p.id,label:p.title,value:{kind:'associate',projectId:p.id}}));
  else if(kind==='ambiguity'&&Array.isArray(c.ambiguity?.choices))choices=clone(c.ambiguity.choices);
  else choices=[{id:'keep-reported',label:'保留为未核实反馈',value:{kind:'keep_reported'}},{id:'background',label:'仅留作背景资料',value:{kind:'background'}}];
  const old=s.reviews.find(r=>r.id===id&&r.status==='pending');
  const candidateFact=normalizedCandidate(c);candidateFact.status='candidate';
  const existing=s.facts.find(f=>f.id===c.id);
  if(!existing)s.facts.push(candidateFact);
  const evidence=mergeEvidence(asArray(old?.evidence),c.sourceRefs);
  const factIds=unique([...asArray(old?.factIds),c.id]);
  const review={id,projectId:c.projectId??null,itemId:c.itemId??null,kind,question,reason,
    excerpt:evidence.filter(e=>e.rawAvailable!==false&&e.quote).map(e=>e.quote).join('\n'),evidence,choices,
    factIds,basis:hash({identity,evidence,factIds,choices}),status:'pending'};
  if(old)Object.assign(old,review);else s.reviews.push(review);
  return id;
}

/** Ordinary feedback classifier; all authority-bearing observations use the original FactEngine. */
export function organizeCandidates(snapshot,candidates,{requestId,now=snapshot.generatedAt,sourceUpdates=[]}={}){
  assertSnapshot(snapshot);
  if(!Array.isArray(candidates))throw new LedgerError('candidate_array_required');
  const op={kind:'organize',candidates,sourceUpdates};
  const pre=changeReceipt(snapshot,requestId,op,null,now);
  if(pre.duplicate)return{snapshot:clone(snapshot),receipt:pre.receipt,outcomes:clone(pre.receipt.result.outcomes),duplicate:true};
  const s=clone(snapshot);updateSources(s,sourceUpdates);
  const outcomes=[];const knownProjects=new Map(s.projects.map(p=>[p.id,p]));
  for(const c of candidates){
    const invalid=validateOrdinaryCandidate(c);
    if(invalid){outcomes.push({candidateId:c?.id??null,status:'rejected',reason:invalid});continue;}
    if(s.facts.some(f=>f.id===c.id||asArray(f.factIds).includes(c.id))){outcomes.push({candidateId:c.id,status:'duplicate'});continue;}
    if(c.expectedFieldBasis&&c.expectedFieldBasis!==fieldBasis(snapshot,c.itemId??null,c.field)){
      outcomes.push({candidateId:c.id,status:'rejected',reason:'field_basis_changed'});continue;
    }
    const protectedDecision=asArray(s.decisions).find(d=>d.itemId===(c.itemId??null)&&d.field===c.field);
    if(protectedDecision&&c.expectedDecisionVersion!==undefined&&c.expectedDecisionVersion!==protectedDecision.version){
      outcomes.push({candidateId:c.id,status:'rejected',reason:'manual_decision_changed'});continue;
    }
    const sourceInvalid=c.sourceRefs.some(ref=>{
      const live=s.sources.find(v=>v.sourceId===ref.sourceId&&v.objectId===ref.objectId);
      return live&&(live.withdrawn||live.version!==ref.version);
    });
    if(sourceInvalid){outcomes.push({candidateId:c.id,status:'rejected',reason:'source_version_changed'});continue;}
    if(!knownProjects.has(c.projectId)||c.association==='unknown'){
      const reviewId=reviewFor(s,{...c,projectId:null},'association','project_unresolved');
      outcomes.push({candidateId:c.id,status:'review',reviewId});continue;
    }
    if(c.association==='outside'&&knownProjects.get(c.projectId).kind!=='outside'){
      outcomes.push({candidateId:c.id,status:'rejected',reason:'outside_scope_mismatch'});continue;
    }
    if(c.itemId&&!s.items.some(i=>i.id===c.itemId&&i.projectId===c.projectId)){
      const reviewId=reviewFor(s,{...c,itemId:null},'association','item_unresolved');
      outcomes.push({candidateId:c.id,status:'review',reviewId});continue;
    }
    if(c.ambiguity?.material===true){
      const reviewId=reviewFor(s,c,'ambiguity','material_ambiguity');outcomes.push({candidateId:c.id,status:'review',reviewId});continue;
    }
    if(c.conflict?.material===true){
      const reviewId=reviewFor(s,c,'conflict','material_conflict');outcomes.push({candidateId:c.id,status:'review',reviewId});continue;
    }
    const f=normalizedCandidate(c);
    f.stale ||= f.sourceRefs.some(ref=>{const source=s.sources.find(v=>v.sourceId===ref.sourceId&&v.objectId===ref.objectId);return source?.availability&&source.availability!=='ok';});
    // A proposal or unconfirmed formal claim may be retained but cannot replace a formal field.
    if(f.assertionType==='proposal'||f.field==='background'||formalFields.has(f.field)){
      f.status='background';s.facts.push(f);outcomes.push({candidateId:c.id,status:'background'});continue;
    }
    const same=currentFacts(s).find(old=>old.projectId===f.projectId&&old.itemId===f.itemId&&old.field===f.field
      &&old.assertionType===f.assertionType&&old.authority==='unconfirmed'&&hash(old.value)===hash(f.value)&&old.status==='effective');
    if(same){same.sourceRefs=mergeEvidence(same.sourceRefs,f.sourceRefs);same.factIds=unique([...asArray(same.factIds),f.id]);same.critical ||= f.critical;
      outcomes.push({candidateId:c.id,status:'merged',factId:same.id});
    }else{s.facts.push(f);outcomes.push({candidateId:c.id,status:'automatic',factId:f.id});}
  }
  if(outcomes.some(o=>o.status==='rejected'&&['evidence_required','evidence_unverified','source_version_changed'].includes(o.reason))){
    const rejectedIds=new Set(outcomes.filter(o=>o.status==='rejected').map(o=>o.candidateId));
    markCoverage(s,unique(candidates.filter(c=>rejectedIds.has(c?.id)).map(c=>c.projectId).filter(Boolean)),'partial','部分新反馈依据未完成核对，尚未用于更新摘要');
  }
  const receipt={...pre.receipt,result:{outcomes}};
  finishMutation(s,receipt,now);
  return{snapshot:s,receipt,outcomes,duplicate:false};
}

export function applyReviewDecision(snapshot,decision){
  assertSnapshot(snapshot);
  const {reviewId,choiceId,expectedBasis,requestId,actorId,now=snapshot.generatedAt}=decision??{};
  if(actorId!==snapshot.viewerId)throw new LedgerError('actor_not_authorized');
  const operation={kind:'review',reviewId,choiceId,expectedBasis,actorId};
  const pre=changeReceipt(snapshot,requestId,operation,null,now);
  if(pre.duplicate)return{snapshot:clone(snapshot),receipt:pre.receipt,duplicate:true};
  const s=clone(snapshot);const review=s.reviews.find(r=>r.id===reviewId);
  if(!review||review.status!=='pending')throw new LedgerError('review_not_pending');
  if(!expectedBasis||review.basis!==expectedBasis)throw new LedgerError('review_basis_changed');
  if(review.expiresAtMs&&Date.parse(now)>=review.expiresAtMs)throw new LedgerError('review_evidence_expired');
  if(asArray(review.evidence).some(ref=>{const source=asArray(s.sources).find(v=>v.sourceId===ref.sourceId&&v.objectId===ref.objectId);return source&&(source.withdrawn||source.version!==ref.version);}))throw new LedgerError('review_evidence_changed');
  const choice=asArray(review.choices).find(c=>c.id===choiceId);
  if(!choice)throw new LedgerError('review_choice_invalid');
  const value=choice.value??{};const affected=s.facts.filter(f=>asArray(review.factIds).includes(f.id));
  if(value.kind==='associate'){
    const p=s.projects.find(p=>p.id===value.projectId);
    if(!p)throw new LedgerError('project_not_authorized');
    if(review.reason==='item_unresolved')throw new LedgerError('item_association_requires_native_host');
    if(!affected.length)throw new LedgerError('native_review_requires_host');
    if(affected.some(f=>f.itemId&&!s.items.some(i=>i.id===f.itemId&&i.projectId===p.id)))throw new LedgerError('item_project_mismatch');
    for(const f of affected){f.projectId=p.id;f.status=formalFields.has(f.field)||f.assertionType==='proposal'?'background':'effective';}
    review.projectId=p.id;
  }else if(value.kind==='background'){
    for(const f of affected)if(f.authority==='unconfirmed'&&!f.protected)f.status='background';
  }else if(value.kind==='keep_reported'){
    for(const f of affected)if(f.authority==='unconfirmed')f.status=formalFields.has(f.field)?'background':'effective';
  }else if(value.kind==='select'){
    const chosen=affected.find(f=>f.id===value.factId);
    if(!chosen)throw new LedgerError('review_choice_invalid');
    // Selecting a source resolves its display dispute. It cannot overwrite a protected human decision.
    if(affected.some(f=>f.id!==chosen.id&&(f.protected||f.authority==='owner_confirmed')))throw new LedgerError('protected_decision_requires_native_correction');
    chosen.status=chosen.authority==='unconfirmed'&&formalFields.has(chosen.field)?'background':'effective';
    for(const f of affected)if(f.id!==chosen.id)f.status='background';
  }else throw new LedgerError('review_choice_not_supported');
  review.status='resolved';review.resolution={choiceId,actorId,at:now};
  const receipt={...pre.receipt,result:{reviewId,status:'resolved',projectId:review.projectId,externalActionApproved:false}};
  finishMutation(s,receipt,now);return{snapshot:s,receipt,duplicate:false};
}

export function applyReminderDisplayAction(snapshot,input){
  assertSnapshot(snapshot);
  const {reminderId,action,expectedBasis,requestId,actorId,until,now=snapshot.generatedAt}=input??{};
  if(actorId!==snapshot.viewerId)throw new LedgerError('actor_not_authorized');
  if(!['read','snooze'].includes(action))throw new LedgerError('display_action_invalid');
  const operation={kind:'reminder_display',reminderId,action,expectedBasis,actorId,until:until??null};
  const pre=changeReceipt(snapshot,requestId,operation,null,now);
  if(pre.duplicate)return{snapshot:clone(snapshot),receipt:pre.receipt,duplicate:true};
  const s=clone(snapshot),r=s.reminders.find(v=>v.id===reminderId);
  if(!r)throw new LedgerError('reminder_not_found');
  if(!expectedBasis||r.basis!==expectedBasis)throw new LedgerError('reminder_basis_changed');
  if(action==='snooze'){
    if(!nonempty(until)||!Number.isFinite(Date.parse(until))||Date.parse(until)<=Date.parse(now))throw new LedgerError('snooze_time_invalid');
    r.displayState='snoozed';r.snoozedUntil=until;
  }else{r.readAt=now;if(r.displayState!=='snoozed'||!r.snoozedUntil||Date.parse(r.snoozedUntil)<=Date.parse(now))r.displayState='read';}
  r.displayVersion=(r.displayVersion??0)+1;
  const receipt={...pre.receipt,result:{reminderId,displayState:r.displayState,businessState:r.businessState,closed:false}};
  finishMutation(s,receipt,now);return{snapshot:s,receipt,duplicate:false};
}
