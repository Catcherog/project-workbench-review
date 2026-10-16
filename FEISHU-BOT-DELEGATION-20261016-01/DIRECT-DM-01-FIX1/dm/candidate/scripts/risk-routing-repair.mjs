/** Reconcile existing grounded AI receipts; human decisions are never replayed. */
export function repairRiskRouting(state,advice,domain,at){
 let changed=false;const latest=new Map();for(const a of advice||[])for(const [i,f]of(a.workItems||[]).entries()){const id=f.existingItemId||a.workItemIds?.[i];if(id&&!a.historical)latest.set(id,f);}
 for(const source of state.sources.filter(s=>s.workItem&&!s.archived)){
  const old=source.workItem;if(old.routingPolicyVersion===3)continue;
  const f=latest.get(source.id),human=old.human?.fields?.length||old.reviews?.length||old.pendingChange||old.disposition?.state==='ignored'||old.handling?.state==='handled'||old.handling?.state==='in_progress'||old.handling?.manuallyReady||old.decisions?.length;
  if(f&&!human&&f.triage){
   const sources=f.sourceIds.map(id=>state.sources.find(s=>s.id===id));
   const valid=sources.every(s=>s&&!s.workItem&&domain.caseEvidenceAvailable(state,s)&&old.evidence.some(e=>e.key===domain.workSourceKey(state,s)&&e.fingerprint===domain.workSourceFingerprint(state,s)));
   const background=old.nature==='action'&&f.triage.necessary===false&&['reference','noise'].includes(f.nature);
   const scoped=old.nature==='risk'&&f.triage.necessary===false;
   const renewed=domain.workItemState(state,source).stale&&f.triage.necessary&&f.triage.ready&&sources.some(s=>s?.riskEvidence?.complete&&['document','attachment'].includes(s.riskEvidence.origin));
   if(valid&&(background||scoped||renewed)){
    domain.applyWorkItemFindings(state,[{...f,id:undefined,existingItemId:source.id,expectedVersion:source.version,matchReason:'已保存判断按统一分流规则修复',...(renewed?{assessmentSourceIds:f.sourceIds}:{})}],at);
    source.workItem.routingRepair={at,reason:background?'历史背景退出待办':renewed?'采用本次已核对依据，旧依据留存':'消息必要性与原风险分开'};
   }
  }
  source.workItem.routingPolicyVersion=3;changed=true;
 }
 return changed;
}
