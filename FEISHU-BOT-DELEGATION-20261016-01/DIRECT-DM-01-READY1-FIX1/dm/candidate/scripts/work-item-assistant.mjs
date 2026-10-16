const fail=(message,status=422)=>Object.assign(new Error(message),{status});
const strings=['action','targetId','associationKind','associationId','title','summary','remainingSummary','nature','impact','nextStep','reason'];
export const workItemRequestSchema={type:'array',maxItems:1,items:{type:'object',additionalProperties:false,required:[...strings,'sourceIds'],properties:{
  ...Object.fromEntries(strings.map(key=>[key,{type:'string',...(key==='action'?{enum:['associate','merge','split']}:{})}])),sourceIds:{type:'array',items:{type:'string'},maxItems:40}
}}};
export function workItemAssistantContext(state,input,domain){
  if(input.contextRef?.kind!=='sources')return null;
  const source=state.sources.find(row=>row.id===input.contextRef.id&&!row.archived&&row.workItem&&!row.workItem.mergedIntoId);
  if(!source)return null;
  const snapshot=row=>{const c=domain.workItemState(state,row);return {id:row.id,title:row.title,version:row.version,basis:c.basis,evidenceBasis:c.liveEvidenceBasis,summary:row.workItem.summary,nature:row.workItem.nature,association:row.workItem.association,sourceIds:row.sourceIds};};
  const candidates=state.sources.filter(row=>row.workItem&&!row.archived&&!row.workItem.mergedIntoId&&row.id!==source.id);
  return {evidence:source.sourceIds.map(id=>({id,title:state.sources.find(row=>row.id===id)?.title||'原文已不可用'})),current:snapshot(source),candidates:candidates.slice(0,80).map(snapshot),candidateCoverage:{included:Math.min(80,candidates.length),total:candidates.length},
    associations:[{kind:'personal',id:'',title:'个人工作事项'},{kind:'unknown',id:'',title:'暂不确定'},...['projects','cases'].flatMap(kind=>state[kind].filter(row=>!row.archived&&!row.mergedIntoId).map(row=>({kind:kind==='projects'?'project':'case',id:row.id,title:row.title+(row.code?' · '+row.code:'')+(kind==='projects'?'（项目）':'（专项）')})))],
    note:'current/candidates 的 summary 是已保存理解，原文只看 evidence.passages。候选索引可能不完整，不能按名称直接合并。'};
}
export function validateWorkItemRequests(values,context){
  if(values===undefined)return [];
  if(!Array.isArray(values)||values.length>1)throw fail('每次先核对一项整理方案');
  return values.map(value=>{
    if(!context||!value||Object.keys(value).some(key=>![...strings,'sourceIds'].includes(key))||strings.some(key=>typeof value[key]!=='string'||value[key].length>(key==='title'?200:key==='reason'?1000:1600))||!Array.isArray(value.sourceIds)||value.sourceIds.length>40||value.sourceIds.some(id=>typeof id!=='string'))throw fail('事项整理方案格式无效');
    const d=Object.fromEntries(strings.map(key=>[key,value[key].trim()]));d.sourceIds=[...new Set(value.sourceIds)];
    if(!['associate','merge','split'].includes(d.action))throw fail('不支持的事项整理操作');
    if(d.action==='associate'&&d.associationKind&&!context.associations.some(a=>a.kind===d.associationKind&&a.id===d.associationId))throw fail('归属不在本次候选范围');
    if(d.action==='merge'&&d.targetId&&!context.candidates.some(row=>row.id===d.targetId))throw fail('合并目标不在本次候选范围');
    if(d.action==='split'&&d.sourceIds.some(id=>!context.current.sourceIds.includes(id)))throw fail('拆分依据必须来自当前事项');
    if(d.action==='split'&&!['reference','progress','action','decision','risk'].includes(d.nature))throw fail('拆分后的事项类型无效');
    return d;
  });
}
const requestId=(job,index)=>'aiwi-'+job.id+'-'+index;
export function listWorkItemRequests(assistant,workspaceId,jobId){
  const job=assistant.get(jobId,workspaceId),state=assistant.store.load(workspaceId),context=job.workItemContext;
  if(job.status!=='completed'||!context)throw fail('当前对话没有已完成的整理方案',409);
  const current=state.sources.find(row=>row.id===context.current.id),c=current?.workItem?assistant.domain.workItemState(state,current):null;
  const stale=job.restored||job.evidenceStatus==='stale'||!current||current.archived||current.workItem?.mergedIntoId||current.version!==context.current.version||c?.basis!==context.current.basis||c?.liveEvidenceBasis!==context.current.evidenceBasis;
  return {context,cards:(job.workItemRequests||[]).map((draft,index)=>({index,draft,result:job.restored?null:state.receipts['work-item:'+requestId(job,index)]?.result||null,stale:!!stale}))};
}
export function applyWorkItemRequest(assistant,{workspaceId,jobId,index,draft}){
  if(assistant.closed||assistant.suspendedWorkspaces.has(workspaceId))throw fail('工作区正在停止或恢复，请稍后核对',409);
  return assistant.store.transaction(()=>{
    const job=assistant.get(jobId,workspaceId),context=job.workItemContext;
    if(job.status!=='completed'||job.restored||!context||!Number.isInteger(index)||!job.workItemRequests?.[index])throw fail('整理方案不可执行，请重新提问',409);
    const d=validateWorkItemRequests([draft],context)[0];
    if(d.action!==job.workItemRequests[index].action)throw fail('操作类型改变，请重新提出整理要求',409);
    const before=assistant.store.load(workspaceId),current=context.current;
    const op={workspaceId,sourceId:current.id,requestId:requestId(job,index),expectedVersion:current.version,expectedBasis:current.basis,expectedEvidenceBasis:current.evidenceBasis,action:d.action,reason:d.reason};
    if(d.action==='associate')op.association={kind:d.associationKind,id:d.associationId};
    if(d.action==='merge'){const target=context.candidates.find(row=>row.id===d.targetId);if(!target)throw fail('请选择明确的合并目标');Object.assign(op,{targetId:target.id,targetVersion:target.version});
      if(!before.receipts['work-item:'+op.requestId]){const row=before.sources.find(row=>row.id===target.id),c=row?.workItem&&assistant.domain.workItemState(before,row);if(!c||c.basis!==target.basis||c.liveEvidenceBasis!==target.evidenceBasis)throw fail('合并目标的依据已变化，请重新整理',409);}}
    if(d.action==='split')Object.assign(op,{title:d.title,summary:d.summary,remainingSummary:d.remainingSummary,nature:d.nature,impact:d.impact,nextStep:d.nextStep,sourceIds:d.sourceIds,riskDecision:'pending'});
    if(!before.receipts['work-item:'+op.requestId]&&job.evidenceStatus==='stale')throw fail('原文已变化，请重新整理',409);
    const next=assistant.domain.applyWorkItemOperation(before,op,new Date().toISOString());
    const errors=assistant.domain.validateState(next);if(errors.length)throw fail(errors.map(e=>e.message).join('；'));
    if(next!==before){next.receipts['work-item:'+op.requestId].result.draft=d;assistant.store.save(next,before.revision);}
    return listWorkItemRequests(assistant,workspaceId,jobId);
  });
}
