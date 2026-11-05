import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm,chmod,realpath} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {SignedQueueBridge} from '../server/queue-bridge.mjs';
import {sign,canonical,verifySigned} from '../server/canonical.mjs';

const key=Buffer.from('synthetic-wire-test-key-at-least-32-bytes');
const clock=()=>Date.now();
const session=()=>({id:'owner-session-0001',userId:'demo-owner',tenantId:'demo-tenant',workspaceId:'ledger-demo',
  projectIds:['demo-sample'],scopes:['ledger:read','am:prepare','am:approve'],expiresAtMs:clock()+600000});
async function fixture(t){
  // macOS's /var temporary path aliases /private/var. Test the canonical
  // private queue path while retaining the product's symlink rejection.
  const dir=await realpath(await mkdtemp(join(tmpdir(),'ledger-queue-')));await chmod(dir,0o700);
  const keyFile=join(dir,'service.key');await writeFile(keyFile,key,{mode:0o600});
  t.after(()=>rm(dir,{recursive:true,force:true}));
  const bridge=await new SignedQueueBridge({queueDir:dir,keyFile,pollMs:5,timeoutMs:500}).init();
  return {dir,bridge};
}
async function reply(f,id,data,{tamper=false}={}){
  const paths=f.bridge.paths(id);let request;
  for(let i=0;i<100;i++){try{request=JSON.parse(await readFile(paths.request,'utf8'));break;}catch(e){if(e.code!=='ENOENT')throw e;await delay(3);}}
  assert.ok(request);assert.equal(request.operation,'workbench');assert.equal(verifySigned(request.envelope,key),true);
  const result={schema:'am-workbench.rpc-result/v1',requestId:id,method:request.envelope.method,audience:'am-ledger-workbench',
    ok:true,data,serverTimeMs:clock()};result.signature=sign(result,key);
  if(tamper)result.data={changed:true};
  await writeFile(paths.result,JSON.stringify({workbench:result}),{mode:0o600});
}
test('signed operator queue roundtrip binds request, session and method',async t=>{
  const f=await fixture(t),s=session(),id='wire-request-0001';
  const pending=f.bridge.call('snapshot',{},s,{requestId:id});await reply(f,id,{projects:[],expiresAtMs:clock()+60000});
  assert.deepEqual((await pending).projects,[]);
  assert.deepEqual(await f.bridge.call('snapshot',{},s,{requestId:id}),await pending);
});
test('same request ID cannot change approved body',async t=>{
  const f=await fixture(t),s=session(),id='wire-request-0002';
  const pending=f.bridge.call('prepare',{body:'已确认的正文'},s,{requestId:id});await reply(f,id,{previewId:'preview-1',expiresAtMs:clock()+60000});await pending;
  await assert.rejects(f.bridge.call('prepare',{body:'改变后的正文'},s,{requestId:id}),e=>e.code==='idempotency_conflict');
});
test('old response cannot be read after project scope shrinks',async t=>{
  const f=await fixture(t),s=session(),id='wire-request-0003';
  const pending=f.bridge.call('snapshot',{},s,{requestId:id});await reply(f,id,{projects:[]});await pending;
  await assert.rejects(f.bridge.peek(id,{...s,projectIds:[]}),e=>e.code==='request_scope_mismatch');
});
test('tampered AM result cannot be presented as an execution receipt',async t=>{
  const f=await fixture(t),s=session(),id='wire-request-0004';
  const pending=f.bridge.call('approve',{previewId:'preview-1'},s,{requestId:id});const rejection=assert.rejects(pending,e=>e.code==='invalid_am_receipt');
  await reply(f,id,{state:'queued'},{tamper:true});await rejection;
});
test('expired snapshot cannot replay raw source content',async t=>{
  const f=await fixture(t),s=session(),id='wire-request-0005';
  const pending=f.bridge.call('snapshot',{},s,{requestId:id});const rejection=assert.rejects(pending,e=>e.code==='snapshot_expired');
  await reply(f,id,{expiresAtMs:clock()-1,quote:'过期原文'});await rejection;
});
test('expired follow-up preview cannot replay its body through the operation URL',async t=>{
  const f=await fixture(t),s=session(),id='wire-request-expired-preview';
  const pending=f.bridge.call('prepare',{},s,{requestId:id});
  const rejection=assert.rejects(pending,e=>e.code==='preview_expired');
  await reply(f,id,{previewId:'old-preview',expiresAtMs:clock()-1,body:'已过期的正文'});await rejection;
});
test('world-readable signing key and traversal request IDs are rejected',async t=>{
  const f=await fixture(t);await chmod(join(f.dir,'service.key'),0o644);
  await assert.rejects(new SignedQueueBridge({queueDir:f.dir,keyFile:join(f.dir,'service.key')}).init(),e=>e.code==='unsafe_am_file');
  assert.throws(()=>f.bridge.paths('../not-a-request'),e=>e.code==='invalid_request_id');
});
test('wire canonicalization rejects floating timestamps and keeps Chinese source text',()=>{
  assert.equal(canonical({z:'台架',a:[1,true,null]}),'{"a":[1,true,null],"z":"台架"}');
  assert.throws(()=>canonical({time:1.1}),e=>e.code==='invalid_wire_value');
});
