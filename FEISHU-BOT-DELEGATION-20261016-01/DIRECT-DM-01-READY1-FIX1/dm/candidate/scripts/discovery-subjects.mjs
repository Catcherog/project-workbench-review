import {createHash,randomUUID} from 'node:crypto';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const fail=(message,status=409)=>Object.assign(Error(message),{status});

/** Pure state transition shared by the overview and the legacy risk review endpoint. */
export function classifyDiscoverySubject(before,input,domain,at=new Date().toISOString()) {
  const {key,expectedBasis,requestId}=input;
  if(!/^[-\w]{1,160}$/.test(requestId||''))throw fail('缺少有效请求标识',422);
  if(before.workspaceType==='restored')throw fail('恢复工作区仅保留历史，请在正式工作区确认归属');
  const receiptKey='subject-classify:'+requestId,fingerprint=hash(input),prior=before.receipts[receiptKey];
  if(prior){if(prior.fingerprint!==fingerprint)throw fail('同一请求不能改变归属选择');return {state:before,...prior.result};}
  const subject=domain.pendingDiscoverySubjects(before).find(row=>row.key===key);
  if(!subject||subject.basis!==expectedBasis)throw fail('待定事项或资料已更新，请重新核对后选择');
  if(Boolean(input.target)===Boolean(input.newCase))throw fail('请选择关联项目或转为专项',422);
  let next=structuredClone(before),target=input.target;
  const reviews=new Map(next.sources.filter(source=>source.managementSignal).map(source=>[source.id,domain.managementSignalState(next,source).review]));
  if(target&&(!['projects','cases'].includes(target.kind)||!next[target.kind]?.some(row=>row.id===target.id&&!row.archived&&!row.mergedIntoId)))throw fail('请选择本工作区内有效的项目或专项',422);
  // Confirming one pending group must never silently move somebody else's linked work.
  for(const id of subject.sourceIds){
    const known=domain.inferredManagementTarget(next,next.sources.find(source=>source.id===id));
    if(known&&(!target||known.kind!==target.kind||known.id!==target.id))throw fail('该群已有其他事项关联，请先核对现有归属');
  }
  if(input.newCase){
    if(typeof input.newCase.title!=='string'||!input.newCase.title.trim()||input.newCase.title.trim().length>200)throw fail('请填写200字以内的专项名称',422);
    const created=domain.applyCaseCommand(next,{action:'create',requestId:'subject-'+hash([before.workspaceId,key]).slice(0,40),title:input.newCase.title.trim(),projectIds:[],caseType:'临时专项'});
    next=created.state;target={kind:'cases',id:created.caseId};
    const record=next.cases.find(row=>row.id===target.id);
    record.sourceIds=[...new Set([...subject.sourceIds,...subject.signalIds])];record.situation=subject.summary;
    record.nextAction='核对现状与后续工作';
    const creation=next.audit.findLast(entry=>entry.operation==='case.create'&&entry.objectId===record.id);if(creation)creation.after=structuredClone(record);
  }
  target={kind:target.kind,id:target.id};
  const record=next[target.kind].find(row=>row.id===target.id),associationId='subject-association-'+hash(key).slice(0,32),oldAssociation=next.sources.find(row=>row.id===associationId);
  const association={id:associationId,title:subject.title+' · 归属记录',type:'事项归属记录',projectIds:target.kind==='projects'?[target.id]:record.projectIds||[],sourceIds:subject.sourceIds,objectIds:[target.id],confirmed:true,processingStatus:'已整理',version:(oldAssociation?.version||0)+1,collectedAt:oldAssociation?.collectedAt||at,updatedAt:at,excerpt:'本人确认的事项归属；风险核实与业务验收分别记录。',subjectAssociation:{schemaVersion:1,key,chat:subject.chat,target,decidedAt:at,decidedBy:'本人',history:oldAssociation?[...(oldAssociation.subjectAssociation.history||[]),oldAssociation.subjectAssociation]:[]}};
  if(oldAssociation)Object.assign(oldAssociation,association);else next.sources.push(association);
  const changed=new Map();
  for(const id of subject.sourceIds){
    const source=next.sources.find(row=>row.id===id),oldBasis=domain.materialSourceIdentityKey(next,source);
    if(domain.applySourceSubjectAssociation(next,source,target)){source.version++;source.updatedAt=at;changed.set(id,[oldBasis,domain.materialSourceIdentityKey(next,source)]);}
  }
  for(const source of next.sources.filter(row=>row.managementSignal)){
    const signal=source.managementSignal;let updated=false;
    if((signal.origin==='agent'||signal.origin==='dot')&&!signal.target&&subject.sourceIds.includes(signal.sourceId)){
      signal.target=target;source.objectIds=[target.id];source.projectIds=target.kind==='projects'?[target.id]:record.projectIds||[];
      if(target.kind==='cases')source.caseIds=[target.id];updated=true;
    }
    // Rebase only exact, previously valid source identities for this metadata-only move.
    // A changed or withdrawn original must stay stale, even after choosing its project.
    const original=changed.get(signal.sourceId);
    if(original&&signal.sourceBasis===original[0]){signal.sourceBasis=original[1];updated=true;}
    for(const proof of signal.evidence||[]){const pair=changed.get(proof.sourceId);if(pair&&proof.basis===pair[0]){proof.basis=pair[1];updated=true;}}
    if(updated){
      const review=reviews.get(source.id);
      if(review)signal.associationReviewBasis={previous:review.basis,current:domain.managementSignalState(next,source).basis};
      source.version++;source.updatedAt=at;
    }
  }
  const result={target,subjectKey:key};next.receipts[receiptKey]={fingerprint,result};
  next.audit.push({id:'subject-classify-'+randomUUID(),time:at,operation:'subject.classify',kind:target.kind,objectId:target.id,actor:'本人',before:{key,sourceIds:subject.sourceIds,signalIds:subject.signalIds},after:{title:record.title,target,createdCase:!!input.newCase},revision:next.revision+1});
  next.revision++;const errors=domain.validateState(next);if(errors.length)throw fail(errors.map(error=>error.message).join('；'));
  return {state:next,...result};
}

export class DiscoverySubjects {
  constructor({store,domain}){Object.assign(this,{store,domain});}
  classify(input){return this.store.transaction(()=>{const before=this.store.load(input.workspaceId),result=classifyDiscoverySubject(before,input,this.domain);if(result.state!==before)this.store.save(result.state,before.revision);return {...result,state:this.store.load(input.workspaceId)};});}
}
