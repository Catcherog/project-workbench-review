import {createHash,randomUUID} from 'node:crypto';
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const fail=(message,status=409)=>Object.assign(new Error(message),{status});

/** Existing LocalStore owns persistence; all adapters are injected. No CLI default. */
export class FollowupService {
  constructor({store,domain,clock=()=>Date.now(),notifications={}}){Object.assign(this,{store,domain,clock,notifications});this.jobs=new Map();}
  project(s,ref){return this.domain.buildFollowup(s,ref,this.clock());}
  context(s,ref){return this.domain.followupContext(this.project(s,ref),s);}
  list(workspaceId){const s=this.store.load(workspaceId);return this.domain.buildWorkbenchOverview(s,this.domain.followupDay(this.clock()),this.clock());}
  operate(input){return this.store.transaction(()=>{
    const before=this.store.load(input.workspaceId),next=this.domain.applyFollowupOperation(before,input,this.clock());
    if(next!==before)this.store.save(next,before.revision);
    const state=this.store.load(input.workspaceId);return {state,item:this.project(state,input)};
  });}
  notificationRecord(workspaceId,id,mutate){return this.store.transaction(()=>{
    const before=this.store.load(workspaceId),next=structuredClone(before),src=next.sources.find(s=>s.id===id);
    if(!src)throw fail('通知回执不存在',404);
    const prior=structuredClone(src.followupNotification.channels);mutate(src.followupNotification);src.version++;next.revision++;
    next.audit.push({id:'followup-notification-'+next.revision,time:new Date(this.clock()).toISOString(),operation:'followup.notification',objectId:id,actor:'本人紧急通知适配器',before:prior,after:src.followupNotification.channels,revision:next.revision});
    this.store.save(next,before.revision);return src.followupNotification;
  });}
  /** Local/Feishu-self adapters must declare both identity and persisted readback. */
  notify({workspaceId,kind,targetId,selfId}){
    if(this.core&&kind==='sources'&&this.store.load(workspaceId).sources.find(r=>r.id===targetId)?.workItem?.core)return this.core.notify(workspaceId,targetId);
    if(!selfId)throw fail('本人通知身份尚未核对',422);
    const p=this.project(this.store.load(workspaceId),{kind,targetId}),key=workspaceId+':'+p.itemKey;
    if(this.jobs.has(key))return this.jobs.get(key);
    const job=this.executeNotification({workspaceId,kind:p.kind,targetId:p.targetId,selfId}).finally(()=>this.jobs.delete(key));
    this.jobs.set(key,job);return job;
  }
  async executeNotification({workspaceId,kind,targetId,selfId}){
    const state=this.store.load(workspaceId),p=this.project(state,{kind,targetId});
    if(!p.urgent||!p.active||p.suppressNotification||state.workspaceType==='restored')return {status:'quiet',reason:'当前没有需要主动通知的紧急变化，或处于恢复检查工作区'};
    const id='followup-notice-'+hash([workspaceId,p.itemKey,p.notificationBasis,selfId]).slice(0,40);
    let record=state.sources.find(s=>s.id===id)?.followupNotification;
    // Each channel persists its intent BEFORE invoking an adapter. A crash is unknown.
    if(!record)this.store.transaction(()=>{
      const before=this.store.load(workspaceId),next=structuredClone(before);
      if(next.sources.some(s=>s.id===id))return;
      record={schemaVersion:1,workspaceId,itemKey:p.itemKey,basis:p.notificationBasis,selfId,createdAt:new Date(this.clock()).toISOString(),channels:{desktop:{stage:'pending'},feishu_self:{stage:'pending'}}};
      next.sources.push({id,title:'本人紧急通知 · '+p.title,projectIds:p.projectIds,sourceIds:p.sources.map(s=>s.id),objectIds:[p.targetId],version:1,confirmed:false,followupNotification:record});
      next.revision++;this.store.save(next,before.revision);
    });
    for(const name of ['desktop','feishu_self']){
      record=this.store.load(workspaceId).sources.find(s=>s.id===id).followupNotification;
      const adapter=this.notifications[name],channel=record.channels[name];
      if(channel.stage!=='pending'||!adapter)continue;
      const current=this.project(this.store.load(workspaceId),{kind,targetId});
      if(!current.urgent||current.notificationBasis!==p.notificationBasis)break;
      const identity=await adapter.identity();
      if(identity.selfId!==selfId||identity.channel!==name)throw fail('本人通知适配器身份不匹配');
      const claim=randomUUID();
      const claimed=this.notificationRecord(workspaceId,id,r=>{if(r.channels[name].stage==='pending')r.channels[name]={stage:'sending',key:id+':'+name,claim};});
      if(claimed.channels[name].claim!==claim)continue;
      try{
        const receipt=await adapter.send({key:id+':'+name,selfId,itemKey:p.itemKey,title:p.title,body:p.reason,basis:p.notificationBasis});
        if(!receipt?.id)throw fail('通知结果未返回可回读身份');
        this.notificationRecord(workspaceId,id,r=>{r.channels[name]={...r.channels[name],stage:'sent',receipt};});
        const readback=await adapter.readback(receipt);
        if(readback?.id!==receipt.id||readback?.selfId!==selfId||readback?.basis!==p.notificationBasis)throw fail('通知回读不匹配');
        this.notificationRecord(workspaceId,id,r=>{r.channels[name]={...r.channels[name],stage:'readback_verified',readback,error:''};});
      }catch(error){this.notificationRecord(workspaceId,id,r=>{r.channels[name]={...r.channels[name],stage:'needs_reconcile',error:error.message};});}
    }
    return {sourceId:id,...this.store.load(workspaceId).sources.find(s=>s.id===id).followupNotification};
  }
  async reconcileNotification({workspaceId,sourceId}){
    const record=this.store.load(workspaceId).sources.find(s=>s.id===sourceId)?.followupNotification;
    if(!record||record.workspaceId!==workspaceId)throw fail('通知回执工作区不匹配');
    for(const [name,channel] of Object.entries(record.channels)){
      if(!['sent','sending','needs_reconcile'].includes(channel.stage))continue;
      if(!channel.receipt?.id)throw fail('缺少通知 ID，需人工核对；不会自动重发');
      const adapter=this.notifications[name];if(!adapter)throw fail('通知回读适配器不可用',503);
      const identity=await adapter.identity();if(identity.selfId!==record.selfId||identity.channel!==name)throw fail('通知回读身份变化');
      const readback=await adapter.readback(channel.receipt);
      if(readback?.id!==channel.receipt.id||readback?.selfId!==record.selfId||readback?.basis!==record.basis)throw fail('通知回读不匹配');
      this.notificationRecord(workspaceId,sourceId,r=>{r.channels[name]={...r.channels[name],stage:'readback_verified',readback,error:''};});
    }
    return this.store.load(workspaceId).sources.find(s=>s.id===sourceId).followupNotification;
  }
}
