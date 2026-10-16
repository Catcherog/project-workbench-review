// Narrow method-level reproduction, not full DelegationProbe/process regression.
import test from 'node:test'; import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs'; import {tmpdir} from 'node:os'; import {join} from 'node:path';
import {keys,signed,digest} from '../r1-slice/codec.mjs';
import {identity,summaryId,action,purpose,defaultPolicy} from '../r1-slice/policy.mjs';
import {validateDelivery} from '../r1-slice/grant.mjs';
import {Store} from '../r1-slice/store.mjs';
import {reviewedMethods} from '../r1-slice/deliver-fragment.mjs';
function setup(status){
 const root=mkdtempSync(join(tmpdir(),'r1-review-')),store=new Store(join(root,'state.sqlite'));
 const bot=keys(),human=keys(),trust={bot:bot.publicKey,human:human.publicKey};
 const policy=defaultPolicy(),body='Synthetic reviewer data';
 const s={protocol:'demo-delegation/v1',requestId:'r1-review-request',...identity,action,purpose,resourceId:summaryId,resourceVersion:'v1',body,contentSha256:digest(body),policyVersion:1,bindingVersion:1,issuedAt:1000,expiresAt:301000,nonce:'synthetic-nonce',confirmationRef:'synthetic-ref',hops:0};
 const p={kind:'confirmation',synthetic:true,human:identity.human,requestId:s.requestId,snapshotHash:digest(s),decision:'approve',issuedAt:1001,expiresAt:s.expiresAt,confirmationRef:s.confirmationRef};
 const confirmation=signed('human',identity.human,p,human.privateKey),wire=signed('bot',identity.bot,{kind:'deliver',snapshot:s,confirmation},bot.privateKey);
 store.db.prepare('INSERT INTO requests VALUES(?,?,?,?,?,?)').run(s.requestId,digest(s),s.nonce,status,JSON.stringify({snapshot:s,confirmation}),1);
 let now=1002;
 const context={closed:false,trust,store,policy:()=>policy,clock:()=>now,counts:()=>store.counts(),adapter:()=>{throw Error('UNEXPECTED_ADAPTER');}};
 return {s,wire,policy,store,context,setTime:x=>now=x,close(){store.close();rmSync(root,{recursive:true,force:true});}};
}
test('CONTROL: valid signed replay before expiry returns existing verified result',async()=>{
 const f=setup('LOCAL_DELIVERY_VERIFIED');try{
 assert.equal(validateDelivery(f.wire,f.store.row(f.s.requestId),f.context.trust,f.policy,1002).requestId,f.s.requestId);
 assert.deepEqual(await reviewedMethods.deliver.call(f.context,f.wire),{status:'LOCAL_DELIVERY_VERIFIED',duplicate:true});
 }finally{f.close();}
});
test('CONTROL: expired but never-dispatched authorization may become EXPIRED',async()=>{
 const f=setup('AUTHORIZED');try{f.setTime(f.s.expiresAt);await assert.rejects(reviewedMethods.deliver.call(f.context,f.wire),/EXPIRED/);assert.equal(f.store.row(f.s.requestId).status,'EXPIRED');}finally{f.close();}
});
for(const before of ['LOCAL_DELIVERY_VERIFIED','DELIVERY_UNKNOWN'])test(`R1-B01: expiry replay must preserve ${before}`,async()=>{
 const f=setup(before);try{f.setTime(f.s.expiresAt);await assert.rejects(reviewedMethods.deliver.call(f.context,f.wire),/EXPIRED/);assert.equal(f.store.row(f.s.requestId).status,before);}finally{f.close();}
});
test('R1-B01: subsequent permission revocation must not erase a verified delivery fact',async()=>{
 const f=setup('LOCAL_DELIVERY_VERIFIED');try{f.policy.disclose=false;await assert.rejects(reviewedMethods.deliver.call(f.context,f.wire),/DENIED/);assert.equal(f.store.row(f.s.requestId).status,'LOCAL_DELIVERY_VERIFIED');}finally{f.close();}
});
