import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,renameSync,existsSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {activationFile,activationKey} from '../candidate/scripts/direct-dm-activation.mjs';
import {createIsolationLedger,DirectDmIsolation} from '../candidate/scripts/direct-dm-isolation.mjs';
import {fullFixture,blockedExternal,restoreExecutionGuard,freePort} from './full-service-fixture.mjs';
import {startServer as legacyStartServer} from '../candidate/scripts/legacy-local-http.fixture.mjs';

const records=[];
const end=async c=>{assert.equal(c.state.externalModels,0);await c.dispose();assert.equal(blockedExternal.length,0);};
function late(c,id,more={}){return {...c.f.event,message_id:id,parent_id:'',root_id:'',create_time:c.f.manifest.expiresAt+1000,content:'Unthreaded arbitrary late input',...more};}
function source(c,m){return {id:'source-'+m.message_id,excerpt:m.content,personalMessage:{scope:c.f.identity.scope,accountId:c.f.identity.userId,messageId:m.message_id,chatId:m.chat_id,senderId:m.sender_id,rawCreateTime:String(m.create_time),parentId:m.parent_id,rootId:m.root_id}};}
test('complete candidate service boots without isolation when never activated',async()=>{
 const c=await fullFixture();try{const app=await c.start({configured:false});const response=await fetch(app.origin+'/api/v2/status');const status=await response.json();assert.equal(status.application,'pm-workbench');assert.equal(status.ready,true);assert.equal(status.testMode,true);assert.equal(app.store.directDmIsolation,undefined);assert.equal(app.store.db.prepare('PRAGMA user_version').get().user_version,2);records.push({case:'ordinary-boot',ready:true,testMode:true,isolation:false,version:2});}finally{await end(c);}
});
test('full host routes event, polling, discovery and final storage through durable isolation',async()=>{
 const c=await fullFixture();try{
  const app=await c.start();c.arm();assert.equal(app.store.db.prepare('PRAGMA user_version').get().user_version,3);
  app.agentMonitor.configure('official',{revision:0,enabled:true,personal:true,discoverGroups:true,intervalSeconds:60});app.eventBridge.configure('official',{revision:0,enabled:true});
  const groupId='oc_synthetic_discovery';c.state.groups=[{chat_id:groupId,name:'Synthetic group'}]; // Existing membership baseline, not a newly joined group.
  c.state.now=c.f.manifest.expiresAt+2000;const incoming=late(c,'om_full_late');
  await app.eventBridge.ingest('official','im.message.receive_v1',incoming);assert.equal(app.store.load('official').sources.length,0);
  c.state.messages=[incoming];await app.agentMonitor.poll('official');assert.equal(app.store.load('official').sources.length,0);
  // Advance only the synthetic poll cursor to include the known late timestamp.
  let control=app.agentMonitor.control('official');control.personalThrough=new Date(c.f.manifest.expiresAt-1000).toISOString();app.agentMonitor.save('official',control);
  await app.agentMonitor.poll('official');assert.equal(app.store.load('official').sources.length,0);
  const groupCopy=late(c,'om_group_copy',{chat_id:groupId,chat_type:'group',content:'request '+c.f.manifest.id});c.state.messages=[groupCopy];
  await app.agentMonitor.poll('official');assert.equal(app.store.load('official').sources.length,0);assert.equal(Object.keys(app.agentMonitor.control('official').discoveryState.groups).length,0);
  // Deliberately omit early filtering; final SQLite guard must still reject root-only evidence.
  c.state.now=c.f.manifest.issuedAt+100;c.f.sentPreview();
  app.store.directDmIsolation.reserveEffect(c.f.manifest.id,'preview',c.f.policy);
  app.store.directDmIsolation.recordEffect(c.f.manifest.id,'preview',{messageId:'om_full_preview',chatId:c.f.manifest.participantChatId});
  const rooted=late(c,'om_final_root',{chat_id:'oc_unreserved',root_id:'om_full_preview',content:'no marker'}),before=app.store.load('official'),next=structuredClone(before);next.revision++;next.sources.push(source(c,rooted));
  assert.throws(()=>app.store.transaction(()=>app.store.save(next,before.revision)),/TEST_SOURCE_BLOCKED/);assert.deepEqual(app.store.load('official'),before);
  // Same person in another normal conversation keeps the existing business path.
  c.state.now=c.f.manifest.expiresAt+3000;c.state.messages=[late(c,'om_normal_other_chat',{chat_id:'oc_normal_business',content:'Ordinary business feedback'})];await app.agentMonitor.poll('official');
  assert.equal(app.store.load('official').sources.length,1);assert.equal(app.store.load('official').sources[0].personalMessage.chatId,'oc_normal_business');
  records.push({case:'full-ingress',testSources:0,ordinaryOtherChatSources:1,eventConsumerMode:app.eventBridge.status('official').streams['im.message.receive_v1'].status,mockReads:c.state.reads.length});
 }finally{await end(c);}
});
test('full host blocks legacy leaked source before input, budget retry or automatic receipt',async()=>{
 const c=await fullFixture();try{
  const app=await c.start(),s=app.store.load('official'),message=late(c,'om_legacy_fixture');
  const row={...source(c,message),inputEnvelope:{origin:'feishu',actor:'colleague',jobId:'synthetic-job'}};s.sources.push(row);s.revision++;app.store.save(s,s.revision-1);c.arm();
  let modelStarts=0;app.assistant.start=async()=>{modelStarts++;throw Error('should never start');};app.assistant.get=()=>{modelStarts++;throw Error('should never inspect an untrusted job');};
  assert.equal((await app.coreInbox.receive({workspaceId:'official',sourceId:row.id,identity:c.f.identity,parentId:'',senderId:message.sender_id})).status,'test_quarantined');
  assert.equal((await app.coreInbox.receipt({workspaceId:'official',sourceId:row.id})).status,'test_quarantined');await app.coreInbox.resumeBudgetQueue('official');
  assert.equal(modelStarts,0);assert.equal(c.state.reads.length,0);records.push({case:'downstream-legacy-fixture',syntheticPreexistingSource:1,newSources:0,modelStarts,sendCalls:0});
 }finally{await end(c);}
});
test('full service restores passive isolation without the temporary configuration',async()=>{
 const c=await fullFixture();try{
  const app=await c.start();c.arm();const id=c.f.manifest.id;app.store.directDmIsolation.stop(id);await c.close();
  const recovered=await c.start({configured:false});assert.ok(recovered.store.directDmIsolation);assert.equal(recovered.store.directDmIsolation.hold({identity:c.f.identity,message:late(c,'om_after_restart'),channel:'event'}),true);
  assert.throws(()=>recovered.store.directDmIsolation.reserveEffect(id,'preview',c.f.policy));assert.ok(recovered.store.getSetting(activationKey));assert.ok(existsSync(activationFile(c.dataDir)));
  records.push({case:'restart-config-absent',loadedFromPersistentRegistry:true,lateHeld:true,newExecutionAllowed:false});
 }finally{await end(c);}
});
test('full service refuses a redirect to another empty ledger',async()=>{
 const c=await fullFixture();try{await c.start();c.arm();await c.close();const other=join(c.dir,'other.sqlite');createIsolationLedger(other);await assert.rejects(c.start({configuredFile:other}),/ISOLATION_LEDGER_REDIRECT_DENIED/);records.push({case:'redirect-empty',bootRejected:true});}finally{await end(c);}
});
test('full service fails closed on lost ledger and retains history after restoring the file',async()=>{
 const c=await fullFixture();try{await c.start();c.arm();await c.close();renameSync(c.ledger,c.ledger+'.preserved');await assert.rejects(c.start({configured:false}),/ISOLATION_LEDGER_MISSING/);renameSync(c.ledger+'.preserved',c.ledger);const app=await c.start({configured:false});assert.equal(app.store.directDmIsolation.request(c.f.manifest.id).manifest.id,c.f.manifest.id);records.push({case:'ledger-missing',bootRejected:true,originalHistoryPreserved:true});}finally{await end(c);}
});
test('full service fails closed on corrupt ledger without creating an empty replacement',async()=>{
 const c=await fullFixture();try{await c.start();c.arm();await c.close();const original=readFileSync(c.ledger);writeFileSync(c.ledger,'synthetic corruption');await assert.rejects(c.start({configured:false}));assert.equal(readFileSync(c.ledger,'utf8'),'synthetic corruption');writeFileSync(c.ledger,original);const app=await c.start({configured:false});assert.equal(app.store.directDmIsolation.request(c.f.manifest.id).manifest.id,c.f.manifest.id);records.push({case:'ledger-corrupt',bootRejected:true,noEmptyReplacement:true,originalHistoryPreserved:true});}finally{await end(c);}
});
test('same path with a different empty ledger is rejected by persistent ledger identity',async()=>{
 const c=await fullFixture();try{await c.start();c.arm();await c.close();renameSync(c.ledger,c.ledger+'.preserved');createIsolationLedger(c.ledger);await assert.rejects(c.start({configured:false}),/ISOLATION_LEDGER_ID_CHANGED/);records.push({case:'same-path-empty',bootRejected:true,originalFileRetained:true});}finally{await end(c);}
});
test('missing sidecar or missing database registration cannot silently disable isolation',async t=>{
 for(const kind of ['sidecar','setting'])await t.test(kind,async()=>{const c=await fullFixture();try{await c.start();c.arm();await c.close();if(kind==='sidecar')renameSync(activationFile(c.dataDir),activationFile(c.dataDir)+'.preserved');else{const db=new DatabaseSync(join(c.dataDir,'workbench.sqlite'));db.prepare('DELETE FROM settings WHERE key=?').run(activationKey);db.close();}await assert.rejects(c.start({configured:false}),/ISOLATION_PERSISTENT_REGISTRATION_MISSING/);records.push({case:'missing-'+kind,bootRejected:true});}finally{await end(c);}});
});
test('old full host refuses the latched data version before starting consumers',async()=>{
 const c=await fullFixture();try{await c.start();c.arm();await c.close();await assert.rejects(legacyStartServer({...c.base,port:await freePort()}),/数据库版本高于/);records.push({case:'legacy-host-rollback',bootRejectedBeforeConsumers:true,version:3});}finally{await end(c);}
});
test('a second active consumer cannot take over or rewrite a live sending intent',async()=>{
 const c=await fullFixture();try{const app=await c.start();c.arm();c.state.now=c.f.manifest.issuedAt+1;const gate=app.store.directDmIsolation;gate.reserveEffect(c.f.manifest.id,'preview',c.f.policy);const observer=new DirectDmIsolation(c.ledger,{clock:()=>c.state.now});try{assert.equal(observer.status(c.f.manifest.id).state,'PREVIEW_PENDING');assert.equal(observer.status(c.f.manifest.id).effects[0].state,'SENDING');assert.throws(()=>observer.reserveEffect(c.f.manifest.id,'preview',c.f.policy));assert.equal(observer.hold({identity:c.f.identity,message:late(c,'om_passive_other_consumer'),channel:'observer'}),true);}finally{observer.close();}records.push({case:'concurrent-consumer',activeIntentPreserved:true,secondSendDenied:true,passiveHold:true});}finally{await end(c);}
});
test.after(()=>{assert.equal(blockedExternal.length,0);restoreExecutionGuard();mkdirSync('../evidence/after',{recursive:true});writeFileSync('../evidence/after/full-service-results.json',JSON.stringify({mode:'complete candidate host, isolated SQLite, mock platform, no UI claim',records,blockedExternalExecutions:blockedExternal,realPlatformCalls:0,realModelCalls:0},null,2));});
