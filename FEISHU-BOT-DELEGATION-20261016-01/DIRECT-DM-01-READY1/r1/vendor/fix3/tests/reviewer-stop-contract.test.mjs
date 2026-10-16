// Independent offline contract tests. No model, Feishu, production service, or network calls.
// The two safety assertions are expected to FAIL against the audited R1-FIX1 commit.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import os from 'node:os';
import {join} from 'node:path';
import {ProbeBroker} from '../src/broker.mjs';
import {ExecutionBudget} from '../src/budget.mjs';
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function fixture(execute){
 const root=await fs.mkdtemp(join(os.tmpdir(),'gpt-fix1-review-'));
 const events=new Map(),replies=[];const file=join(root,'broker.sqlite');
 const broker=new ProbeBroker({file,appId:'synthetic-app',tenantId:'synthetic-tenant',participants:[{id:'synthetic-user',alias:'A'}],deadline:Date.now()+60000,maxStopMs:100,
  verify:async id=>events.get(id),execute,
  reply:async(t,text)=>{const r={messageId:'synthetic-reply-'+replies.length,chatId:t.chatId,text};replies.push(r);return r;},
  readReply:async id=>replies.find(r=>r.messageId===id)});
 async function accept(id,text){const e={appId:'synthetic-app',tenantId:'synthetic-tenant',senderId:'synthetic-user',senderType:'user',chatId:'synthetic-chat',chatType:'p2p',messageId:id,text,createdAt:Date.now()};events.set(id,e);return broker.accept(e);}
 await accept('begin','联调开始');await broker.queue;
 return {root,file,broker,accept,replies,async cleanup(){await broker.close();await fs.rm(root,{recursive:true,force:true});}};
}
function unknownExitError(){return Object.assign(new Error('MODEL_NOT_COMPLETED'),{evidence:{terminationConfirmed:false,residualPids:[424242],stopReason:'cancelled'}});}

test('C01 positive control: idle broker confirms clean stop',async()=>{
 const f=await fixture(async x=>({marker:x.marker,summary:'合成测试'}));
 try{const r=await f.broker.close();assert.equal(r.confirmed,true);assert.equal(existsSync(f.file+'.owner'),false);}finally{await f.cleanup();}
});

test('C02 positive control: unresolved worker keeps stop unconfirmed and owner retained',async()=>{
 let ready;const started=new Promise(r=>ready=r);
 const f=await fixture(()=>{ready();return new Promise(()=>{});});
 try{await f.accept('run','计算合成样本');await started;const r=await f.broker.close();assert.equal(r.confirmed,false);assert.equal(existsSync(f.file+'.owner'),true);}finally{await f.cleanup();}
});

test('B01a safety: a settled worker with terminationConfirmed=false must NOT confirm stop',async t=>{
 const f=await fixture(async()=>{throw unknownExitError();});
 try{
  await f.accept('run','计算合成样本');await f.broker.queue;
  const message=f.broker.db.prepare("SELECT status FROM messages WHERE id='run'").get();
  const r=await f.broker.close();const ownerExists=existsSync(f.file+'.owner');
  t.diagnostic(JSON.stringify({scenario:'unknown-before-stop',workerEvidence:{terminationConfirmed:false,residualPids:[424242]},messageStatus:message.status,stopReceipt:r,ownerExistsAfterClose:ownerExists,realChildSpawned:false}));
  assert.deepEqual({confirmed:r.confirmed,ownerRetained:ownerExists},{confirmed:false,ownerRetained:true});
 }finally{await f.cleanup();}
});

test('B01b safety: worker reporting unknown termination DURING stop must retain ownership',async t=>{
 let ready;const started=new Promise(r=>ready=r);
 const f=await fixture(x=>new Promise((resolve,reject)=>{ready();x.signal.addEventListener('abort',()=>setTimeout(()=>reject(unknownExitError()),10),{once:true});}));
 try{
  await f.accept('run','计算合成样本');await started;
  const r=await f.broker.close();const ownerExists=existsSync(f.file+'.owner');
  t.diagnostic(JSON.stringify({scenario:'unknown-during-stop',workerEvidence:{terminationConfirmed:false,residualPids:[424242]},stopReceipt:r,ownerExistsAfterClose:ownerExists,realChildSpawned:false}));
  assert.deepEqual({confirmed:r.confirmed,ownerRetained:ownerExists},{confirmed:false,ownerRetained:true});
 }finally{await f.cleanup();}
});

test('C03 positive control: cooperative cancelled worker finishes before confirmed stop',async()=>{
 let ready;const started=new Promise(r=>ready=r);
 const f=await fixture(x=>new Promise((resolve,reject)=>{ready();x.signal.addEventListener('abort',()=>reject(Object.assign(new Error('CANCELLED'),{evidence:{terminationConfirmed:true,residualPids:[]}})),{once:true});}));
 try{await f.accept('run','计算合成样本');await started;const r=await f.broker.close();assert.equal(r.confirmed,true);assert.equal(existsSync(f.file+'.owner'),false);}finally{await f.cleanup();}
});

test('C04 positive control: the separate model budget DOES retain unknown-termination occupancy',async()=>{
 const root=await fs.mkdtemp(join(os.tmpdir(),'gpt-fix1-budget-'));
 const budget=new ExecutionBudget(join(root,'synthetic-budget.sqlite'),{usedCalls:0,startedAt:[]});
 try{const id=budget.reserve();budget.finish(id,false);assert.equal(budget.status().active,1);assert.throws(()=>budget.reserve(),/MODEL_OWNER_BUSY/);}finally{budget.close();await fs.rm(root,{recursive:true,force:true});}
});
