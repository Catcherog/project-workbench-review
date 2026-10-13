import {createHash} from 'node:crypto';
import {captureCoreInput} from './core-input.mjs';
import {riskResourceCatalog} from './risk-evidence-reader.mjs';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const fail=message=>Object.assign(Error(message),{status:409});
export function mappedReply(state,messageId){
  if(!messageId)return '';
  const matches=[];
  for(const source of state.sources){
    if(source.inputEnvelope?.receipt?.id===messageId&&source.inputEnvelope.targetId)matches.push(source.inputEnvelope.targetId);
    const n=source.followupNotification;
    if(n?.core&&Object.values(n.channels).some(c=>c.receipt?.id===messageId))matches.push(n.workItemId);
    if(source.reminderRun?.core)for(const m of source.reminderRun.items)if(m.messageId===messageId)matches.push(m.workItemId);
    if(source.reminderRun&&!source.reminderRun.core)for(const m of source.reminderRun.messages||[])if(m.messageId===messageId&&m.targetId)matches.push(...state.sources.filter(r=>r.workItem?.businessTarget?.id===m.targetId&&!r.archived).map(r=>r.id));
  }
  const ids=[...new Set(matches)];return ids.length===1?ids[0]:'';
}
/** Receives only messages already authenticated and read back by the existing bridge. */
export class CoreFeishuInput {
  constructor({assistant,store,domain,client,reader}){Object.assign(this,{assistant,store,domain,client,reader});this.jobs=new Map();}
  update(workspaceId,sourceId,fn){return this.store.transaction(()=>{const s=this.store.load(workspaceId),source=s.sources.find(r=>r.id===sourceId);fn(source,s);source.version++;s.revision++;this.store.save(s,s.revision-1);return source;});}
  async resumeBudgetQueue(workspaceId){
    if(this.closed)return;
    const state=this.store.load(workspaceId);if(state.workspaceType==='restored')return;
    for(const source of state.sources.filter(r=>r.inputEnvelope?.origin==='feishu'&&r.inputEnvelope.actor!=='self'&&!r.inputEnvelope.restored&&!r.inputEnvelope.effectWithdrawn)){
      const e=source.inputEnvelope,previous=e.jobId?this.assistant.get(e.jobId,workspaceId):null,prepareOnly=previous?.status==='completed'&&previous.coreWorkOutcome?.failureCode==='AI_BUDGET';
      if(!prepareOnly&&!(previous?.status==='failed'&&previous.failureCode==='AI_BUDGET')&&e.failureCode!=='INPUT_BUSY')continue;
      if(this.assistant.aiUsage.budgetStatus().blocked){if(e.status!=='budget_wait')this.update(workspaceId,source.id,r=>{r.inputEnvelope.status='budget_wait';r.inputEnvelope.error='后台预算不足，原输入排队等待额度恢复';});continue;}
      const identity=await this.client.identity();if(identity.scope!==source.personalMessage.scope||identity.userId!==source.personalMessage.accountId)continue;
      await this.reader.verifyMessage(source,AbortSignal.timeout(30000));
      const attempt=(e.retryCount||0)+1,requestId=e.requestId+'-retry-'+attempt;
      const job=await this.assistant.start({workspaceId,requestId,sessionId:requestId,parentJobId:'',mode:'answer',text:'',prepareOnly,sourceIds:[source.id],coreInputSourceId:source.id,contextRef:{kind:'sources',id:e.targetId}});
      this.update(workspaceId,source.id,r=>{r.inputEnvelope.retryHistory=[...(r.inputEnvelope.retryHistory||[]),{jobId:e.jobId||'',reason:prepareOnly?'后续准备预算恢复':'输入预算或并发限制恢复'}];r.inputEnvelope.retryCount=attempt;r.inputEnvelope.jobId=job.id;r.inputEnvelope.status='processing';r.inputEnvelope.error='';r.inputEnvelope.failureCode='';});
    }
  }
  start(enabledWorkspaces){this.timer=setInterval(()=>{if(this.pending||this.closed)return;this.pending=(async()=>{for(const w of enabledWorkspaces())try{await this.resumeBudgetQueue(w.id);}catch(error){this.store.setSetting('coreInputError:'+w.id,{at:new Date().toISOString(),error:error.message});}})().finally(()=>{this.pending=null;});},30000);this.timer.unref();}
  async close(){this.closed=true;clearInterval(this.timer);await this.pending;}
  async receive({workspaceId,sourceId,identity,parentId,senderId}){
    const s=this.store.load(workspaceId),source=s.sources.find(r=>r.id===sourceId),targetId=source?.inputEnvelope?.associationDecision?.targetId||mappedReply(s,parentId);
    if(!source?.personalMessage||source.personalMessage.scope!==identity.scope||source.personalMessage.accountId!==identity.userId)throw fail('引用回复的读取身份不一致');
    if(source.inputEnvelope?.jobId)return {status:'received',jobId:source.inputEnvelope.jobId};
    if(!targetId){this.update(workspaceId,sourceId,row=>{row.inputEnvelope={...(row.inputEnvelope||{}),schemaVersion:1,origin:'feishu',actor:senderId===identity.userId?'self':'colleague',targetId:'',messageId:source.personalMessage.messageId,replyTo:parentId||'',status:'needs_association',reason:'引用消息尚未唯一关联事项；原文保留，未猜对象'};});return {status:'needs_association'};}
    const current=s.sources.find(r=>r.id===targetId&&r.workItem&&!r.archived);if(!current)throw fail('引用到的原事项暂不可用');
    const attachments=[];let attachmentError='';
    for(const resource of riskResourceCatalog(s,[{sourceId}],this.domain).filter(r=>r.kind==='attachment').slice(0,8)){
      try{const read=await this.reader.read({workspaceId,resource,signal:AbortSignal.timeout(45000)});for(const doc of read.documents||[])if(doc.original){const a=this.store.attach(workspaceId,{name:doc.original.name,mime:doc.original.mime,base64:doc.original.bytes.toString('base64')});attachments.push(a);}}
      catch(error){attachmentError=error.message;}
    }
    const live=this.store.load(workspaceId),row=live.sources.find(r=>r.id===targetId),state=this.domain.workItemState(live,row),self=senderId===identity.userId;
    // Each changed field is compared with its own later human decision. An
    // unrelated priority edit must not block a valid check-time reply.
    const late=false;
    const requestId='feishu-'+hash([identity.scope,identity.userId,source.personalMessage.messageId]).slice(0,40);
    let input={workspaceId,requestId,sessionId:requestId,contextRef:{kind:'sources',id:targetId},parentJobId:'',mode:'answer',sourceIds:[sourceId],text:self&&!late?source.excerpt:'',...(self&&!late?{p1Input:{occurredAt:source.occurredAt,expectedVersion:row.version,expectedBasis:state.basis,expectedEvidenceBasis:state.liveEvidenceBasis,manual:{}}}:{})};
    input=captureCoreInput(this.assistant,input,{verifiedSource:{...source,attachments,inputActor:self?'self':'colleague',replyTo:parentId}});
    this.update(workspaceId,sourceId,r=>{r.inputEnvelope.attachmentError=attachmentError;r.inputEnvelope.lateInstruction=!!late;});
    try{
      const job=await this.assistant.start(input);
      this.update(workspaceId,sourceId,r=>{r.inputEnvelope.jobId=job.id;r.inputEnvelope.status='processing';});
      return {status:'processing',jobId:job.id};
    }catch(error){this.update(workspaceId,sourceId,r=>{r.inputEnvelope.status=error.status===429?'waiting':'failed';r.inputEnvelope.failureCode=error.status===429?'INPUT_BUSY':'';r.inputEnvelope.error=error.message;});throw error;}
  }
  async associate({workspaceId,sourceId,targetId,expectedVersion}){
    const s=this.store.load(workspaceId),source=s.sources.find(r=>r.id===sourceId),target=s.sources.find(r=>r.id===targetId&&r.workItem&&!r.archived);
    if(!source?.personalMessage||!target||source.version!==expectedVersion||source.inputEnvelope?.status!=='needs_association')throw fail('待关联输入或目标已有变化');
    const identity=await this.client.identity();if(source.personalMessage.scope!==identity.scope||source.personalMessage.accountId!==identity.userId)throw fail('原输入账号与当前账号不同');
    this.update(workspaceId,sourceId,row=>{row.inputEnvelope.associationDecision={targetId,at:new Date().toISOString(),actor:'本人'};});
    return this.receive({workspaceId,sourceId,identity,parentId:source.inputEnvelope.replyTo,senderId:source.personalMessage.senderId});
  }
  /** Only the authenticated user's own reply receives an automatic private receipt. */
  async receipt({workspaceId,sourceId}){
    const s=this.store.load(workspaceId),source=s.sources.find(r=>r.id===sourceId),e=source?.inputEnvelope;
    if(!e?.jobId||e.restored)return {status:e?.status||'not_received'};
    const job=this.assistant.get(e.jobId,workspaceId);if(job.status==='running')return {status:'processing'};
    if(e.actor!=='self')return {status:'saved',outcome:job.coreOutcome||job.p1Outcome,receipt:'原事项可读；第三方新消息仍需预览'};
    if(e.receipt?.stage==='readback_verified')return e.receipt;
    const identity=await this.client.identity();if(identity.scope!==source.personalMessage.scope||identity.userId!==source.personalMessage.accountId)throw fail('回执身份变化');
    const text=job.status==='completed'?job.p1Outcome?.status==='saved'?'已记录到原事项：'+(job.p1Outcome.receipt.progress||'本次安排')+'。':job.p1Outcome?.status==='clarify'?'输入已保留，有具体差异需要你在工作台核对。':'本次资料已保留，理解结果可在原事项查看。':'本次尚未完成保存：'+(job.error||'处理失败')+'。原输入保留。';
    let receipt=e.receipt;
    const receiptKey=hash(['input-receipt',identity.scope,e.messageId]).slice(0,40);
    if(!receipt){this.update(workspaceId,sourceId,r=>{r.inputEnvelope.receipt={stage:'sending',key:receiptKey,text};});
      try{const sent=await this.client.run(['im','+messages-send','--user-id',identity.userId,'--text',text,'--idempotency-key',receiptKey,'--as','user']);if(!sent.message_id)throw fail('回执没有返回消息身份');receipt={stage:'sent',id:sent.message_id,text};this.update(workspaceId,sourceId,r=>{r.inputEnvelope.receipt=receipt;});}catch(error){this.update(workspaceId,sourceId,r=>{r.inputEnvelope.receipt={...r.inputEnvelope.receipt,stage:'unknown',error:error.message};});return this.store.load(workspaceId).sources.find(r=>r.id===sourceId).inputEnvelope.receipt;}}
    if(!receipt.id)return {stage:'unknown',reason:'回执结果待核实，未重发；本地保存状态独立保留'};
    const read=await this.client.run(['im','+messages-mget','--message-ids',receipt.id,'--no-reactions','--as','user']),message=read.messages?.find(m=>m.message_id===receipt.id);
    if(!message||message.content!==receipt.text||!Object.values(message.sender||{}).includes(identity.userId))throw fail('输入回执尚未读回相同发送人和正文');
    this.update(workspaceId,sourceId,r=>{r.inputEnvelope.receipt={...receipt,stage:'readback_verified',readback:message};});return {stage:'readback_verified',id:receipt.id};
  }
}
