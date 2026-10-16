import {digest} from './direct-dm-authority.mjs';
import {normalizeDmMessage} from './direct-dm-isolation.mjs';
// Trusted local composition only; never accepts approval fields from an event.
export class DirectDmController {
 constructor({gate,authority,transport}={}){Object.assign(this,{gate,authority});Object.defineProperty(this,'transport',{value:transport,enumerable:true});this.closed=false;this.active=new Set();this.jobs=new Set();}
 current(m){if(this.closed)throw Error('DM_EXECUTION_STOPPED');const policy=this.authority.current(m);this.gate.policy(m,policy);return policy;}
 register(manifest){if(this.closed)throw Error('DM_EXECUTION_STOPPED');return this.authority.admit(manifest);}
 track(job){this.jobs.add(job);job.finally(()=>this.jobs.delete(job)).catch(()=>{});return job;}
 deliver(id,kind){return this.track(this._deliver(id,kind));}
 async _deliver(id,kind){
  const m=this.gate.request(id).manifest;
  const payload=this.gate.reserveEffect(id,kind,this.current(m)),abort=new AbortController();this.active.add(abort);
  try{
   const receipt=await this.transport.send(payload,{signal:abort.signal,idempotencyKey:digest(id+':'+kind).slice(0,48),beforeSend:()=>{
    this.current(m);if(this.gate.request(id).state!==(kind==='preview'?'PREVIEW_PENDING':'DELIVERY_PENDING'))throw Error('DM_EXECUTION_STOPPED');
   }});
   this.gate.recordEffect(id,kind,receipt);
   try{const read=await this.transport.read(receipt.messageId,{signal:abort.signal});this.gate.readbackEffect(id,kind,read);}
   catch(error){this.gate.readbackEffect(id,kind,{});throw error;}
   return this.gate.status(id);
  }catch(error){
   const effect=this.gate.db.prepare('SELECT state FROM effects WHERE request_id=? AND kind=?').get(id,kind);
   if(effect?.state==='SENDING')this.gate.recordEffect(id,kind,{});
   this.gate.event(id,'ADAPTER_OPERATION_FAILED',{kind,code:String(error.message).slice(0,100),at:this.gate.clock()});throw error;
  }finally{this.active.delete(abort);}
 }
 handle({identity,message}){return this.track(this._handle({identity,message}));}
 async _handle({identity,message}){
  const match=this.gate.classify(identity,message);if(!match)return {held:false};
  this.gate.hold({identity,message,channel:'trusted_controller'});
  const id=match.requestId,r=this.gate.request(id),e=normalizeDmMessage(message);
  if(r.state!=='AWAITING_CONFIRMATION'||e.senderId!==r.manifest.participantId||e.chatId!==r.manifest.participantChatId)return {held:true,executed:false};
  try{
   // First enforce expiry, signature and current installed binding. The
   // asynchronous original-message read then rechecks all gates in confirm().
   this.current(r.manifest);
   const result=await this.gate.confirm(id,message,{identity,verify:(messageId,options)=>this.transport.read(messageId,options),current:()=>this.current(r.manifest)});
   if(result==='CONFIRMED')await this.deliver(id,'summary');
   return {held:true,state:this.gate.status(id).state};
  }catch(error){this.gate.event(id,'CONFIRMATION_NOT_EXECUTED',{code:String(error.message).slice(0,100),at:this.gate.clock()});return {held:true,executed:false,error:error.message};}
 }
 async close(){this.closed=true;for(const a of this.active)a.abort();await Promise.allSettled([...this.jobs]);}
}
