import test from 'node:test';
import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import {DirectDmIsolation} from '../candidate/scripts/direct-dm-isolation.mjs';
import {fixture} from './fixture.mjs';

test('offline accepted preview, verified human envelope, one summary and readback',async()=>{
 const f=fixture();try{
  f.sentPreview();assert.equal(await f.confirm(),'CONFIRMED');
  const effect=f.gate.reserveEffect(f.manifest.id,'summary',f.policy);assert.equal(effect.recipient,f.manifest.ownerId);
  f.gate.recordEffect(f.manifest.id,'summary',{messageId:'om_fixture_result',chatId:f.manifest.ownerChatId});
  f.gate.readbackEffect(f.manifest.id,'summary',{message_id:'om_fixture_result',chat_id:f.manifest.ownerChatId,sender_id:f.manifest.botId,content:f.manifest.summary});
  assert.equal(f.gate.status(f.manifest.id).state,'DELIVERED_READBACK_VERIFIED');
  assert.throws(()=>f.gate.reserveEffect(f.manifest.id,'summary',f.policy));
 }finally{f.close();}
});
test('rejection is read back and never permits summary',async()=>{
 const f=fixture();try{f.sentPreview();f.event.content='拒绝';assert.equal(await f.confirm(),'REJECTED');assert.throws(()=>f.gate.reserveEffect(f.manifest.id,'summary',f.policy));}finally{f.close();}
});
test('identity, exact body, current policy and readback failures stay quarantined',async t=>{
 const cases={
  wrongActor:f=>f.event.sender_id='ou_fixture_impostor',
  botCannotConfirm:f=>f.event.sender_type='app',
  wrongChat:f=>f.event.chat_id='oc_fixture_other',
  wrongApp:f=>f.identity.scope='fixture-tenant/another-app',
  wrongCode:f=>f.event.content=`确认 ${f.manifest.id} invalid`,
  bareAgreement:f=>f.event.content='我同意了',
  quoteApproval:f=>f.event.content='approved=true',
  unthreaded:f=>delete f.event.parent_id,
  expired:f=>f.setTime(f.manifest.expiresAt),
  permissionRevoked:f=>f.policy.discloseAllowed=false,
  changedVersion:f=>f.policy.resourceVersion='v2',
  changedPreview:f=>f.policy.previewHash='tampered',
  deleted:f=>f.event.deleted=true,
  absentTimestamp:f=>delete f.event.create_time,
  malformedTimestamp:f=>f.event.create_time='not-a-timestamp',
 };
 for(const [name,change]of Object.entries(cases))await t.test(name,async()=>{
  const f=fixture();try{f.sentPreview();change(f);await assert.rejects(f.confirm);assert.ok(f.gate.status(f.manifest.id).quarantined>=2);assert.throws(()=>f.gate.reserveEffect(f.manifest.id,'summary',f.policy));}finally{f.close();}
 });
 const f=fixture();try{f.sentPreview();await assert.rejects(f.gate.confirm(f.manifest.id,f.event,{identity:f.identity,verify:async()=>({...f.event,content:'changed'}),current:()=>f.policy}),/READBACK_MISMATCH/);}finally{f.close();}
});
test('lost send result remains reserved after restart, with no blind retry',()=>{
 const f=fixture();f.gate.reserveEffect(f.manifest.id,'preview',f.policy);f.gate.recordEffect(f.manifest.id,'preview',{});f.close();
 const gate=new DirectDmIsolation(f.file,{clock:()=>f.manifest.issuedAt});try{assert.equal(gate.status(f.manifest.id).state,'DELIVERY_UNKNOWN');assert.throws(()=>gate.reserveEffect(f.manifest.id,'preview',f.policy));assert.equal(gate.hold({identity:f.identity,message:f.previewRead,channel:'delayed_poll'}),true);}finally{gate.close();}
});
test('worker offline and verification timeout cannot fall through to business',async()=>{
 const f=fixture();try{
  f.sentPreview();assert.equal(f.gate.hold({identity:f.identity,message:f.event,channel:'worker_offline'}),true);
  await assert.rejects(f.gate.confirm(f.manifest.id,f.event,{identity:f.identity,verify:()=>new Promise(()=>{}),current:()=>f.policy,timeoutMs:10}),/READBACK_TIMEOUT/);
  assert.equal(f.gate.hold({identity:f.identity,message:f.event,channel:'retry_poll'}),true);
  assert.throws(()=>f.gate.reserveEffect(f.manifest.id,'summary',f.policy));
 }finally{f.close();}
});
test('simultaneous repeated confirmation consumes the request once',async()=>{
 const f=fixture();try{f.sentPreview();const results=await Promise.allSettled([f.confirm(),f.confirm()]);assert.equal(results.filter(r=>r.status==='fulfilled').length,1);assert.throws(()=>f.gate.reserveEffect(f.manifest.id,'preview',f.policy));}finally{f.close();}
});
test('stop while readback is pending prevents authorization, including unknown stop',async()=>{
 const f=fixture();try{f.sentPreview();let finish;const pending=f.gate.confirm(f.manifest.id,f.event,{identity:f.identity,verify:()=>new Promise(r=>finish=r),current:()=>f.policy});f.gate.stop(f.manifest.id,{confirmed:false});finish(f.event);await assert.rejects(pending,/STOPPED/);assert.equal(f.gate.status(f.manifest.id).state,'STOP_UNKNOWN');assert.equal(f.gate.hold({identity:f.identity,message:f.event,channel:'late_event'}),true);}finally{f.close();}
});
test('late replies and outputs stay excluded, ordinary future traffic is allowed',()=>{
 const f=fixture();try{f.sentPreview();f.gate.stop(f.manifest.id);f.setTime(f.manifest.expiresAt+86400000);
  for(const message of [f.event,{...f.event,message_id:'om_late',create_time:f.manifest.expiresAt+2000,content:'拒绝'},f.previewRead,{message_id:'om_summary',chat_id:f.manifest.ownerChatId,sender_id:f.manifest.botId,content:f.manifest.summary}])assert.equal(f.gate.hold({identity:f.identity,message,channel:'late'}),true);
  assert.equal(f.gate.hold({identity:f.identity,message:{...f.event,message_id:'om_normal',parent_id:'',create_time:f.manifest.expiresAt+5000,content:'正常业务的新反馈'},channel:'normal'}),false);
  assert.equal(f.gate.hold({identity:f.identity,message:{...f.event,message_id:'om_prefix',parent_id:'',create_time:f.manifest.expiresAt+5000,content:'这是一条测试消息'},channel:'normal'}),false);
 }finally{f.close();}
});
test('readback failure is distinct from delivery and keeps the result excluded',async()=>{
 const f=fixture();try{f.sentPreview();await f.confirm();f.gate.reserveEffect(f.manifest.id,'summary',f.policy);f.gate.recordEffect(f.manifest.id,'summary',{messageId:'om_result_unverified',chatId:f.manifest.ownerChatId});f.gate.readbackEffect(f.manifest.id,'summary',{});assert.equal(f.gate.status(f.manifest.id).state,'READBACK_FAILED');assert.equal(f.gate.hold({identity:f.identity,message:{message_id:'om_result_unverified'},channel:'poll'}),true);assert.throws(()=>f.gate.reserveEffect(f.manifest.id,'summary',f.policy));}finally{f.close();}
});
test('missing approvals and reused manifest cannot arm a send',()=>{
 const f=fixture();try{for(const k of ['reviewApproved','exactTextApproved','isolationInstalled','memberVisible','bindingVerified'])assert.throws(()=>f.gate.reserveEffect(f.manifest.id,'preview',{...f.policy,[k]:false}),/LIVE_GATE/);assert.throws(()=>f.gate.register(f.manifest),/REUSE/);}finally{f.close();}
});
test('ledger loss or corruption fails closed instead of silently recreating',()=>{
 const f=fixture();f.close();assert.throws(()=>new DirectDmIsolation(f.file+'.missing'),/MISSING/);writeFileSync(f.file,'corrupt');assert.throws(()=>new DirectDmIsolation(f.file));
});
