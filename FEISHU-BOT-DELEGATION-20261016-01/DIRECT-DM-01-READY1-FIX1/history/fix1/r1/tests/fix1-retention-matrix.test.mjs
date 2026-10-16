import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {setTimeout as delay} from 'node:timers/promises';
import {createFixture,ready} from '../src/fixture.mjs';
import {keys,digest} from '../src/codec.mjs';

const reports=[];
async function until(fn){const end=Date.now()+2500;while(!fn()){if(Date.now()>end)throw Error('CONTROLLED_STAGE_NOT_REACHED');await delay(5);}}
function receiverCommitted(f){try{return f.received().length===1;}catch(e){if(e.code==='ERR_SQLITE_ERROR'&&e.message==='no such table: deliveries')return false;throw e;}}
async function stage(f,r,status){
 let pending,release;
 if(status==='DELIVERING'){
  pending=f.probe.deliver(r.delivery,{afterCommitDelayMs:800});await until(()=>f.probe.status(r.snapshot.requestId)==='DELIVERING'&&receiverCommitted(f));
 }else if(status==='LOCAL_RECEIVED'){
  const original=f.probe.readback.bind(f.probe);const pause=new Promise(done=>release=done);f.probe.readback=async(...args)=>{await pause;return original(...args);};
  pending=f.probe.deliver(r.delivery);await until(()=>f.probe.status(r.snapshot.requestId)==='LOCAL_RECEIVED');
 }else{
  const args=status==='DELIVERY_UNKNOWN'?{timeoutMs:180,afterCommitDelayMs:800}:status==='LOCAL_RECEIVED_UNVERIFIED'?{failReadback:true}:{};
  assert.equal((await f.probe.deliver(r.delivery,args)).status,status);
 }
 return async()=>{release?.();if(pending)await pending;};
}
// The three reviewer failure pairs are covered by reviewer-retention-full.test.
const alreadyCovered=new Set(['LOCAL_DELIVERY_VERIFIED/expiry','DELIVERY_UNKNOWN/expiry','LOCAL_DELIVERY_VERIFIED/revoke']);
test('R1-B01 preserves all dispatched stages under later authorization rejection',async t=>{
 for(const status of ['DELIVERING','DELIVERY_UNKNOWN','LOCAL_RECEIVED','LOCAL_RECEIVED_UNVERIFIED','LOCAL_DELIVERY_VERIFIED'])for(const mode of ['expiry','revoke','rule-change']){
  if(alreadyCovered.has(status+'/'+mode))continue;
  await t.test(status+'/'+mode,async()=>{
   const f=createFixture('FIX1-matrix-'+status+'-'+mode);let finish=async()=>{};
   try{const r=await ready(f);finish=await stage(f,r,status);const before=f.probe.counts(),received=f.received(),saved=f.probe.store.row(r.snapshot.requestId).data;
    if(mode==='expiry')f.clock.now=r.snapshot.expiresAt;else f.policy(p=>{if(mode==='revoke')p.disclose=false;else p.version++;});
    await assert.rejects(()=>f.probe.deliver(r.delivery),mode==='expiry'?/EXPIRED/:mode==='revoke'?/DENIED/:/RULE_VERSION_CHANGED/);
    assert.equal(f.probe.status(r.snapshot.requestId),status);assert.deepEqual(f.probe.counts(),before);assert.deepEqual(f.received(),received);assert.deepEqual(f.probe.store.row(r.snapshot.requestId).data,saved);
    const decision=f.probe.store.authorization(r.snapshot.requestId);assert.equal(decision.state,mode==='expiry'?'EXPIRED':'REVOKED');
    const journal=f.probe.store.db.prepare('SELECT event FROM events WHERE request_id=?').all(r.snapshot.requestId);assert.ok(journal.some(x=>x.event==='DELIVERING'));assert.ok(journal.some(x=>x.event==='AUTHORIZATION_DENIED'));
    await finish();finish=async()=>{};assert.deepEqual(f.probe.store.authorization(r.snapshot.requestId),decision);assert.equal(f.probe.counts().dispatches,1);assert.equal(f.received().length,1);
    reports.push({status,mode,passed:true,decision,dispatches:1,receiverWrites:1,finalFact:f.probe.status(r.snapshot.requestId)});
   }finally{await finish();assert.equal((await f.close()).confirmed,true);}
  });
 }
});
test('R1-B01 invalid signature and changed snapshot do not bypass authorization via idempotency',async()=>{
 const f=createFixture('FIX1-invalid-replays');try{const r=await ready(f);await f.probe.deliver(r.delivery);const before=f.probe.counts();
  const invalid=await f.probe.bot(r.delivery.payload,keys().privateKey);await assert.rejects(()=>f.probe.deliver(invalid),/INVALID_SIGNATURE/);
  const snapshot={...r.snapshot,body:'Changed protected fixture bytes'};snapshot.contentSha256=digest(snapshot.body);
  const changed=await f.probe.bot({kind:'deliver',snapshot,confirmation:r.approval});await assert.rejects(()=>f.probe.deliver(changed),/CONFIRMED_SNAPSHOT_CHANGED/);
  assert.equal(f.probe.status(r.snapshot.requestId),'LOCAL_DELIVERY_VERIFIED');assert.deepEqual(f.probe.counts(),before);assert.equal(f.received().length,1);
 }finally{assert.equal((await f.close()).confirmed,true);}
});
test('R1-B01 independent authorization decisions and original receipt survive reopening',async()=>{
 const f=createFixture('FIX1-retention-restart');try{const r=await ready(f);await f.probe.deliver(r.delivery);const received=f.received(),before=f.probe.counts();f.clock.now=r.snapshot.expiresAt;await assert.rejects(()=>f.probe.deliver(r.delivery),/EXPIRED/);const decision=f.probe.store.authorization(r.snapshot.requestId);assert.equal((await f.close()).confirmed,true);f.reopen();assert.equal(f.probe.status(r.snapshot.requestId),'LOCAL_DELIVERY_VERIFIED');assert.deepEqual(f.probe.store.authorization(r.snapshot.requestId),decision);assert.deepEqual(f.received(),received);assert.deepEqual(f.probe.counts(),before);}finally{assert.equal((await f.close()).confirmed,true);}
});
test.after(()=>{fs.mkdirSync('evidence',{recursive:true});fs.writeFileSync('evidence/fix1-retention-matrix.json',JSON.stringify({mode:'full engine and actual local adapter processes',additionalStageScenarios:12,reports,realModelCalls:0,platformMessages:0},null,2));});
