import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {randomUUID} from 'node:crypto';
import {createLedgerHandler} from '../server/ledger-handler.mjs';
import {DemoBridge} from '../demo/demo-bridge.mjs';
import {LedgerError} from '../server/errors.mjs';
import {sanitizeEvidence} from '../server/evidence-retention.mjs';
import {createNativeLedgerMount} from '../integrations/wb/native-mount.mjs';

async function fixture(t,options={}){
  const bridge=options.bridge||new DemoBridge();
  const session={verified:true,id:'http-test-session',userId:'demo-owner',tenantId:'demo-tenant',workspaceId:'ledger-demo',projectIds:['*'],
    scopes:['ledger:read','am:prepare','am:approve','review:resolve','reminder:manage'],expiresAtMs:Date.now()+600000,...options.session};
  const handler=createLedgerHandler({bridge,cacheTtlMs:options.ttl??10000,getSession(req){return req.headers.authorization==='test-owner'?session:null;},
    authorizeMutation(req){if(req.headers['x-test-csrf']!=='csrf-test')throw new LedgerError('csrf_rejected','请在当前页面确认。',403);}});
  const server=createServer((req,res)=>void handler(req,res));await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const origin='http://127.0.0.1:'+server.address().port;
  const call=async(path,body,extra={})=>{const r=await fetch(origin+'/api/v2/ledger'+path,{method:body===undefined?'GET':'POST',
    headers:{Authorization:'test-owner','Content-Type':'application/json','X-Test-CSRF':'csrf-test',...extra},
    ...(body===undefined?{}:{body:JSON.stringify({requestId:randomUUID(),...body})})});return{status:r.status,data:await r.json()};};
  return {bridge,handler,session,call,origin};
}
test('bootstrap requires host authentication and project scope is enforced',async t=>{
  const f=await fixture(t,{session:{projectIds:['demo-sample']}});
  assert.equal((await f.call('/bootstrap',undefined,{Authorization:'bad'})).status,401);
  const out=await f.call('/bootstrap');assert.equal(out.status,200);assert.deepEqual(out.data.projects.map(p=>p.id),['demo-sample']);
  assert.equal((await f.call('/projects/demo-release')).status,404);
});
test('browser cannot inject trusted identity or omit CSRF',async t=>{
  const f=await fixture(t);
  assert.equal((await f.call('/am/prepare',{projectId:'demo-sample',userId:'someone-else'})).status,422);
  assert.equal((await f.call('/am/prepare',{projectId:'demo-sample'},{'X-Test-CSRF':'bad'})).status,403);
  assert.equal(f.bridge.calls.some(c=>c.method==='prepare'),false);
});
test('same-page prepare, present, approve preserves business state and one action',async t=>{
  const f=await fixture(t);const project=await f.call('/projects/demo-sample');assert.equal(project.data.rows.length,4);
  const prepared=await f.call('/am/prepare',{projectId:'demo-sample',itemId:'demo-bench'});assert.equal(prepared.status,200);
  const preview=prepared.data.preview;
  const shown=await f.call('/am/present',{previewId:preview.previewId,displayHash:preview.displayHash});
  const requestId=randomUUID();const approve={previewId:preview.previewId,presentationId:shown.data.presentationId,displayHash:preview.displayHash,requestId};
  const first=await f.call('/am/approve',approve),second=await f.call('/am/approve',approve);
  assert.equal(first.data.state,'queued');assert.equal(first.data.messageId,null);assert.deepEqual(first.data,second.data);
  assert.equal(f.bridge.receipts.size,1);assert.equal(f.bridge.snapshot.items.find(i=>i.id==='demo-bench').businessState,'open');
  assert.equal((await f.call('/am/receipts/'+requestId)).data.requestId,requestId);
});
test('waiting recommendation never allocates a sending preview',async t=>{
  const f=await fixture(t);const result=await f.call('/am/prepare',{projectId:'demo-release',itemId:'demo-rollout'});
  assert.equal(result.data.kind,'wait');assert.equal(f.bridge.previews.size,0);
});
test('editing a draft invalidates its previous presentation',async t=>{
  const f=await fixture(t);const p=(await f.call('/am/prepare',{projectId:'demo-sample',itemId:'demo-bench'})).data.preview;
  const shown=(await f.call('/am/present',{previewId:p.previewId,displayHash:p.displayHash})).data;
  const revised=await f.call('/am/revise',{projectId:'demo-sample',itemId:'demo-bench',previousPreviewId:p.previewId,body:'补充核实开测时间。',channel:'group'});
  assert.equal(revised.status,200);assert.notEqual(revised.data.preview.previewId,p.previewId);
  assert.equal((await f.call('/am/approve',{previewId:p.previewId,presentationId:shown.presentationId,displayHash:p.displayHash})).status,409);
  assert.equal(f.bridge.receipts.size,0);
});
test('review resolves information only and moves feedback to the chosen project',async t=>{
  const f=await fixture(t);const initial=(await f.call('/bootstrap')).data,review=initial.reviews[0];
  const result=await f.call('/reviews/resolve',{reviewId:review.id,choiceId:'demo-sample',expectedBasis:review.basis});assert.equal(result.status,200);
  assert.equal((await f.call('/bootstrap')).data.reviews.length,0);assert.equal(f.bridge.previews.size,0);
  const summary=(await f.call('/projects/demo-sample')).data;
  assert.match(summary.rows.find(r=>r.key==='progress').text,/评审资料/);
  assert.equal(f.bridge.snapshot.facts.find(v=>v.id==='demo-unassigned').authority,'unconfirmed');
});
test('reminder read and snooze change presentation, never deadline or closure',async t=>{
  const f=await fixture(t),reminder=f.bridge.snapshot.reminders[0],deadline=reminder.dueAt;
  assert.equal((await f.call('/reminders/ack',{reminderId:reminder.id,expectedBasis:reminder.basis})).status,200);
  assert.equal((await f.call('/reminders/snooze',{reminderId:reminder.id,expectedBasis:reminder.basis,until:new Date(Date.now()+3600000).toISOString()})).status,200);
  const current=f.bridge.snapshot.reminders[0];assert.equal(current.dueAt,deadline);assert.equal(current.businessState,'open');assert.equal(current.displayState,'snoozed');
});
test('pending prerequisite read is not returned as a completed mutation',async t=>{
  const bridge=new DemoBridge(),original=bridge.call.bind(bridge);let queued=false;
  bridge.call=async(method,params,session,options)=>{if(method==='snapshot'&&!queued){queued=true;throw new LedgerError('rpc_pending','读取中',202,{requestId:'read-pending-001',pollUrl:'/api/v2/ledger/operations/read-pending-001'});}return original(method,params,session,options);};
  bridge.peek=async()=>({state:'complete',requestId:'read-pending-001',data:structuredClone(bridge.snapshot),context:{route:'internal-read'}});
  const f=await fixture(t,{bridge});const first=await f.call('/am/prepare',{projectId:'demo-sample',itemId:'demo-bench'});
  assert.equal(first.status,409);assert.equal(first.data.error.code,'source_refresh_pending');assert.equal(bridge.previews.size,0);
  const second=await f.call('/am/prepare',{projectId:'demo-sample',itemId:'demo-bench'});assert.equal(second.data.kind,'action');assert.equal(bridge.previews.size,1);
});
test('source outage retains last good four rows with explicit stale coverage',async t=>{
  const f=await fixture(t,{ttl:0});const before=(await f.call('/projects/demo-sample')).data;
  f.bridge.call=async()=>{throw new LedgerError('offline','离线',503);};
  const after=(await f.call('/projects/demo-sample')).data;assert.equal(after.coverage.status,'stale');
  assert.equal(after.rows[0].text,before.rows[0].text);assert.equal(after.project.id,'demo-sample');
});
test('final response retention removes expired quotes but preserves structured progress',()=>{
  const out=sanitizeEvidence({text:'负责人报告样机已齐',sourceRefs:[{quote:'原始消息',rawAvailable:true,rawExpiresAt:'2020-01-01T00:00:00Z'}]});
  assert.equal(out.text,'负责人报告样机已齐');assert.equal(out.sourceRefs[0].quote,null);assert.equal(out.sourceRefs[0].rawAvailable,false);
});
test('native mount is disabled by default and does not inspect credentials',async()=>{
  const mounted=await createNativeLedgerMount({});assert.equal(await mounted({},{}),false);
});
