import {createHash,randomUUID} from 'node:crypto';
import {FeishuTaskClient} from './feishu-task-client.mjs';

const fail=(message,status=422)=>Object.assign(new Error(message),{status});
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const codePattern=/^[A-Za-z0-9][A-Za-z0-9_-]{3,160}$/;
const collections={case:'cases',deliverable:'deliverables',project:'projects'};
export function approvalInstanceCode(input){
  if(typeof input==='string'&&codePattern.test(input.trim()))return input.trim();
  try{const url=new URL(input);if(url.protocol==='https:'&&!url.username&&!url.password&&!url.port&&(url.hostname==='feishu.cn'||url.hostname.endsWith('.feishu.cn'))){const code=url.searchParams.get('instanceCode')||url.searchParams.get('instance_code');if(codePattern.test(code||''))return code;}}catch{}
  throw fail('请填写审批实例标识，或带实例标识的飞书审批链接');
}
export function approvalText(raw,domain){
  let form;try{form=JSON.parse(raw.form||'[]');}catch{throw fail('审批表单未返回可解析内容',502);}
  if(!Array.isArray(form))throw fail('审批表单格式不完整',502);
  const value=x=>typeof x==='string'?x:JSON.stringify(x??'');
  const lines=['审批名称：'+(raw.definition_name||'未返回'),'实例标识：'+raw.instance_code,'飞书审批状态：'+domain.approvalStatusLabel(raw.status),...(raw.reverted?['该实例标记为已撤回，请核对。']:[]),'发起人标识：'+(raw.user_id||'未返回'),'发起时间：'+(domain.feedbackTime(raw.start_time)||'未返回'),'结束时间：'+(raw.end_time&&Number(raw.end_time)!==0?domain.feedbackTime(raw.end_time)||'未返回':'尚未返回结束时间'),'','审批表单',...form.map(field=>(field.name||field.id||'字段')+'：'+value(field.value)),'','审批任务',...(raw.tasks||[]).map(t=>(t.node_name||t.id||'节点')+' · '+(t.user_id||'人员未返回')+' · '+(t.status||'状态未返回')),'','审批动态',...(raw.operation_records||[]).map(o=>(domain.feedbackTime(o.create_time)||'时间未返回')+' · '+(o.user_id||'人员未返回')+' · '+o.type+(o.comment?' · '+o.comment:'')),'','评论',...(raw.comments||[]).map(c=>(c.user_id||'人员未返回')+'：'+(c.comment||''))];
  return lines.join('\n');
}
/** Local evidence only. No approve/reject/notify endpoint is used. */
export class ApprovalEvidence {
  constructor({store,domain,client=new FeishuTaskClient(),clock=()=>new Date().toISOString()}){Object.assign(this,{store,domain,client,clock});this.jobs=new Map();this.previews=new Map();this.closed=false;}
  target(input){const s=this.store.load(input.workspaceId),kind=collections[input.targetKind],row=kind?s[kind].find(r=>r.id===input.targetId&&!r.archived):null;if(!row)throw fail('审批依据的关联对象不存在',404);return row;}
  job(key,fn){if(this.closed)throw fail('服务已关闭',503);if(this.jobs.has(key))return this.jobs.get(key).promise;const controller=new AbortController(),signal=AbortSignal.any([controller.signal,AbortSignal.timeout(120000)]),promise=fn(signal).finally(()=>this.jobs.delete(key));this.jobs.set(key,{controller,promise});return promise;}
  search(input){return this.job('search:'+input.workspaceId+':'+input.targetId,async signal=>{
    this.target(input);if(typeof input.query!=='string'||!input.query.trim()||input.query.length>100)throw fail('请用项目编号、报告名称等关键词检索审批');
    const identity=await this.client.identity({signal}),found=new Map(),errors=[],coverage=[];
    for(const topic of ['1','2','17','18','initiated']){
      let token='',done=false;const seen=new Set();
      try{for(let page=0;page<20;page++){
        const params={keyword:input.query.trim(),page_size:100,user_id_type:'open_id',...(topic==='initiated'?{}:{topic}),...(token?{page_token:token}:{})};
        const data=await this.client.run(['approval',topic==='initiated'?'instances':'tasks',topic==='initiated'?'initiated':'query','--params',JSON.stringify(params),'--as','user'],{signal});
        const rows=data?.[topic==='initiated'?'instances':'tasks'];if(!Array.isArray(rows)||typeof data.has_more!=='boolean')throw fail('审批列表分页不完整',502);
        for(const row of rows){if(!codePattern.test(row.instance_code||''))throw fail('审批列表缺少稳定实例标识',502);found.set(row.instance_code,{instanceCode:row.instance_code,title:row.title||row.definition_name||'审批记录',initiator:row.initiator_name||row.initiator||'未返回',summary:(row.summaries||[]).map(s=>s.key+'：'+s.value).join('；'),listStatus:row.instance_status});}
        if(!data.has_more){done=true;break;}if(!data.page_token||seen.has(data.page_token))throw fail('审批分页游标未推进',502);token=data.page_token;seen.add(token);
      }if(!done)errors.push('审批列表 '+topic+' 达到分页上限');}catch(error){if(signal.aborted)throw error;errors.push('审批列表 '+topic+'：'+error.message);}
      coverage.push({topic,complete:done});
    }
    return {candidates:[...found.values()],complete:errors.length===0,errors,coverage,readAt:this.clock(),accountId:identity.userId,scope:identity.scope};
  });}
  async fetch(code,signal){
    const raw=await this.client.run(['approval','instances','get','--params',JSON.stringify({instance_code:code,locale:'zh-CN',user_id_type:'open_id'}),'--as','user'],{signal});
    if(raw?.instance_code!==code||typeof raw.status!=='string')throw fail('审批实例身份或状态未通过核对',409);
    if(Buffer.byteLength(JSON.stringify(raw))>2*1024*1024)throw fail('审批详情超过本次读取范围，请从飞书核对');
    return {raw,excerpt:approvalText(raw,this.domain),rawHash:hash(raw)};
  }
  preview(input){return this.job('preview:'+input.workspaceId+':'+input.targetId,async signal=>{
    const row=this.target(input),identity=await this.client.identity({signal}),code=approvalInstanceCode(input.instance),value=await this.fetch(code,signal),previewId=randomUUID();
    for(const [id,p]of this.previews)if(Date.parse(this.clock())-Date.parse(p.at)>600000)this.previews.delete(id);
    if(this.previews.size>=40)throw fail('待核对的审批预览较多，请稍后再读取',429);
    this.previews.set(previewId,{...value,identity,workspaceId:input.workspaceId,targetKind:input.targetKind,targetId:input.targetId,targetVersion:row.version,at:this.clock()});
    return {previewId,title:value.raw.definition_name||'审批记录',instanceCode:code,status:value.raw.status,statusLabel:this.domain.approvalStatusLabel(value.raw.status),excerpt:value.excerpt,readAt:this.clock()};
  });}
  save(input,value,identity,targetVersion){
    const id='approval-'+hash([identity.scope,identity.userId,value.raw.instance_code]).slice(0,36);
    const state=this.store.transaction(()=>{
      const before=this.store.load(input.workspaceId),next=structuredClone(before),row=next[collections[input.targetKind]]?.find(r=>r.id===input.targetId&&!r.archived);
      if(!row||targetVersion!==undefined&&row.version!==targetVersion)throw fail('关联对象已更新，请重新预览审批',409);
      const prior=next.sources.find(src=>src.id===id),objectIds=[...new Set([...(prior?.objectIds||[]),row.id])],projectIds=[...new Set([...(prior?.projectIds||[]),...(input.targetKind==='project'?[row.id]:row.projectIds)])],caseIds=[...new Set([...(prior?.caseIds||[]),...(input.targetKind==='case'?[row.id]:[])])];
      if(prior&&!prior.archived&&prior.approvalEvidence.rawHash===value.rawHash&&prior.objectIds.includes(row.id)){
        prior.approvalEvidence.checkedAt=this.clock();next.revision++;next.audit.push({id:'approval-recheck-'+randomUUID(),time:this.clock(),operation:'approval.recheck',kind:'sources',objectId:id,actor:'只读核对',before:null,after:{rawHash:value.rawHash,checkedAt:this.clock()},revision:next.revision});this.store.save(next,before.revision);return this.store.load(input.workspaceId);
      }
      const changed=prior&&prior.approvalEvidence.rawHash!==value.rawHash;
      const source={...(prior||{}),id,title:value.raw.definition_name||'飞书审批记录',type:'飞书审批',projectIds,caseIds,objectIds,sourceIds:[],version:(prior?.version||0)+1,excerpt:value.excerpt,collectedAt:this.clock(),occurredAt:this.domain.feedbackTime(value.raw.start_time),author:value.raw.user_id||'发起人未返回',confirmed:false,archived:false,url:prior?.url||'',approvalEvidence:{schemaVersion:1,instanceCode:value.raw.instance_code,scope:identity.scope,accountId:identity.userId,raw:value.raw,rawHash:value.rawHash,readAt:this.clock(),history:[...(prior?.approvalEvidence.history||[]),...(changed?[{version:prior.version,raw:prior.approvalEvidence.raw,excerpt:prior.excerpt,collectedAt:prior.collectedAt}]:[])]}};
      if(prior)Object.assign(prior,source);else next.sources.push(source);
      if(!row.sourceIds.includes(id)){row.sourceIds.push(id);row.version++;row.updatedAt=this.clock();}
      // Bump each associated case when its evidence changes to reject stale forms.
      if(changed)for(const c of next.cases.filter(c=>caseIds.includes(c.id))){c.version++;c.updatedAt=this.clock();}
      next.revision++;next.audit.push({id:'approval-source-'+randomUUID(),time:this.clock(),operation:'approval.evidence',kind:'sources',objectId:id,actor:'本人核对关联 / 只读刷新',before:before.sources.find(src=>src.id===id)||null,after:source,revision:next.revision});
      const errors=this.domain.validateState(next);if(errors.length)throw fail(errors.map(e=>e.message).join('；'));
      this.store.save(next,before.revision);return this.store.load(input.workspaceId);
    });return {state,sourceId:id};
  }
  link(input){return this.job('link:'+input.workspaceId+':'+input.previewId,async signal=>{
    const preview=this.previews.get(input.previewId);if(!preview||preview.workspaceId!==input.workspaceId||preview.targetKind!==input.targetKind||preview.targetId!==input.targetId||Date.parse(this.clock())-Date.parse(preview.at)>600000)throw fail('审批预览已过期或不属于当前对象，请重新读取',409);
    const identity=await this.client.identity({signal});if(identity.scope!==preview.identity.scope||identity.userId!==preview.identity.userId)throw fail('当前账号与审批预览不一致',409);
    const value=await this.fetch(preview.raw.instance_code,signal);if(value.rawHash!==preview.rawHash)throw fail('审批在预览后已变化，请重新读取核对',409);
    const result=this.save(input,value,identity,preview.targetVersion);this.previews.delete(input.previewId);return result;
  });}
  refresh(input){return this.job('refresh:'+input.workspaceId+':'+input.sourceId,async signal=>{
    this.target(input);const source=this.store.load(input.workspaceId).sources.find(src=>src.id===input.sourceId&&!src.archived&&src.objectIds?.includes(input.targetId));if(!source?.approvalEvidence)throw fail('此审批尚未关联到当前对象',409);
    const identity=await this.client.identity({signal}),proof=source.approvalEvidence;
    if(identity.scope!==proof.scope||identity.userId!==proof.accountId)throw fail('当前账号与审批依据不一致',409);
    const value=await this.fetch(proof.instanceCode,signal);
    const current=this.store.load(input.workspaceId).sources.find(src=>src.id===input.sourceId&&!src.archived&&src.objectIds?.includes(input.targetId));if(!current||current.version!==source.version)throw fail('审批关联已变化，请刷新后重试',409);
    return this.save(input,value,identity);
  });}
  async close(){this.closed=true;for(const j of this.jobs.values())j.controller.abort();await Promise.allSettled([...this.jobs.values()].map(j=>j.promise));this.previews.clear();}
}
