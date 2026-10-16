// Reconstructed from the GPT FIX2 review timing; not claimed as the original attachment.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import os from 'node:os';
import {join} from 'node:path';
import {ProbeBroker} from '../src/broker.mjs';
import {processRun,liveGroupMembers} from '../src/process.mjs';
import {readExecutionState} from '../src/execution-state.mjs';
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
for(const afterClose of [false,true])test('required executor rejects late spawn after settle '+(afterClose?'after close':'before stop'),async t=>{
 const root=await fs.mkdtemp(join(os.tmpdir(),'fix3-late-')),file=join(root,'broker.sqlite'),gate=deferred(),started=deferred(),controller=new AbortController();let late,first,next;
 const execute=async x=>{
  first=await processRun('/bin/sleep',['0.02'],{signal:x.signal});
  late=(async()=>{await gate.promise;return processRun('/bin/sleep',['1'],{signal:controller.signal,timeoutMs:1500,onSpawn:r=>started.resolve(r)});})();
  return {marker:x.marker,summary:'synthetic result'};
 };execute.processLifecycle='required';
 const events=new Map(),sent=[];
 const config={file,appId:'synthetic-app',tenantId:'synthetic-tenant',participants:[{id:'synthetic-user',alias:'A'}],deadline:Date.now()+60000,execute,verify:async id=>events.get(id),reply:async(target,text)=>{const r={messageId:'reply-'+sent.length,chatId:target.chatId,text};sent.push(r);return r;},readReply:async id=>sent.find(x=>x.messageId===id)};
 const broker=new ProbeBroker(config);
 const accept=async(id,text)=>{const e={appId:config.appId,tenantId:config.tenantId,senderId:'synthetic-user',senderType:'user',chatId:'synthetic-chat',chatType:'p2p',messageId:id,text,createdAt:Date.now()};events.set(id,e);await broker.accept(e);await broker.queue;};
 try{
  await accept('begin','联调开始');await accept('run','计算合成样本');assert.equal(first.terminationConfirmed,true);assert.equal(broker.workers.size,0);
  if(afterClose)await broker.close();
  gate.resolve();const observed=await Promise.race([started.promise,late]);
  const before=Object.values(readExecutionState(file).runs)[0];const stop=await broker.close(),ownerRetained=existsSync(file+'.owner');let newAdmitted=false;
  try{next=new ProbeBroker(config);newAdmitted=true;}catch{}
  t.diagnostic(JSON.stringify({scenario:afterClose?'after-close-control':'settled-before-stop',parent:before.status,children:Object.values(before.processes).map(x=>x.status),lateSpawned:!!observed.pid,stopConfirmed:stop.confirmed,ownerRetained,newAdmitted,oldGroupMembers:observed.pgid?liveGroupMembers(observed.pgid):[]}));
  assert.equal(observed.spawned??!!observed.pid,false,'settled execution identity must refuse before spawn');
  assert.equal(stop.confirmed,true);assert.equal(newAdmitted,true);
 }finally{
  gate.resolve();controller.abort();if(late){const r=await late;assert.equal(r.terminationConfirmed,true);if(r.pgid)assert.deepEqual(liveGroupMembers(r.pgid),[]);t.diagnostic(JSON.stringify({cleanupConfirmed:r.terminationConfirmed,residualPids:r.residualPids}));}
  if(next)await next.close();await broker.close();await fs.rm(root,{recursive:true,force:true});
 }
});
