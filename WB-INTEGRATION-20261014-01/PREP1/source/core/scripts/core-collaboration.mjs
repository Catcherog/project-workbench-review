import {createHash,randomUUID} from 'node:crypto';
const digest=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const fail=(message,status=409)=>Object.assign(Error(message),{status});
const untouched=m=>!['sending','unknown','sent','readback_verified'].includes(m.stage);
const targetSnapshot=(s,m)=>{const row=s.deliverables.find(r=>r.id===m.targetId&&!r.archived),item=s.sources.find(r=>r.id===m.workItemId&&r.workItem);return {事项:item?.title||'',归属:item?.workItem.association||null,交付物:row?.title||'',关联节点:row?.flowNodeIds||[],负责人:row?.ownerId||row?.executorId||row?.owner||'',计划日期:row?.plannedEnd||'',要求日期:row?.dueAt||row?.deadline||'',交付要求:row?.description||''};};
const fingerprint=m=>digest([m.workItemId,m.targetId,m.nodeId,m.recipient,m.text,m.purpose,m.proof,m.dependsOnAdmission,m.targetBasis]);

/** P5 messages use the existing reminderRun ledger and Feishu client. */
export class CoreCollaboration {
  constructor({store,domain,client,clock=()=>Date.now(),mode='disabled',refresh}){Object.assign(this,{store,domain,client,clock,mode,refresh});this.jobs=new Map();}
  stamp(){return new Date(this.clock()).toISOString();}
  run(workspaceId,sourceId){const s=this.store.load(workspaceId),source=s.sources.find(x=>x.id===sourceId&&!x.archived&&x.reminderRun?.core);if(!source)throw fail('没有对应协作批次',404);return {s,source,run:source.reminderRun};}
  update(workspaceId,sourceId,fn){return this.store.transaction(()=>{const {s,source,run}=this.run(workspaceId,sourceId),before=s.revision,snapshot=JSON.stringify(s);fn(run,s);if(JSON.stringify(s)===snapshot)return {source,state:s};source.version++;source.updatedAt=this.stamp();s.revision++;const errors=this.domain.validateState(s);if(errors.length)throw fail(errors.map(e=>e.message).join('；'),422);this.store.save(s,before);return {source,state:this.store.load(workspaceId)};});}
  recipient(s,id,identity,channel='private'){
    if(channel==='group'){
      const scope=s.sources.find(x=>x.chatScope?.state==='active'&&x.chatScope.chatId===id&&x.chatScope.scope===identity.scope);
      if(!scope)throw fail('群身份及项目范围尚未核实');return {id,channel:'group',name:scope.title,scope:identity.scope,projectIds:scope.projectIds};
    }
    const p=s.people.find(p=>p.id===id&&!p.archived);
    if(!p?.identityVerified||p.feishuAppId!==identity.appId||p.feishuTenantKey!==identity.tenantKey||!/^ou_[\w-]+$/.test(p.feishuUserId||''))throw fail('接收人的当前飞书身份尚未核实');
    return {id:p.feishuUserId,localId:p.id,channel:'private',name:p.title,appId:identity.appId,tenantKey:identity.tenantKey};
  }
  async resolveRecipient({workspaceId,personId,query}){
    const state=this.store.load(workspaceId),person=state.people.find(p=>p.id===personId&&!p.archived);if(!person)throw fail('没有对应责任人');
    if(state.workspaceType==='restored')throw fail('恢复工作区不能改变人员身份');
    const value=(query||person.title).trim();if(value.length<2||value.length>80)throw fail('请提供完整姓名或工作邮箱',422);
    if(!this.client.resolveOwner)throw fail('当前人员查询通道不可用',503);
    const identity=await this.client.identity(),resolved=await this.client.resolveOwner(value.includes('@')?{email:value}:{name:value});
    if(!/^ou_[\w-]+$/.test(resolved.userId||''))throw fail('尚未取得唯一的飞书用户身份');
    const afterIdentity=await this.client.identity();if(identity.scope!==afterIdentity.scope||identity.userId!==afterIdentity.userId)throw fail('人员查询期间账号变化');
    return this.store.transaction(()=>{const s=this.store.load(workspaceId),current=s.people.find(p=>p.id===personId&&!p.archived);if(!current||current.version!==person.version)throw fail('人员记录已变化');Object.assign(current,{identityVerified:true,feishuUserId:resolved.userId,feishuIdType:'open_id',feishuAppId:identity.appId,feishuTenantKey:identity.tenantKey,identityVerifiedAt:this.stamp(),identityQuery:value});current.version++;s.revision++;s.audit.push({id:'core-person-'+randomUUID(),time:this.stamp(),operation:'core.person.resolve',objectId:personId,actor:'本人查询',before:null,after:{identityVerified:true,scope:identity.scope},revision:s.revision});this.store.save(s,s.revision-1);return {personId,identityVerified:true};});
  }
  async prepare({workspaceId,messages,requestId}){
    if(!Array.isArray(messages)||!messages.length||messages.length>20||!requestId)throw fail('请选择 1–20 条完整消息',422);
    const identity=await this.client.identity(),sourceId='reminder-core-'+digest([workspaceId,requestId]).slice(0,32);
    return this.store.transaction(()=>{
      const s=this.store.load(workspaceId);if(s.workspaceType==='restored')throw fail('恢复工作区不准备真实协作');
      const intent=digest(messages),receiptKey='core-preview:'+requestId,receipt=s.receipts[receiptKey],old=s.sources.find(x=>x.id===(receipt?.result?.sourceId||sourceId));
      if(receipt&&receipt.fingerprint!==intent)throw fail('同一预览请求不能更改内容');
      if(old){if(old.reminderRun.intentHash!==intent)throw fail('同一请求不能更改内容');return {source:old,state:s};}
      const prepared=messages.map((m,index)=>{
        const row=s.sources.find(x=>x.id===m.workItemId&&x.workItem&&!x.archived);
        if(!row||typeof m.text!=='string'||!m.text.trim()||m.text.length>4000||!this.domain.validCoreProofs(s,m.proof))throw fail('消息缺少正确事项、完整正文或有效来源',422);
        if(m.targetId&&!s.deliverables.some(d=>d.id===m.targetId&&!d.archived&&d.projectIds.some(p=>row.projectIds.includes(p))))throw fail('报告与事项项目不一致');
        const knownTarget=row.workItem.core?.delivery?.targetId||(row.workItem.businessTarget?.kind==='deliverables'?row.workItem.businessTarget.id:'');
        if(m.targetId&&knownTarget&&m.targetId!==knownTarget)throw fail('这条消息属于另一份报告，请使用其对应事项');
        const recipient=this.recipient(s,m.recipientId,identity,m.channel);if(recipient.channel==='group'&&!recipient.projectIds.some(id=>row.projectIds.includes(id)))throw fail('群与当前事项项目的关系尚未核实');
        const item={...m,id:sourceId+':'+index,key:randomUUID(),recipient,text:m.text.trim(),dependsOnAdmission:m.dependsOnAdmission===true,proof:structuredClone(m.proof),stage:'pending_review',executionOwner:'ai',approvedHash:'',approvalHistory:[],events:[],needsRecheck:false};
        item.targetSnapshot=targetSnapshot(s,item);item.targetBasis=digest(item.targetSnapshot);item.fingerprint=fingerprint(item);return item;
      });
      const existing=s.sources.find(r=>r.reminderRun?.core&&!r.archived&&r.reminderRun.intentHash===intent&&r.reminderRun.identity.scope===identity.scope&&r.reminderRun.identity.userId===identity.userId&&!r.reminderRun.items.every(m=>['readback_verified','cancelled','stopped'].includes(m.stage)));
      if(existing){s.receipts[receiptKey]={fingerprint:intent,result:{sourceId:existing.id,reused:true}};s.revision++;this.store.save(s,s.revision-1);return {source:existing,state:this.store.load(workspaceId)};}
      const at=this.stamp(),run={schemaVersion:1,approvalVersion:4,core:true,workspaceId,identity,createdAt:at,status:'pending_review',intentHash:intent,items:prepared,messages:prepared};
      // Messages and items have one persisted identity; access always goes via items.
      const source={id:sourceId,title:'待预览协作 · '+prepared.length+' 条',projectIds:[...new Set(prepared.flatMap(m=>s.sources.find(x=>x.id===m.workItemId).projectIds))],sourceIds:[...new Set(prepared.flatMap(m=>m.proof.map(p=>p.sourceId)))],objectIds:[...new Set(prepared.map(m=>m.workItemId))],type:'提醒执行记录',excerpt:'不同报告分别发送；逐条预览后确认保留项',version:1,collectedAt:at,reminderRun:run};
      s.sources.push(source);s.receipts[receiptKey]={fingerprint:intent,result:{sourceId}};s.revision++;s.audit.push({id:sourceId,time:at,operation:'core.messages.prepare',objectId:sourceId,actor:'助手',before:null,after:{externalWrite:false,items:prepared.length},revision:s.revision});this.store.save(s,s.revision-1);return {source,state:this.store.load(workspaceId)};
    });
  }
  decide({workspaceId,sourceId,requestId,decisions=[],admissions=[]}){
    return this.update(workspaceId,sourceId,(run,s)=>{
      const receipt='core-approval:'+requestId,hash=digest({sourceId,decisions,admissions});
      if(s.receipts[receipt]){if(s.receipts[receipt].fingerprint!==hash)throw fail('同一确认请求内容已变化');return;}
      if(!requestId||!Array.isArray(decisions)||!Array.isArray(admissions)||new Set(decisions.map(d=>d.id)).size!==decisions.length)throw fail('确认范围无效',422);
      for(const a of admissions){const row=s.sources.find(r=>r.id===a.id&&r.workItem);if(!row||row.version!==a.expectedVersion)throw fail('候选已有变化');this.domain.applyCoreDecision(s,row,{action:'core-admit'},this.stamp());row.version++;}
      for(const d of decisions){
        const m=run.items.find(x=>x.id===d.id);if(!m||m.fingerprint!==d.fingerprint||!untouched(m))throw fail('预览已变化或消息已有执行记录');
        if(d.action==='edit'){
          if(typeof d.text!=='string'||!d.text.trim()||d.text.length>4000)throw fail('请保留完整有效正文',422);
          m.text=d.text.trim();if(d.recipientId)m.recipient=this.recipient(s,d.recipientId,run.identity,d.channel||m.recipient.channel);
          if(d.proof){if(!this.domain.validCoreProofs(s,d.proof))throw fail('新预览依据尚未有效');m.proof=structuredClone(d.proof);}
          const previousTarget=m.targetSnapshot;m.targetSnapshot=targetSnapshot(s,m);m.targetBasis=digest(m.targetSnapshot);
          m.previewChanges={previous:{...(m.approvalHistory.at(-1)||{}),target:previousTarget},current:{recipient:m.recipient,text:m.text,proof:m.proof,target:m.targetSnapshot}};
          m.fingerprint=fingerprint(m);m.approvedHash='';m.stage='pending_review';
        }else if(d.action==='cancel'){m.stage='cancelled';m.events.push({at:this.stamp(),kind:'cancelled',reason:d.reason||'本人取消这条消息'});}
        else if(d.action==='approve'){
          if(m.dependsOnAdmission&&s.sources.find(r=>r.id===m.workItemId)?.workItem.core?.admission==='candidate')throw fail('该消息需要先纳入对应事项；其他无前置的消息可单独确认');
          if(!this.domain.validCoreProofs(s,m.proof))throw fail('来源已变化，请重新完整预览');
          m.approvedHash=m.fingerprint;m.stage='approved';m.approvalHistory.push({at:this.stamp(),fingerprint:m.fingerprint,recipient:m.recipient,text:m.text,proof:m.proof});
        }else throw fail('不支持的预览决定',422);
      }
      run.messages=structuredClone(run.items);s.receipts[receipt]={fingerprint:hash,result:{sourceId,decisions:decisions.map(d=>({id:d.id,action:d.action})),admissions:admissions.map(a=>a.id)}};
      s.audit.push({id:receipt,time:this.stamp(),operation:'core.messages.decide',objectId:sourceId,actor:'本人',before:null,after:s.receipts[receipt].result,revision:s.revision+1});
    });
  }
  authority({workspaceId,sourceId,messageId,expectedFingerprint,action}){
    return this.update(workspaceId,sourceId,(run)=>{const m=run.items.find(x=>x.id===messageId);if(!m||m.fingerprint!==expectedFingerprint)throw fail('操作范围已变化');if(!['takeover','release'].includes(action))throw fail('请选择明确接手或交回');m.executionOwner=action==='takeover'?'human':'ai';m.events.push({at:this.stamp(),kind:action});run.messages=structuredClone(run.items);});
  }
  check(s,m){
    const row=s.sources.find(x=>x.id===m.workItemId&&x.workItem&&!x.archived);
    if(!row)return {stage:'blocked',reason:'原事项不可读取，尚未核实必要性'};
    if(m.recipient.channel==='private'){
      const person=s.people.find(p=>p.id===m.recipient.localId&&!p.archived);
      if(!person?.identityVerified||person.feishuUserId!==m.recipient.id||person.feishuAppId!==m.recipient.appId||person.feishuTenantKey!==m.recipient.tenantKey)return {stage:'needs_preview',reason:'接收人身份或所属账号范围已变化'};
    }else if(!s.sources.some(r=>r.chatScope?.state==='active'&&r.chatScope.chatId===m.recipient.id&&r.chatScope.scope===m.recipient.scope&&r.projectIds.some(p=>row.projectIds.includes(p))))return {stage:'needs_preview',reason:'群身份或与当前项目的关系已变化'};
    const c=row.workItem.core,delivery=c?.delivery;
    const finished=delivery?.targetId===m.targetId&&delivery.delivered&&this.domain.validCoreProofs(s,delivery.proof)||row.workItem.p1?.lifecycle?.state==='closed'&&c?.assessment?.goalSatisfied&&this.domain.validCoreProofs(s,c.assessment.proof);
    if(finished)return {stage:'stopped',reason:'可靠新事实表明这条协作已无必要'};
    if(row.workItem.p1?.lifecycle?.state==='closed')return {stage:'needs_preview',reason:'本人已结束本地跟进，请核对这条未执行协作是否仍需要'};
    if(m.targetBasis!==digest(targetSnapshot(s,m)))return {stage:'needs_preview',reason:'关联对象、负责人、业务日期或交付要求已变化'};
    if(!this.domain.validCoreProofs(s,m.proof))return {stage:'needs_preview',reason:'相关来源或关键前提已经变化，请重新完整预览'};
    if(m.approvedHash!==fingerprint(m))return {stage:'needs_preview',reason:'正文、收件人或批准范围已变化'};
    if(m.dependsOnAdmission&&c?.admission!=='managed')return {stage:'blocked',reason:'具体前置纳入决定尚未生效'};
    return {stage:'ready'};
  }
  recheckPrepared({workspaceId,sourceId}){
    const {s,run}=this.run(workspaceId,sourceId),changes=[];
    for(const m of run.items){if(!untouched(m)||['cancelled','stopped'].includes(m.stage))continue;const c=this.check(s,m);if(c.stage==='stopped'||c.stage==='needs_preview'&&m.stage!=='pending_review'&&m.stage!=='needs_preview')changes.push({id:m.id,...c});}
    if(!changes.length)return;
    return this.update(workspaceId,sourceId,r=>{for(const change of changes){const m=r.items.find(x=>x.id===change.id);m.stage=change.stage;m.events.push({at:this.stamp(),kind:change.stage,reason:change.reason});}r.messages=structuredClone(r.items);});
  }
  execute(input){
    const key=input.workspaceId+':'+input.sourceId;if(this.jobs.has(key))return this.jobs.get(key);
    const task=this.send(input).finally(()=>this.jobs.delete(key));this.jobs.set(key,task);return task;
  }
  async send({workspaceId,sourceId}){
    if(this.mode==='disabled')throw fail('协作发送尚未启用；预览与批准已保存',503);
    const initial=this.run(workspaceId,sourceId);if(initial.s.workspaceType==='restored')throw fail('恢复工作区不重放外发');
    const identity=await this.client.identity();if(identity.scope!==initial.run.identity.scope||identity.userId!==initial.run.identity.userId)throw fail('账号已变化，原批准不适用');
    for(const original of initial.run.items){
      let {s,run}=this.run(workspaceId,sourceId),m=run.items.find(x=>x.id===original.id);
      if(m.executionOwner==='human'||!['approved','failed_not_sent'].includes(m.stage))continue;
      try{await this.refresh?.({workspaceId,workItemId:m.workItemId,targetId:m.targetId});}catch(error){this.update(workspaceId,sourceId,r=>{const x=r.items.find(i=>i.id===m.id);x.error='发前读取失败，尚未核实：'+error.message;});continue;}
      ({s,run}=this.run(workspaceId,sourceId));m=run.items.find(x=>x.id===original.id);
      if(m.executionOwner==='human'||!['approved','failed_not_sent'].includes(m.stage))continue;
      const check=this.check(s,m);
      if(check.stage!=='ready'){this.update(workspaceId,sourceId,r=>{const x=r.items.find(i=>i.id===m.id);x.stage=check.stage;x.events.push({at:this.stamp(),kind:check.stage,reason:check.reason});});continue;}
      const currentIdentity=await this.client.identity();if(currentIdentity.scope!==run.identity.scope||currentIdentity.userId!==run.identity.userId)throw fail('发送前账号已变化');
      let claimed=false;
      this.update(workspaceId,sourceId,(r,state)=>{const x=r.items.find(i=>i.id===m.id);if(x.executionOwner==='human'||!['approved','failed_not_sent'].includes(x.stage)||this.check(state,x).stage!=='ready')return;x.stage='sending';x.attemptedAt=this.stamp();x.attempts=(x.attempts||0)+1;claimed=true;});
      if(!claimed)continue;
      try{
        const sent=await this.client.run(['im','+messages-send',m.recipient.channel==='group'?'--chat-id':'--user-id',m.recipient.id,'--text',m.text,'--idempotency-key',m.key,'--as','user']);
        const messageId=sent?.message_id||sent?.message?.message_id;if(!messageId)throw fail('没有返回可回读的消息身份');
        this.update(workspaceId,sourceId,r=>Object.assign(r.items.find(i=>i.id===m.id),{messageId,stage:'sent',sentAt:this.stamp(),sendReceipt:sent,error:''}));
        await this.reconcileOne(workspaceId,sourceId,m.id);
        }catch(error){this.update(workspaceId,sourceId,r=>{const x=r.items.find(i=>i.id===m.id);x.stage=error.definitelyNotSent===true&&!x.messageId?'failed_not_sent':'unknown';x.error=error.message;x.retryAfter=new Date(this.clock()+60000*Math.min(60,2**Math.min(x.attempts||1,6))).toISOString();});}
    }
    return this.update(workspaceId,sourceId,r=>{r.messages=structuredClone(r.items);r.status=r.items.every(m=>['readback_verified','cancelled','stopped'].includes(m.stage))?'readback_verified':r.items.some(m=>['unknown','sending','sent'].includes(m.stage))?'needs_reconcile':'partial';});
  }
  async reconcileOne(workspaceId,sourceId,messageId){
    const {run,s}=this.run(workspaceId,sourceId),m=run.items.find(x=>x.id===messageId);if(!m)throw fail('没有这条消息');
    if(s.workspaceType==='restored')throw fail('恢复记录仅保留历史');
    const identity=await this.client.identity();if(identity.scope!==run.identity.scope||identity.userId!==run.identity.userId)throw fail('回读账号变化');
    if(m.stage==='readback_verified')return;
    if(!m.messageId){
      const found=await this.client.lookupByKey?.(m.key);
      if(found?.status==='not_sent'&&found.verified===true){this.update(workspaceId,sourceId,r=>Object.assign(r.items.find(x=>x.id===m.id),{stage:'failed_not_sent',error:'已核实未发出'}));return;}
      if(!found?.messageId)throw fail('结果未知，缺少可查询的消息身份；保留原请求，不自动重发');
      m.messageId=found.messageId;this.update(workspaceId,sourceId,r=>{r.items.find(x=>x.id===m.id).messageId=m.messageId;});
    }
    const response=await this.client.run(['im','+messages-mget','--message-ids',m.messageId,'--no-reactions','--as','user']),remote=response?.messages?.find(x=>x.message_id===m.messageId);
    if(!remote||remote.msg_type!=='text'||remote.content!==m.text||!Object.values(remote.sender||{}).includes(identity.userId))throw fail('回读尚未匹配原发送人及完整正文');
    if(remote.chat_id&&m.recipient.channel==='group'&&remote.chat_id!==m.recipient.id)throw fail('回读消息群身份不一致');
    this.update(workspaceId,sourceId,r=>{const x=r.items.find(i=>i.id===m.id);Object.assign(x,{stage:'readback_verified',readback:remote,readAt:this.stamp(),error:''});x.events.push({at:this.stamp(),kind:'readback_verified',meaning:'发送事实；不表示已读、知晓、认可或业务完成'});r.messages=structuredClone(r.items);});
  }
  async reconcile({workspaceId,sourceId}){const {run}=this.run(workspaceId,sourceId);for(const m of run.items)if(['unknown','sending','sent'].includes(m.stage))try{await this.reconcileOne(workspaceId,sourceId,m.id);}catch(error){this.update(workspaceId,sourceId,r=>{r.items.find(x=>x.id===m.id).error=error.message;});}return this.run(workspaceId,sourceId).source;}
  async close(){await Promise.allSettled([...this.jobs.values()]);}
}
