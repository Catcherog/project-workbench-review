import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import os from 'node:os';
import {join} from 'node:path';
import {ProbeBroker} from '../src/broker.mjs';
import {processRun,liveGroupMembers} from '../src/process.mjs';
import {recordExecution} from '../src/execution-context.mjs';
import {readExecutionState,reconcileExecution,executionStatePath} from '../src/execution-state.mjs';
import {recoverOwner,acquireOwner,inspectOwner} from '../src/owner.mjs';
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function fixture(execute,extra={}){
 const root=await fs.mkdtemp(join(os.tmpdir(),'fix2-state-')),file=join(root,'broker.sqlite'),events=new Map(),sent=[];
 const config={file,appId:'synthetic-app',tenantId:'synthetic-tenant',participants:[{id:'synthetic-user',alias:'A'}],deadline:Date.now()+60000,maxStopMs:150,execute,
 verify:async id=>events.get(id),reply:async(t,text)=>{const r={messageId:'reply-'+sent.length,chatId:t.chatId,text};sent.push(r);return r;},readReply:async id=>sent.find(x=>x.messageId===id),...extra};
 const broker=new ProbeBroker(config);
 const accept=async(id,text)=>{const e={appId:config.appId,tenantId:config.tenantId,senderId:'synthetic-user',senderType:'user',chatId:'synthetic-chat',chatType:'p2p',messageId:id,text,createdAt:Date.now()};events.set(id,e);return broker.accept(e);};
 await accept('begin','联调开始');await broker.queue;
 return {root,file,config,broker,accept,sent,async work(){await accept('run','计算合成样本');await broker.queue;},async cleanup(){await broker.close();await fs.rm(root,{recursive:true,force:true});}};
}
function fakeStarted(){recordExecution({type:'intent',processKey:'fake-process',commandFingerprint:'synthetic-command-fingerprint'});recordExecution({type:'started',processKey:'fake-process',pid:424242,pgid:424242,identity:'synthetic-start-identity'});}
const fakeFinished=confirmed=>recordExecution({type:'finished',processKey:'fake-process',pid:424242,pgid:424242,identity:'synthetic-start-identity',spawned:true,terminationConfirmed:confirmed,residualPids:confirmed?[]:[424242],exit:confirmed?0:null,stopReason:'cancelled'});

test('missing termination receipt cannot be replaced by a successful returned business result',async()=>{
 const f=await fixture(async x=>{fakeStarted();return {marker:x.marker,summary:'synthetic'};});
 try{await f.work();const r=await f.broker.close();assert.equal(r.confirmed,false);assert.equal(f.sent.length,1);assert.equal(existsSync(f.file+'.owner'),true);assert.equal(Object.values(readExecutionState(f.file).runs)[0].status,'unknown');}finally{await f.cleanup();}
});
test('opaque executor without a process/no-spawn contract is not assumed safe',async()=>{
 const f=await fixture(async x=>({marker:x.marker,summary:'synthetic'}));
 try{await f.work();assert.equal((await f.broker.close()).confirmed,false);assert.equal(f.sent.length,1);}finally{await f.cleanup();}
});
for(const lateConfirmed of [false,true])test('timeout then late '+(lateConfirmed?'success':'unknown')+' cannot rewrite sealed state',async()=>{
 const f=await fixture(async x=>{fakeStarted();await delay(120);fakeFinished(lateConfirmed);return {marker:x.marker,summary:'late'};},{taskTimeoutMs:10,maxStopMs:50});
 try{await f.work();const r=await f.broker.close(),before=await fs.readFile(executionStatePath(f.file),'utf8');assert.equal(r.confirmed,false);await delay(160);assert.equal(await fs.readFile(executionStatePath(f.file),'utf8'),before);assert.equal(f.sent.length,1);assert.equal(existsSync(f.file+'.owner'),true);}finally{await f.cleanup();}
});
test('actual exit-unknown survives stripped errors, then only fresh OS reconciliation releases owner',async t=>{
 let receipt;
 const f=await fixture(async x=>{receipt=await processRun(process.execPath,['-e','setTimeout(()=>{},10)'],{signal:x.signal,timeoutMs:1000,terminateGraceMs:10,terminateBoundMs:70,inspectGroup:()=>null});throw Error('WRAPPER_REMOVED_ALL_EVIDENCE');});
 try{
  await f.work();assert.equal(receipt.terminationConfirmed,false);assert.deepEqual(liveGroupMembers(receipt.pgid),[]);
  const r=await f.broker.close();assert.equal(r.confirmed,false);assert.equal(existsSync(f.file+'.owner'),true);
  assert.throws(()=>new ProbeBroker(f.config),/BROKER_ALREADY_OWNED/);
  const state=readExecutionState(f.file),id=Object.keys(state.runs)[0];assert.equal(state.runs[id].status,'unknown');
  const owner=JSON.parse(await fs.readFile(f.file+'.owner/owner.json','utf8'));assert.throws(()=>recoverOwner(f.file,owner.id),/OWNER_RECOVERY_DENIED/);
  assert.throws(()=>reconcileExecution(f.file,id,{identity:()=> 'reused-process',members:()=>[]}),/PID_REUSED/);
  assert.throws(()=>reconcileExecution(f.file,id,{identity:()=>{throw Error('inspection unavailable');},members:()=>[]}),/inspection unavailable/);
  assert.throws(()=>reconcileExecution(f.file,id,{identity:()=>null,members:()=>null}),/GROUP_UNCONFIRMED/);
  const checked=f.broker.reconcileTermination(id);assert.equal(checked.reconciled,true);assert.equal(checked.ownerReleased,true);assert.equal(existsSync(f.file+'.owner'),false);assert.strictEqual(f.broker.reconcileTermination(id),checked);
  const next=new ProbeBroker(f.config);assert.equal((await next.close()).confirmed,true);
  assert.equal((await f.broker.close()).confirmed,false); // original stop receipt remains historical
  t.diagnostic(JSON.stringify({kind:'actual_short_child_with_injected_inspection_failure',injectedUnknown:true,realGroupAbsentBeforeReconcile:true,stopConfirmed:r.confirmed,ownerRetainedUntilCheck:true,reconcileUsedRealOsChecks:true,ownerReleasedAfterCheck:true}));
 }finally{await f.cleanup();}
});
test('canonical termination persistence failure keeps durable blocking state even after real exit',async()=>{
 let receipt;const f=await fixture(async x=>{receipt=await processRun('/bin/sleep',['0.02'],{signal:x.signal});throw Error('ordinary wrapper error');});
 const original=f.broker.terminations.persist;
 f.broker.terminations.persist=(path,state)=>{if(Object.values(state.runs).some(r=>Object.values(r.processes).some(p=>p.status==='confirmed')))throw Error('injected terminal fsync failure');return original(path,state);};
 try{await f.work();assert.equal(receipt.terminationConfirmed,true);assert.equal(receipt.lifecyclePersisted,false);const r=await f.broker.close();assert.equal(r.confirmed,false);assert.equal(r.persistenceFault,true);assert.equal(existsSync(executionStatePath(f.file)+'.fault'),true);assert.equal(existsSync(f.file+'.owner'),true);assert.throws(()=>new ProbeBroker(f.config),/BROKER_ALREADY_OWNED/);}finally{await f.cleanup();}
});
test('closed concurrent/repeated calls are idempotent and do not double-release',async()=>{
 const execute=async x=>({marker:x.marker,summary:'logical-only'});execute.processLifecycle='logical-only';const f=await fixture(execute);
 try{await f.work();const [a,b,c]=await Promise.all([f.broker.close(),f.broker.close(),f.broker.stop()]);assert.strictEqual(a,b);assert.strictEqual(b,c);assert.equal(a.confirmed,true);assert.equal(existsSync(f.file+'.owner'),false);assert.strictEqual(await f.broker.close(),a);}finally{await f.cleanup();}
});
test('explicit pre-spawn cancellation and confirmed nonzero exit are safe failure paths',async()=>{
 for(const cancelBefore of [true,false]){
  let receipt;const f=await fixture(async()=>{const c=new AbortController();if(cancelBefore)c.abort();receipt=await processRun('/bin/sh',['-c','exit 7'],{signal:c.signal});throw Error('normal failure');});
  try{await f.work();assert.equal(receipt.terminationConfirmed,true);if(cancelBefore)assert.equal(receipt.spawned,false);else assert.equal(receipt.exit,7);assert.equal((await f.broker.close()).confirmed,true);assert.equal(existsSync(f.file+'.owner'),false);assert.equal(f.sent.length,1);}finally{await f.cleanup();}
 }
});
test('unknown state copied without owner still blocks restart and cannot be reconciled on another host',async()=>{
 const f=await fixture(async()=>{fakeStarted();fakeFinished(false);throw Error('unknown');});
 const destination=await fs.mkdtemp(join(os.tmpdir(),'fix2-copy-'));
 try{await f.work();await f.broker.close();const copied=join(destination,'broker.sqlite');await fs.copyFile(f.file,copied);await fs.copyFile(executionStatePath(f.file),executionStatePath(copied));assert.throws(()=>new ProbeBroker({...f.config,file:copied}),/TERMINATION_RECONCILIATION_REQUIRED/);
  const state=readExecutionState(copied),id=Object.keys(state.runs)[0];state.hostFingerprint='different-test-host';await fs.writeFile(executionStatePath(copied),JSON.stringify(state));assert.throws(()=>reconcileExecution(copied,id,{identity:()=>null,members:()=>[]}),/HOST_MISMATCH/);
 }finally{await f.cleanup();await fs.rm(destination,{recursive:true,force:true});}
});
test('an asynchronous process intent after confirmed close cannot spawn a new child',async()=>{
 let late;const execute=async x=>{late=new Promise(resolve=>setTimeout(async()=>resolve(await processRun('/bin/sleep',['1'])),60));return {marker:x.marker,summary:'logical'};};execute.processLifecycle='logical-only';
 const f=await fixture(execute);
 try{await f.work();assert.equal((await f.broker.close()).confirmed,true);const r=await late;assert.equal(r.spawned,false);assert.equal(r.stopReason,'lifecycle_persistence_failed');assert.equal(f.sent.length,2);}finally{await f.cleanup();}
});
test('managed adapter cannot claim safe exit with only an exception hint',async()=>{
 const execute=async()=>{throw Object.assign(Error('no manager receipt'),{evidence:{terminationConfirmed:true,residualPids:[]}});};execute.processLifecycle='required';
 const f=await fixture(execute);try{await f.work();assert.equal((await f.broker.close()).confirmed,false);assert.equal(existsSync(f.file+'.owner'),true);}finally{await f.cleanup();}
});
test('mismatched terminal identity never replaces the started binding or permits recovery',async()=>{
 const f=await fixture(async()=>{fakeStarted();recordExecution({type:'finished',processKey:'fake-process',spawned:true,pid:434343,pgid:434343,identity:'wrong-process',terminationConfirmed:true,residualPids:[]});throw Error('mismatch');});
 try{await f.work();assert.equal((await f.broker.close()).confirmed,false);const state=readExecutionState(f.file),id=Object.keys(state.runs)[0],p=state.runs[id].processes['fake-process'];assert.equal(p.pid,424242);assert.equal(p.bindingMismatch,true);assert.throws(()=>reconcileExecution(f.file,id,{identity:()=>null,members:()=>[]}),/BINDING_MISMATCH/);}finally{await f.cleanup();}
});
test('owner PID reuse/mismatched startup identity is not auto-recoverable',async()=>{
 const root=await fs.mkdtemp(join(os.tmpdir(),'fix2-owner-')),file=join(root,'owner-test'),lease=acquireOwner(file),path=lease.path+'/owner.json';
 try{await fs.writeFile(path,JSON.stringify({...lease.owner,identity:'different-start-identity'}));assert.equal(inspectOwner(file).state,'pid_reused');assert.equal(inspectOwner(file).recoverable,false);assert.throws(()=>recoverOwner(file,lease.owner.id),/OWNER_RECOVERY_DENIED/);}finally{await fs.writeFile(path,JSON.stringify(lease.owner));lease.release();await fs.rm(root,{recursive:true,force:true});}
});
