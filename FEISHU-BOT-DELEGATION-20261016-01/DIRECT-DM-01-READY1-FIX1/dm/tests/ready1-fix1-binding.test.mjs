import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {setup} from './binding-full-fixture.mjs';
import {activationKey,activationFile} from '../candidate/scripts/direct-dm-activation.mjs';
import {blockedExternal,restoreExecutionGuard} from './full-service-fixture.mjs';
const records=[];
const counts=x=>({requests:x.app.store.directDmIsolation.db.prepare('SELECT COUNT(*) n FROM requests').get().n,effects:x.app.store.directDmIsolation.db.prepare('SELECT COUNT(*) n FROM effects').get().n,capability:x.app.store.db.prepare('PRAGMA user_version').get().user_version,marker:existsSync(activationFile(x.c.dataDir)),setting:x.app.store.getSetting(activationKey),sendCalls:x.state.sends.length});
const untouched={requests:0,effects:0,capability:2,marker:false,setting:null,sendCalls:0};
const ordinary=(x,overrides={})=>({...x.c.f.event,message_id:'om_plain_after_binding_fix',parent_id:'',root_id:'',content:'ordinary new business without a marker',create_time:x.m.expiresAt+1000,...overrides});
const patches={
 tenant:{tenantKey:'tenant_other',scope:'tenant_other/fixture-app'},
 scope:{scope:'different/fixture-app'},app:{appId:'app_other',scope:'fixture-tenant/app_other'},
 owner:{ownerId:'ou_other_owner'},participant:{participantId:'ou_other_participant'},bot:{botId:'ou_other_bot'},
 ownerChat:{ownerChatId:'oc_other_owner'},participantChat:{participantChatId:'oc_other_participant'},
 policyVersion:{policyVersion:'different'},resourceVersion:{resourceVersion:'v2'},purpose:{purpose:'different-purpose'},summaryHash:{summaryHash:'a'.repeat(64)},previewHash:{previewHash:'b'.repeat(64)},
 swappedRoles:{ownerId:'ou_fixture_participant',participantId:'ou_fixture_owner',ownerChatId:'oc_fixture_bot_participant',participantChatId:'oc_fixture_bot_owner'},
 missingScope:{scope:undefined},nonStringOwner:{ownerId:123},emptyVersion:{policyVersion:''},extraField:{unapprovedField:'extra'}
};
for(const [name,configPatch] of Object.entries(patches))test('B01 complete host rejects initial '+name+' before durable registration',async()=>{
 const x=await setup({configPatch});try{
  assert.deepEqual(counts(x),untouched);assert.throws(()=>x.app.directDmController.register(x.m),/EXECUTION_BINDING_MISMATCH/);
  assert.deepEqual(counts(x),untouched);assert.equal(x.state.calls.length,0);assert.equal(x.app.store.load('official').sources.length,0);
  records.push({case:'initial-'+name,...counts(x),platformAndConfigSelfConsistent:true});
 }finally{await x.close();}
});
test('B01 complete host matching signed admission, preview, original confirmation, one summary and persistent isolation',async()=>{
 const x=await setup();try{
  assert.equal(x.app.directDmController.register(x.m).state,'PREPARED');assert.equal(x.state.calls.length,0);
  await x.app.directDmController.deliver(x.m.id,'preview');const event=x.confirmation();await x.app.eventBridge.ingest('official','im.message.receive_v1',event);await x.app.eventBridge.ingest('official','im.message.receive_v1',event);
  assert.equal(x.app.store.directDmIsolation.status(x.m.id).state,'DELIVERED_READBACK_VERIFIED');assert.equal(x.state.sends.length,2);assert.equal(x.state.sends[1].text,x.m.summary);
  x.c.state.now=x.m.expiresAt+1001;await x.app.eventBridge.ingest('official','im.message.receive_v1',ordinary(x));assert.equal(x.app.store.load('official').sources.length,0);
  assert.equal(x.app.store.directDmIsolation.hold({identity:x.c.f.identity,message:ordinary(x,{message_id:'om_other_chat',chat_id:'oc_other_normal'}),channel:'control'}),false);
  records.push({case:'matching-full-chain',state:'DELIVERED_READBACK_VERIFIED',syntheticSendCalls:2,sources:0});
 }finally{await x.close();}
});
for(const [key,value,code] of [['tenantKey','other','PLATFORM_TENANT_CHANGED'],['appId','other','PLATFORM_APP_CHANGED'],['ownerId','ou_other','PLATFORM_OPERATOR_CHANGED'],['botId','ou_other','PLATFORM_BOT_CHANGED']])test('B01 platform '+key+' must match the same approved binding',async()=>{
 const x=await setup({platformPatch:{[key]:value}});try{x.app.directDmController.register(x.m);await assert.rejects(x.app.directDmController.deliver(x.m.id,'preview'),new RegExp(code));assert.equal(x.state.sends.length,0);assert.equal(x.app.store.directDmIsolation.status(x.m.id).state,'DELIVERY_UNKNOWN');}finally{await x.close();}
});
test('B01 original signature control still rejects before registration or capability change',async()=>{
 const x=await setup();try{const e=JSON.parse(readFileSync(x.approvalFile));e.signature=Buffer.alloc(64).toString('base64');writeFileSync(x.approvalFile,JSON.stringify(e));assert.throws(()=>x.app.directDmController.register(x.m),/APPROVAL_SIGNATURE_INVALID/);assert.deepEqual(counts(x),untouched);}finally{await x.close();}
});
test('B01 mismatched restart stops active work and preserves original passive isolation and unknown facts',async()=>{
 const x=await setup();try{
  x.app.directDmController.register(x.m);x.state.mode='lostReceipt';await assert.rejects(x.app.directDmController.deliver(x.m.id,'preview'));
  const gate=x.app.store.directDmIsolation,request=gate.request(x.m.id),effects=gate.db.prepare('SELECT * FROM effects').all(),marker=readFileSync(activationFile(x.c.dataDir),'utf8'),saved=x.app.store.getSetting(activationKey);await x.c.close();
  x.config.binding={...x.config.binding,tenantKey:'other',scope:'other/fixture-app'};writeFileSync(x.configFile,JSON.stringify(x.config));
  const restarted=await x.c.start({configured:false,directDmControlFile:x.configFile,directDmRuntimeOptions:{runner:x.runner,clock:()=>x.c.state.now}});
  await assert.rejects(restarted.directDmController.deliver(x.m.id,'preview'),/EXECUTION_BINDING_MISMATCH/);assert.equal(x.state.sends.length,1);
  assert.deepEqual(restarted.store.directDmIsolation.request(x.m.id),request);assert.deepEqual(restarted.store.directDmIsolation.db.prepare('SELECT * FROM effects').all(),effects);assert.equal(readFileSync(activationFile(x.c.dataDir),'utf8'),marker);assert.deepEqual(restarted.store.getSetting(activationKey),saved);assert.equal(restarted.store.db.prepare('PRAGMA user_version').get().user_version,3);
  x.c.state.now=x.m.expiresAt+1001;await restarted.eventBridge.ingest('official','im.message.receive_v1',ordinary(x));assert.equal(restarted.store.load('official').sources.length,0);
  await x.c.close();const passive=await x.c.start({configured:false});assert.equal(passive.directDmController,null);assert.equal(passive.store.directDmIsolation.hold({identity:x.c.f.identity,message:ordinary(x,{message_id:'om_missing_config'}),channel:'test'}),true);assert.deepEqual(passive.store.directDmIsolation.request(x.m.id),request);
  records.push({case:'mismatched-restart',activeRejected:true,passiveHold:true,capability:3,unknownFactPreserved:true,blindResends:0});
 }finally{await x.close();}
});
test('B01 changed signed approval after admission cannot redirect the registered request',async()=>{
 const x=await setup();try{x.app.directDmController.register(x.m);const before=x.app.store.directDmIsolation.request(x.m.id);x.approve(p=>p.binding.botId='ou_changed');await assert.rejects(x.app.directDmController.deliver(x.m.id,'preview'),/APPROVAL_BINDING_INVALID/);assert.equal(x.state.calls.length,0);assert.deepEqual(x.app.store.directDmIsolation.request(x.m.id),before);assert.equal(x.app.store.directDmIsolation.hold({identity:x.c.f.identity,message:ordinary(x),channel:'test'}),true);}finally{await x.close();}
});
for(const kind of ['config','approval'])test('B01 '+kind+' change during platform identity reads is rejected before send',async()=>{
 const x=await setup();try{x.app.directDmController.register(x.m);x.state.identityHook=async()=>{if(kind==='config'){x.config.binding.botId='ou_changed';writeFileSync(x.configFile,JSON.stringify(x.config));}else x.approve(p=>p.binding.botId='ou_changed');};await assert.rejects(x.app.directDmController.deliver(x.m.id,'preview'));assert.equal(x.state.sends.length,0);assert.equal(x.app.store.directDmIsolation.status(x.m.id).state,'DELIVERY_UNKNOWN');assert.equal(x.app.store.directDmIsolation.hold({identity:x.c.f.identity,message:ordinary(x),channel:'test'}),true);}finally{await x.close();}
});
test('B01 controller cannot swap the actual transport or mutate its bound identity',async()=>{
 const x=await setup();try{const controller=x.app.directDmController;assert.throws(()=>{controller.transport={binding:{botId:'other'}};},TypeError);assert.throws(()=>{controller.transport.binding.botId='other';},TypeError);assert.throws(()=>{controller.transport.binding={...x.config.binding,ownerId:'other'};},TypeError);assert.equal(x.state.calls.length,0);}finally{await x.close();}
});
test('B01 untrusted event identity never grants summary even when its request marker matches',async()=>{
 const x=await setup();try{x.app.directDmController.register(x.m);await x.app.directDmController.deliver(x.m.id,'preview');const before=x.state.calls.length;await x.app.directDmController.handle({identity:{...x.c.f.identity,scope:'other/fixture-app',tenantKey:'other'},message:x.confirmation()});assert.equal(x.state.sends.length,1);assert.equal(x.state.calls.length,before);assert.equal(x.app.store.directDmIsolation.status(x.m.id).state,'AWAITING_CONFIRMATION');assert.equal(x.app.store.load('official').sources.length,0);}finally{await x.close();}
});
test.after(()=>{assert.equal(blockedExternal.length,0);writeFileSync(new URL('../../evidence/ready1-fix1/after/full-host-binding.json',import.meta.url),JSON.stringify({mode:'actual full host; synthetic CLI port; no reviewer host shim',records,blockedExternal,realPlatformCalls:0,realModelCalls:0},null,2));restoreExecutionGuard();});
