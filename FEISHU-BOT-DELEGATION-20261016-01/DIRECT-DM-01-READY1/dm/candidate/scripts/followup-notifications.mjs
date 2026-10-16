import {createHash} from 'node:crypto';
const fail=(message,status=409)=>Object.assign(Error(message),{status});
const digest=value=>createHash('sha256').update(value).digest('hex');

/** Browser/native display is a durable queue; queued never means the user saw it. */
export class DesktopNotificationQueue {
  constructor({store,domain,client}){Object.assign(this,{store,domain,client});}
  key(workspaceId){return 'followupDesktop:'+workspaceId;}
  rows(workspaceId){this.store.load(workspaceId);return this.store.getSetting(this.key(workspaceId))||[];}
  async identity(){const identity=await this.client.identity({signal:AbortSignal.timeout(12000)});return {channel:'desktop',selfId:identity.userId};}
  async send(input){
    const workspaceId=decodeURIComponent(input.itemKey.split(':')[0]),id='desktop-'+digest(input.key);
    return this.store.transaction(()=>{
      const rows=this.rows(workspaceId);let row=rows.find(row=>row.id===id);
      if(!row){row={...input,id,workspaceId,delivery:'queued',createdAt:new Date().toISOString()};rows.push(row);this.store.setSetting(this.key(workspaceId),rows);}
      return {id,workspaceId,selfId:row.selfId,basis:row.basis,delivery:row.delivery};
    });
  }
  async readback(receipt){const row=this.rows(receipt.workspaceId).find(row=>row.id===receipt.id);if(!row)throw fail('电脑提醒队列尚未回读',503);return {id:row.id,selfId:row.selfId,basis:row.basis,delivery:row.delivery};}
  list(workspaceId){if(this.store.load(workspaceId).workspaceType==='restored')return [];return this.rows(workspaceId).map(({id,title,body,basis,delivery,claimId,createdAt})=>({id,title,body,basis,delivery,claimId,createdAt}));}
  update({workspaceId,id,claimId,action}){
    if(this.store.load(workspaceId).workspaceType==='restored')throw fail('恢复工作区不能重新展示旧通知',403);
    if(typeof claimId!=='string'||!/^[a-zA-Z0-9-]{10,100}$/.test(claimId))throw fail('电脑提醒缺少稳定展示标识',422);
    if(!['claim','submitted','denied','failed'].includes(action))throw fail('不支持的电脑提醒操作',422);
    return this.store.transaction(()=>{
      const rows=this.rows(workspaceId),row=rows.find(row=>row.id===id);if(!row)throw fail('没有该电脑提醒',404);
      const previous=JSON.stringify(row),previousDelivery=row.delivery;
      if(action==='claim'){
        if(row.delivery==='queued'){row.claimId=claimId;row.delivery='claimed';row.claimedAt=new Date().toISOString();}
        else if(row.claimId!==claimId)throw fail('其他窗口已领取这条提醒');
      }else{
        if(row.claimId!==claimId)throw fail('展示回执与领取窗口不匹配');
        if(row.delivery!=='claimed'&&row.delivery!==action)throw fail('展示回执已保存，不能改写');
        row.delivery=action;row.finishedAt ||= new Date().toISOString();
      }
      if(previous===JSON.stringify(row))return {id:row.id,delivery:row.delivery,claimId:row.claimId};
      this.store.setSetting(this.key(workspaceId),rows);
      const before=this.store.load(workspaceId),next=structuredClone(before);
      const source=next.sources.find(s=>s.followupNotification?.channels.desktop?.receipt?.id===id);
      if(source){const at=row.finishedAt||row.claimedAt;source.followupNotification.channels.desktop.readback={...source.followupNotification.channels.desktop.readback,id,selfId:row.selfId,basis:row.basis,delivery:row.delivery,displayReceiptAt:at};if(source.followupNotification.core&&row.delivery==='submitted'){const target=next.sources.find(r=>r.id===source.followupNotification.workItemId);if(target&&this.domain?.countCoreNotice(target,source.followupNotification.notice,at))target.version++;}source.version++;source.updatedAt=at;next.revision++;next.audit.push({id:'desktop-receipt-'+id+'-'+row.delivery,time:at,operation:'followup.desktop.receipt',objectId:source.id,actor:'电脑通知展示窗口',before:previousDelivery,after:row.delivery,revision:next.revision});this.store.save(next,before.revision);}
      return {id:row.id,delivery:row.delivery,claimId:row.claimId};
    });
  }
}

export function validateDesktopNotifications(value,workspaceId){
  if(!Array.isArray(value)||value.some(row=>!row||row.workspaceId!==workspaceId||typeof row.id!=='string'||!row.id.startsWith('desktop-')||typeof row.title!=='string'||typeof row.body!=='string'||typeof row.basis!=='string'||!['queued','claimed','submitted','denied','failed','historical'].includes(row.delivery)))throw fail('电脑通知队列备份无效或跨工作区',400);
}

/** Sends only to the current authenticated user and verifies sender/text/id. */
export function feishuSelfNotification(client){
  return {
    async identity(){const identity=await client.identity({signal:AbortSignal.timeout(12000)});return {channel:'feishu_self',selfId:identity.userId};},
    async send(input){
      const identity=await client.identity({signal:AbortSignal.timeout(12000)});if(identity.userId!==input.selfId)throw fail('本人提醒账号已变化');
      const text='【需要你介入】'+input.title+'\n'+input.body;
      const result=await client.run(['im','+messages-send','--user-id',identity.userId,'--text',text,'--idempotency-key',digest(input.key).slice(0,40),'--as','user'],{signal:AbortSignal.timeout(35000)});
      if(!result?.message_id)throw fail('本人提醒返回缺少消息ID；先核对，不能重发');
      return {id:result.message_id,selfId:identity.userId,scope:identity.scope,basis:input.basis,text};
    },
    async readback(receipt){
      const identity=await client.identity({signal:AbortSignal.timeout(12000)});if(identity.userId!==receipt.selfId||identity.scope!==receipt.scope)throw fail('本人提醒回读账号已变化');
      const value=await client.run(['im','+messages-mget','--message-ids',receipt.id,'--no-reactions','--as','user'],{signal:AbortSignal.timeout(35000)}),row=value?.messages?.find(row=>row.message_id===receipt.id);
      if(!row||row.msg_type!=='text'||row.content!==receipt.text||!Object.values(row.sender||{}).includes(receipt.selfId))throw fail('本人提醒未回读到同一消息、发送人和正文');
      return {id:receipt.id,selfId:receipt.selfId,basis:receipt.basis,delivery:'message_readback_verified'};
    },
  };
}

/** Only current urgent projections in official workspaces enter automatic delivery. */
export class FollowupNotificationPump {
  constructor({store,followups,client}){Object.assign(this,{store,followups,client});this.closed=false;this.pending=null;}
  async tick(){
    if(this.closed||this.pending)return this.pending;
    this.pending=(async()=>{
      for(const workspace of this.store.list().filter(w=>w.type==='official')){
        if(this.closed)break;
        const snapshot=this.store.load(workspace.id);
        const urgent=this.followups.list(workspace.id).allAttention.filter(item=>!snapshot.sources.some(r=>r.id===item.followup?.targetId&&r.workItem?.core)&&item.urgent&&item.followup?.active&&!item.followup?.suppressNotification);
        if(!urgent.length)continue;
        try{
          const identity=await this.client.identity({signal:AbortSignal.timeout(12000)});
          for(const item of urgent){if(this.closed)break;await this.followups.notify({workspaceId:workspace.id,kind:item.followup.kind,targetId:item.followup.targetId,selfId:identity.userId});}
          this.store.setSetting('followupNotificationStatus:'+workspace.id,{at:new Date().toISOString(),error:''});
        }catch(error){this.store.setSetting('followupNotificationStatus:'+workspace.id,{at:new Date().toISOString(),error:error.message});}
      }
    })().finally(()=>{this.pending=null;});return this.pending;
  }
  start(){this.timer=setInterval(()=>void this.tick(),30000);this.timer.unref();}
  async close(){this.closed=true;clearInterval(this.timer);await this.pending;await Promise.allSettled([...this.followups.jobs.values()]);}
}
