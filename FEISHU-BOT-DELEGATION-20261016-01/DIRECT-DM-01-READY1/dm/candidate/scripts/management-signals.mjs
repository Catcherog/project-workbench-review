import {createHash,randomUUID} from 'node:crypto';
import {classifyDiscoverySubject} from './discovery-subjects.mjs';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const fail=(message,status=409)=>Object.assign(Error(message),{status});
function upsert(state,id,signal,{projectIds=[],sourceIds=[],at}){
  const old=state.sources.find(row=>row.id===id);
  const current=old?.managementSignal;
  const history=current?[...(current.history||[]),{...current,history:undefined,reviews:undefined,at:old.updatedAt}]:[];
  const row={...(old||{}),id,title:signal.title,type:'管理提示',aiGenerated:true,confirmed:false,projectIds,sourceIds,objectIds:signal.target?[signal.target.id]:[],version:(old?.version||0)+1,collectedAt:old?.collectedAt||at,updatedAt:at,excerpt:signal.summary,processingStatus:'已整理',managementSignal:{...signal,reviews:current?.reviews||[],history,...(current?.workItemId?{workItemId:current.workItemId,workItemBasis:current.workItemBasis||''}:{})}};
  if(old)Object.assign(old,row);else state.sources.push(row);
  return row;
}
export function publishRuleSignals(state,reportSource){
  const report=reportSource.ruleCheck;
  for(const finding of report.findings){
    if(!finding.targetId||!finding.targetKind)continue;
    const bundle=report.versions.find(v=>v.id+'@'+v.version===finding.ruleVersion)?.definition;
    const rule=bundle?.rules.find(rule=>rule.id===finding.ruleId);if(!rule)continue;
    const originId=[report.projectId,bundle.id,rule.check,finding.targetKind,finding.targetId].join(':');
    const id='management-rule-'+hash(originId).slice(0,28);
    if(finding.status!=='attention'&&!state.sources.some(source=>source.id===id))continue;
    finding.managementSourceId=id;
    upsert(state,id,{schemaVersion:1,origin:'rule',originId,priority:'attention',title:finding.targetTitle+' · '+finding.title,summary:finding.reason,nextStep:'核对当前资料与规则依据，记录本次判断。',quote:bundle.evidence.quote,target:{kind:finding.targetKind,id:finding.targetId},sourceId:reportSource.id,rule:{check:rule.check,projectId:report.projectId,bundle},reviews:[]},{projectIds:[report.projectId],sourceIds:[reportSource.id,...finding.evidenceIds],at:report.checkedAt});
  }
}
export function publishAgentSignals(state,advice,domain){
  for(const item of advice){
    const original=state.sources.find(source=>source.id===item.sourceId);if(!original)continue;
    const id='management-dot-'+hash(item.sourceId).slice(0,28),old=state.sources.find(source=>source.id===id);
    if(item.priority==='routine'&&!old)continue;
    const target=old?.managementSignal?.target||domain.inferredManagementTarget(state,original);
    const source=upsert(state,id,{schemaVersion:1,origin:old?.managementSignal?.origin||'agent',producer:item.producer||'legacy',originId:item.sourceId,priority:item.priority,title:item.triage?.title||item.title,summary:item.summary,nextStep:item.nextStep,quote:item.quote,target,sourceId:original.id,sourceBasis:domain.materialSourceIdentityKey(state,original),reviews:[],adviceId:item.id,triage:item.triage,evidence:item.evidence,workflowId:item.workflowId,createdCaseId:old?.managementSignal?.createdCaseId},{projectIds:original.projectIds||[],sourceIds:[...new Set([original.id,...(item.evidence||[]).map(p=>p.sourceId)])],at:item.createdAt});
    item.managementSourceId=source.id;
  }
}
// Retain the exported name used by older integrations and their stored fixtures.
export const publishDotSignals=publishAgentSignals;
export class ManagementSignals {
  constructor({store,domain,clock=()=>new Date().toISOString()}){Object.assign(this,{store,domain,clock});}
  review(input){
    const {workspaceId,sourceId,requestId,expectedVersion,expectedBasis,decision,reason}=input;
    if(!['confirmed','dismissed','resolved'].includes(decision)||typeof reason!=='string'||!reason.trim()||reason.length>1000||!/^[-\w]{1,160}$/.test(requestId||''))throw fail('请选择处理判断并填写说明与依据',422);
    if(input.newCase!==undefined&&input.target!==undefined)throw fail('专项与已有事项归属不能同时选择',422);
    const receiptKey='management-review:'+requestId,fingerprint=hash(input);
    return this.store.transaction(()=>{
      const before=this.store.load(workspaceId),prior=before.receipts[receiptKey];
      if(prior){if(prior.fingerprint!==fingerprint)throw fail('同一请求不能改变处理内容');return {state:before};}
      let next=structuredClone(before),source=next.sources.find(row=>row.id===sourceId&&!row.archived&&row.managementSignal);
      if(!source||source.version!==expectedVersion)throw fail('提示已更新，请重新核对');
      if(source.managementSignal.workItemId)throw fail('此提示已整合到统一事项，请刷新后在该事项记录判断');
      if(source.managementSignal.historical)throw fail('恢复的提示仅保留为历史，请先重新检查当前资料');
      const current=this.domain.managementSignalState(next,source);
      if(current.basis!==expectedBasis)throw fail('依据已经变化，请重新核对当前内容');
      if((!current.available||current.stale)&&decision!=='dismissed')throw fail('当前依据已失效，只能记录不再跟进或等待新的资料');
      const pending=this.domain.pendingDiscoverySubjects(next).find(row=>row.signalIds.includes(sourceId));
      const classify=pending&&(input.newCase&&decision==='confirmed'||input.target&&['projects','cases'].includes(input.target.kind));
      if(classify){
        const result=classifyDiscoverySubject(next,{key:pending.key,expectedBasis:pending.basis,requestId:'review-'+hash(requestId).slice(0,40),...(input.newCase?{newCase:input.newCase}:{target:input.target})},this.domain,this.clock());
        next=result.state;source=next.sources.find(row=>row.id===sourceId);
        if(input.newCase)source.managementSignal.createdCaseId=result.target.id;
      }else if(input.newCase!==undefined){
        if(!['agent','dot'].includes(source.managementSignal.origin)||decision!=='confirmed'||!current.open||current.target||input.target||source.managementSignal.createdCaseId)throw fail('仅未归属且确认需要跟进的事项可建立独立专项；已有专项请沿用原事项');
        if(!input.newCase||typeof input.newCase.title!=='string'||!input.newCase.title.trim()||input.newCase.title.length>200)throw fail('请填写独立专项名称',422);
        const created=this.domain.applyCaseCommand(next,{action:'create',requestId:'discovery-'+hash([workspaceId,sourceId]).slice(0,40),title:input.newCase.title.trim(),projectIds:[],caseType:'临时专项'});
        next=created.state;source=next.sources.find(row=>row.id===sourceId);
        const row=next.cases.find(row=>row.id===created.caseId);
        row.sourceIds=[...new Set([source.id,...source.sourceIds])];row.situation=source.managementSignal.summary;row.nextAction=source.managementSignal.nextStep;row.priorityReason=source.managementSignal.triage?.impact||'';
        const creation=next.audit.findLast(entry=>entry.operation==='case.create'&&entry.objectId===row.id);if(creation)creation.after=structuredClone(row);
        source.managementSignal.target={kind:'cases',id:row.id};source.managementSignal.createdCaseId=row.id;
      }
      if(input.target!==undefined&&!classify){
        if(!['agent','dot'].includes(source.managementSignal.origin))throw fail('制度提示沿用原检查对象，不能改为其他事项');
        if(!input.newCase)source.managementSignal.target=this.domain.validateManagementTarget(next,input.target);
      }
      const linked=this.domain.managementSignalState(next,source),at=this.clock();
      const entry={basis:linked.basis,decision,reason:reason.trim(),at,actor:'本人',summary:linked.currentSummary,target:linked.target,targetTitle:linked.record?.title||''};
      source.managementSignal.reviews.push(entry);source.version++;source.updatedAt=at;
      source.objectIds=source.managementSignal.target?[source.managementSignal.target.id]:[];
      if(linked.record)source.projectIds=linked.target.kind==='projects'?[linked.record.id]:linked.record.projectIds;
      next.receipts[receiptKey]={fingerprint,result:{sourceId,decision}};
      next.audit.push({id:'management-review-'+randomUUID(),time:at,operation:'management.review',kind:'sources',objectId:sourceId,actor:'本人',before:{target:current.target,review:current.review||null},after:entry,revision:next.revision+1});
      next.revision++;const errors=this.domain.validateState(next);if(errors.length)throw fail(errors.map(error=>error.message).join('；'));
      this.store.save(next,before.revision);return {state:this.store.load(workspaceId)};
    });
  }
}
