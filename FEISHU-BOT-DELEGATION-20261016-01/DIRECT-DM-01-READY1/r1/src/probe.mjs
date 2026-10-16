import fs from 'node:fs';import {join} from 'node:path';import {randomUUID} from 'node:crypto';
import {Store} from './store.mjs';import {AdapterRuntime,rpcId} from './runtime.mjs';import {authenticated,exact,digest} from './codec.mjs';import {identity,checkIdentity,readPolicy,authorize,summaryId,action,purpose} from './policy.mjs';import {validateConfirmation,validateDelivery,humanProof} from './grant.mjs';
export class DelegationProbe{
 constructor({root,keys,clock=()=>Date.now()}){this.root=root;this.keys=keys;this.trust={bot:keys.bot.publicKey,human:keys.human.publicKey,receiver:keys.receiver.publicKey};this.clock=clock;this.runtime=new AdapterRuntime(join(root,'adapters.state'));this.store=new Store(join(root,'authority.sqlite'));this.transcript=[];this.closed=false;this.pending=new Set();
  for(const name of ['begin','answer','deliver','readback','bot','human','question']){const fn=this[name].bind(this);this[name]=(...args)=>{if(this.closed)return Promise.reject(Error('PROBE_STOPPED'));const p=Promise.resolve().then(()=>fn(...args)).catch(e=>{this.record('controller-rejected',{operation:name,code:e.message,protectedCounters:this.store.counts()});throw e;});this.pending.add(p);p.then(()=>this.pending.delete(p),()=>this.pending.delete(p));return p;};}
 }
 policy(){return readPolicy(join(this.root,'policy.json'));}
 status(id){return this.store.row(id)?.status;}
 counts(){return this.store.counts();}
 record(kind,value){this.transcript.push({kind,value});}
 async adapter(role,operation,extra={},options){const response=await this.runtime.call(role,{rpcId:rpcId(),operation,...extra},options);if(!response.ok)throw Error(response.code||'ADAPTER_REJECTED');return response;}
 async bot(payload,overrideKey){const r=await this.adapter('engineer','sign',{payload,privateKey:overrideKey||this.keys.bot.privateKey});this.record('bot-wire',r.envelope);return r.envelope;}
 async human(payload,overrideKey){const r=await this.adapter('human','sign',{payload,privateKey:overrideKey||this.keys.human.privateKey});this.record('synthetic-human-wire',r.envelope);return r.envelope;}
 async question(id){const r=await this.adapter('engineer','clarify');this.record('clarification',{requestId:id,question:r.question});return r.question;}
 async begin(envelope){
  if(this.closed)throw Error('PROBE_STOPPED');const p=authenticated(envelope,'bot',identity.bot,this.trust.bot);
  exact(p,['kind','requestId','nonce','tenant','app','bot','human','target','targetApp','text','hops']);if(p.kind!=='intent'||p.hops!==0||typeof p.requestId!=='string'||!p.requestId||typeof p.nonce!=='string'||!p.nonce||typeof p.text!=='string'||p.text.length>1000)throw Error('UNSUPPORTED_INTENT');checkIdentity(p,this.policy());
  const old=this.store.row(p.requestId);if(old){if(old.fingerprint!==digest(p))throw Error('SAME_ID_DIFFERENT_PAYLOAD');return {status:old.status,duplicate:true};}
  if(this.store.db.prepare('SELECT id FROM requests WHERE nonce=?').get(p.nonce))throw Error('NONCE_REPLAY');
  const now=this.clock(),data={intent:p,issuedAt:now,expiresAt:now+300000};this.store.db.prepare('INSERT INTO requests VALUES(?,?,?,?,?,?)').run(p.requestId,digest(p),p.nonce,'NEEDS_INFORMATION',JSON.stringify(data),1);this.store.event(p.requestId,'RECEIVED');this.store.event(p.requestId,'NEEDS_INFORMATION');return {status:'NEEDS_INFORMATION',question:await this.question(p.requestId)};
 }
 async answer(envelope,{relayed=false}={}){
  if(this.closed)throw Error('PROBE_STOPPED');if(relayed){const outer=authenticated(envelope,'bot',identity.bot,this.trust.bot);exact(outer,['kind','inner']);if(outer.kind!=='relay-human-answer')throw Error('UNSUPPORTED_MESSAGE_TYPE');envelope=outer.inner;}
  const p=humanProof(envelope,this.trust);exact(p,['kind','synthetic','human','requestId','intentHash','answers']);if(p.kind!=='answer'||p.synthetic!==true||p.human!==identity.human)throw Error('INVALID_HUMAN_RESPONSE');
  const row=this.store.row(p.requestId);if(!row||row.status!=='NEEDS_INFORMATION'||p.intentHash!==row.fingerprint)throw Error('ANSWER_BINDING_OR_STATE');
  if(this.clock()>=row.data.expiresAt){this.store.save(row.id,'EXPIRED');throw Error('EXPIRED');}
  const a=p.answers;exact(a,['resourceId','resourceVersion','recipient','purpose']);
  if(Object.values(a).some(x=>!x)){if(row.rounds>=2){this.store.save(row.id,'REJECTED');throw Error('CLARIFICATION_LIMIT');}this.store.save(row.id,'NEEDS_INFORMATION',row.data,row.rounds+1);return {status:'NEEDS_INFORMATION',question:await this.question(row.id)};}
  const policy=this.policy(),snapshot={protocol:'demo-delegation/v1',requestId:row.id,...identity,...a,action,body:'',contentSha256:'',policyVersion:policy.version,bindingVersion:policy.binding.version,issuedAt:row.data.issuedAt,expiresAt:row.data.expiresAt,nonce:row.nonce,confirmationRef:randomUUID(),hops:0};
  try{authorize(snapshot,policy,this.clock());}catch(e){this.store.save(row.id,'REJECTED');this.store.event(row.id,'DENIED_BEFORE_RESOURCE_READ',{reason:e.message,counts:this.counts()});throw e;}
  snapshot.body=fs.readFileSync(join(this.root,'resources/summary.txt'),'utf8').trim();this.store.add('summaryReads');snapshot.contentSha256=digest(snapshot.body);this.store.save(row.id,'AWAITING_CONFIRMATION',{...row.data,snapshot});this.store.event(row.id,'PREVIEW_CREATED',{snapshotHash:digest(snapshot),counts:this.counts()});this.record('exact-preview',snapshot);return {status:'AWAITING_CONFIRMATION',snapshot};
 }
 confirm(envelope){
  if(this.closed)throw Error('PROBE_STOPPED');const p=humanProof(envelope,this.trust),row=this.store.row(p.requestId);if(!row||row.status!=='AWAITING_CONFIRMATION')throw Error('CONFIRMATION_STATE');const proof=validateConfirmation(envelope,row.data.snapshot,this.trust,this.clock());
  authorize(row.data.snapshot,this.policy(),this.clock());const status=proof.decision==='approve'?'AUTHORIZED':'REJECTED';this.store.save(row.id,status,{...row.data,confirmation:envelope});this.store.event(row.id,status,{snapshotHash:digest(row.data.snapshot),synthetic:true});return {status};
 }
 async deliver(envelope,{timeoutMs=5000,afterCommitDelayMs=0,failReadback=false}={}){
  if(this.closed)throw Error('PROBE_STOPPED');const wire=authenticated(envelope,'bot',identity.bot,this.trust.bot);const id=wire.snapshot?.requestId;let row=this.store.row(id),snapshot;
  try{snapshot=validateDelivery(envelope,row,this.trust,this.policy(),this.clock());}catch(e){if(row){if(/EXPIRED/.test(e.message))this.store.recordAuthorizationDenial(id,'EXPIRED',e.message,this.clock());else if(/REVOKED|DENIED|RULE_VERSION_CHANGED/.test(e.message))this.store.recordAuthorizationDenial(id,'REVOKED',e.message,this.clock());this.store.event(id,'DELIVERY_DENIED',{reason:e.message,counts:this.counts()});}throw e;}
  if(['DELIVERING','DELIVERY_UNKNOWN','LOCAL_RECEIVED','LOCAL_RECEIVED_UNVERIFIED','LOCAL_DELIVERY_VERIFIED'].includes(row.status))return {status:row.status,duplicate:true};
  if(row.status!=='AUTHORIZED')throw Error('NOT_AUTHORIZED');
  // Read and disclose are separately checked; immutable approved bytes are the only delivery payload.
  authorize(snapshot,this.policy(),this.clock());const current=fs.readFileSync(join(this.root,'resources/summary.txt'),'utf8').trim();this.store.add('summaryReads');if(digest(current)!==snapshot.contentSha256)throw Error('RESOURCE_CONTENT_CHANGED');
  this.store.transaction(()=>{row=this.store.row(id);if(row.status!=='AUTHORIZED')throw Error('CONCURRENT_STATE_CHANGED');this.store.save(id,'DELIVERING');this.store.add('deliveryTools');this.store.add('dispatches');this.store.event(id,'DELIVERING',{counts:this.counts()});});
  let response;
  try{response=await this.adapter('receiver','deliver',{envelope,authorityFile:join(this.root,'authority.sqlite'),receiverFile:join(this.root,'receiver.sqlite'),policyFile:join(this.root,'policy.json'),trust:this.trust,privateKey:this.keys.receiver.privateKey,now:this.clock(),fixtureControl:{afterCommitDelayMs}},{timeoutMs});}
  catch(e){this.store.save(id,'DELIVERY_UNKNOWN');this.store.event(id,'DELIVERY_UNKNOWN',{reason:e.message});return {status:'DELIVERY_UNKNOWN'};}
  if(this.closed){this.store.save(id,'DELIVERY_UNKNOWN');return {status:'DELIVERY_UNKNOWN'};}
  let receipt;try{receipt=authenticated(response.receipt,'receiver',identity.target,this.trust.receiver);this.checkReceipt(receipt,snapshot);}catch(e){this.store.save(id,'DELIVERY_UNKNOWN');throw e;}
  this.store.save(id,'LOCAL_RECEIVED',{...row.data,receipt:response.receipt});this.record('local-receipt',response.receipt);this.store.event(id,'LOCAL_RECEIVED');
  try{return await this.readback(id,{failReadback});}catch(e){this.store.save(id,'LOCAL_RECEIVED_UNVERIFIED');this.store.event(id,'READBACK_FAILED',{reason:e.message});return {status:'LOCAL_RECEIVED_UNVERIFIED'};}
 }
 checkReceipt(p,s){exact(p,['kind','requestId','snapshotHash','contentSha256','recipient','target','receiptId','receivedAt','synthetic']);if(p.kind!=='local-receipt'||p.synthetic!==true||p.requestId!==s.requestId||p.snapshotHash!==digest(s)||p.contentSha256!==s.contentSha256||p.recipient!==s.recipient||p.target!==s.target||!p.receiptId)throw Error('RECEIPT_BINDING');}
 async readback(id,{failReadback=false}={}){
  if(this.closed)throw Error('PROBE_STOPPED');const row=this.store.row(id);if(!row||!['LOCAL_RECEIVED','LOCAL_RECEIVED_UNVERIFIED'].includes(row.status))throw Error('READBACK_STATE');const s=row.data.snapshot;authorize(s,this.policy(),this.clock());
  const query=await this.bot({kind:'readback',requestId:id,snapshotHash:digest(s)});this.store.add('readbacks');const r=await this.adapter('receiver','readback',{envelope:query,authorityFile:join(this.root,'authority.sqlite'),receiverFile:join(this.root,'receiver.sqlite'),policyFile:join(this.root,'policy.json'),trust:this.trust,privateKey:this.keys.receiver.privateKey,now:this.clock(),fixtureControl:{failReadback}});
  if(this.closed)throw Error('PROBE_STOPPED');
  const receipt=authenticated(r.receipt,'receiver',identity.target,this.trust.receiver);this.checkReceipt(receipt,s);if(r.body!==s.body||digest(r.receipt)!==digest(row.data.receipt))throw Error('READBACK_MISMATCH');this.store.save(id,'LOCAL_DELIVERY_VERIFIED');this.store.event(id,'LOCAL_DELIVERY_VERIFIED',{counts:this.counts()});this.record('readback-verified',{requestId:id,body:r.body,receiptId:receipt.receiptId});return {status:'LOCAL_DELIVERY_VERIFIED',requestId:id,receiptId:receipt.receiptId};
 }
 expire(id){const row=this.store.row(id);if(row&&['NEEDS_INFORMATION','AWAITING_CONFIRMATION','AUTHORIZED'].includes(row.status)&&this.clock()>=row.data.expiresAt){this.store.save(id,'EXPIRED');this.store.event(id,'EXPIRED');}return this.status(id);}
 async close(){if(this.closing)return this.closing;this.closed=true;const at=Date.now();this.closing=(async()=>{const r=await this.runtime.close({release:false});let settled=false,timer;await Promise.race([Promise.allSettled([...this.pending]).then(()=>settled=true),new Promise(done=>timer=setTimeout(done,Math.max(1,4000-(Date.now()-at))))]);clearTimeout(timer);const result={...r,protocolSettled:settled,confirmed:r.confirmed&&settled};if(settled)this.store.close();if(result.confirmed)this.runtime.owner.release();return result;})();return this.closing;}
}
