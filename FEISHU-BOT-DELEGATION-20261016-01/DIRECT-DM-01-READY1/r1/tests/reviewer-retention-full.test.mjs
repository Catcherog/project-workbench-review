// Original reviewer assertions, migrated from the extracted method into the full
// DelegationProbe with signed human approval and real local adapter processes.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createFixture,ready} from '../src/fixture.mjs';
import {validateDelivery} from '../src/grant.mjs';
const reports=[];
async function run(name,setup,exercise){
 const f=createFixture('FIX1-'+name);try{
  const r=await ready(f);await setup(f,r);const before=f.probe.counts(),receipts=f.received();
  await exercise(f,r);assert.deepEqual(f.probe.counts(),before);assert.deepEqual(f.received(),receipts);
  reports.push({name,passed:true,state:f.probe.status(r.snapshot.requestId),before,after:f.probe.counts(),receiverWrites:f.received().length,adapterStarts:f.probe.runtime.records.length,roles:[...new Set(f.probe.runtime.records.map(r=>r.role))],journal:f.probe.store.db.prepare('SELECT * FROM events').all()});
 }finally{const stopped=await f.close();assert.equal(stopped.confirmed,true);}
}
const delivered=async(f,r)=>{assert.equal((await f.probe.deliver(r.delivery)).status,'LOCAL_DELIVERY_VERIFIED');};
test('GPT CONTROL: valid signed replay before expiry returns existing verified result',()=>run('valid-replay',delivered,async(f,r)=>{
 assert.equal(validateDelivery(r.delivery,f.probe.store.row(r.snapshot.requestId),f.probe.trust,f.probe.policy(),f.clock.now).requestId,r.snapshot.requestId);
 assert.deepEqual(await f.probe.deliver(r.delivery),{status:'LOCAL_DELIVERY_VERIFIED',duplicate:true});
}));
test('GPT CONTROL: expired but never-dispatched authorization may become EXPIRED',()=>run('unexecuted-expiry',async()=>{},async(f,r)=>{
 f.clock.now=r.snapshot.expiresAt;await assert.rejects(()=>f.probe.deliver(r.delivery),/EXPIRED/);assert.equal(f.probe.status(r.snapshot.requestId),'EXPIRED');
}));
for(const before of ['LOCAL_DELIVERY_VERIFIED','DELIVERY_UNKNOWN'])test(`GPT R1-B01: expiry replay must preserve ${before}`,()=>run('expiry-'+before,async(f,r)=>{
 const result=await f.probe.deliver(r.delivery,before==='DELIVERY_UNKNOWN'?{timeoutMs:180,afterCommitDelayMs:800}:{});assert.equal(result.status,before);assert.equal(f.received().length,1);
},async(f,r)=>{
 f.clock.now=r.snapshot.expiresAt;await assert.rejects(()=>f.probe.deliver(r.delivery),/EXPIRED/);assert.equal(f.probe.status(r.snapshot.requestId),before);
}));
test('GPT R1-B01: subsequent permission revocation must not erase a verified delivery fact',()=>run('revoked-delivery',delivered,async(f,r)=>{
 f.policy(p=>p.disclose=false);await assert.rejects(()=>f.probe.deliver(r.delivery),/DENIED/);assert.equal(f.probe.status(r.snapshot.requestId),'LOCAL_DELIVERY_VERIFIED');
}));
test.after(()=>{fs.mkdirSync('evidence',{recursive:true});fs.writeFileSync('evidence/reviewer-retention-full.json',JSON.stringify({mode:'full engine, real local processes, synthetic keys only',tests:5,reports,realModelCalls:0,platformMessages:0},null,2));});
