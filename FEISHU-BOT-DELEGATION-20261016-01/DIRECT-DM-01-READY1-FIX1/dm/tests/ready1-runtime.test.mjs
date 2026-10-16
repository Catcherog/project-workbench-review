import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,chmodSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {generateKeyPairSync,sign} from 'node:crypto';
import {fullFixture,blockedExternal,restoreExecutionGuard} from './full-service-fixture.mjs';
import {digest,canonical,bindingOf} from '../candidate/scripts/direct-dm-authority.mjs';
import {verifyBuild} from '../candidate/scripts/direct-dm-runtime.mjs';

const root=resolve(import.meta.dirname,'../candidate');
const records=[];
async function setup({arm=true}={}){
 const c=await fullFixture(),m=c.f.manifest,buildManifest=join(root,'build-manifest.json'),buildHash=verifyBuild(root,buildManifest);
 const {publicKey,privateKey}=generateKeyPairSync('ed25519'),pem=publicKey.export({type:'spki',format:'pem'}),approvalFile=join(c.dir,'approval.json'),configFile=join(c.dir,'control.json'),cli=join(c.dir,'synthetic-cli');
 writeFileSync(cli,'synthetic executable pinned by hash; runner supplied in test mode');
 const config={version:1,enabled:true,buildManifest,buildHash,publicKey:pem,publicKeyHash:digest(pem),approvalFile,cli,cliHash:digest(readFileSync(cli,'utf8')),binding:bindingOf(m)};
 writeFileSync(configFile,JSON.stringify(config),{mode:0o600});
 const state={calls:[],sends:[],messages:new Map(),mode:'ok',readHook:null};
 const raw=(id,chat,text,who='app')=>({message_id:id,chat_id:chat,msg_type:'text',sender:{id:who==='app'?m.appId:m.participantId,id_type:who==='app'?'app_id':'open_id',sender_type:who,tenant_key:m.tenantKey},body:{content:JSON.stringify({text})},create_time:String(m.issuedAt+(who==='app'?0:100)),deleted:false});
 const runner=async(_file,args,{signal}={})=>{
  state.calls.push([...args]);assert.equal(args.at(-1)==='user'||args.includes('bot')||args.includes('user'),true);
  if(args[0]==='whoami'){const identity=args.at(-1);return {identity,available:true,appId:state.mode==='wrongApp'?'other':m.appId,brand:'feishu',onBehalfOf:{openId:m.ownerId}};}
  if(args[2]==='/open-apis/bot/v3/info')return {ok:true,identity:'bot',data:{open_id:m.botId,activate_status:2}};
  if(args[2]==='/open-apis/authen/v1/user_info')return {ok:true,identity:'user',data:{open_id:m.ownerId,tenant_key:state.mode==='wrongTenant'?'other':m.tenantKey}};
  if(args[1]==='+messages-send'){
   assert.equal(args[args.indexOf('--as')+1],'bot');
   const chat=args[args.indexOf('--chat-id')+1],text=args[args.indexOf('--text')+1],id='om_ready_'+(state.sends.length+1);
   state.sends.push({chat,text,id,idempotencyKey:args[args.indexOf('--idempotency-key')+1]});
   if(state.mode==='lostReceipt')throw Error('SYNTHETIC_LOST_RECEIPT');
   state.messages.set(id,raw(id,chat,text));return {ok:true,identity:'bot',data:{message_id:id,chat_id:chat}};
  }
  if(args[2]?.startsWith('/open-apis/im/v1/messages/')){
   const id=args[2].split('/').at(-1);if(state.readHook)await state.readHook(id);
   if(state.mode==='readFailure')throw Error('SYNTHETIC_READ_FAILURE');
   const value=structuredClone(state.messages.get(id));
   if(state.mode==='wrongBody')value.body.content=JSON.stringify({text:'changed'});
   if(state.mode==='formattedTime')value.create_time='2026-10-16 16:00';
   if(state.mode==='wrongSender')value.sender.id='other';
   if(state.mode==='wrongMessageTenant')value.sender.tenant_key='other';
   return {ok:true,identity:'bot',data:{items:value?[value]:[]}};
  }
  throw Error('UNEXPECTED_OFFLINE_CLI_CALL');
 };
 const app=await c.start({directDmControlFile:configFile,directDmRuntimeOptions:{runner,clock:()=>c.state.now}});if(arm)c.arm();c.state.now=m.issuedAt+1;
 const payload={version:1,task:'DIRECT-DM-01-READY1',revoked:false,buildHash,manifestHash:digest(m),binding:bindingOf(m),ledgerId:app.store.directDmIsolation.ledgerId,notBefore:m.issuedAt,expiresAt:m.expiresAt,evidence:Object.fromEntries(['review','installation','exactText','isolationPrinciple','memberVisibility','conversationBinding','read','disclose'].map(k=>[k,{approved:true,reference:'synthetic-only:'+k,sha256:digest('synthetic:'+k)}]))};
 function approve(change){if(change)change(payload);writeFileSync(approvalFile,JSON.stringify({payload,signature:sign(null,Buffer.from(canonical(payload)),privateKey).toString('base64')}),{mode:0o600});}
 approve();
 function confirmation(){const event={...c.f.event,parent_id:state.sends[0].id};const r=raw(event.message_id,event.chat_id,event.content,'user');r.parent_id=event.parent_id;state.messages.set(event.message_id,r);return event;}
 app.agentMonitor.configure('official',{revision:0,enabled:true,personal:true,discoverGroups:true,intervalSeconds:60});app.eventBridge.configure('official',{revision:0,enabled:true});
 return {c,app,m,state,config,configFile,approvalFile,payload,approve,confirmation,async close(){await c.dispose();assert.equal(c.state.externalModels,0);assert.equal(blockedExternal.length,0);}};
}
test('READY1 complete host: signed authority -> bot preview -> raw confirm -> one bot summary -> original readback',async()=>{
 const x=await setup();try{
  await x.app.directDmController.deliver(x.m.id,'preview');assert.equal(x.app.store.directDmIsolation.status(x.m.id).state,'AWAITING_CONFIRMATION');
  const event=x.confirmation();await x.app.eventBridge.ingest('official','im.message.receive_v1',event);await x.app.eventBridge.ingest('official','im.message.receive_v1',event);
  assert.equal(x.app.store.directDmIsolation.status(x.m.id).state,'DELIVERED_READBACK_VERIFIED');assert.equal(x.state.sends.length,2);
  assert.equal(x.state.sends[0].text,x.m.preview);assert.equal(x.state.sends[1].text,x.m.summary);assert.equal(x.app.store.load('official').sources.length,0);
  assert.equal(new Set(x.state.sends.map(s=>s.idempotencyKey)).size,2);records.push({case:'full-host-complete',syntheticSendCalls:2,productionSources:0,realPlatformCalls:0});
 }finally{await x.close();}
});
for(const key of ['review','installation','exactText','conversationBinding','memberVisibility'])test('READY1 absent '+key+' evidence never invokes transport',async()=>{
 const x=await setup();try{x.approve(p=>p.evidence[key].approved=false);await assert.rejects(x.app.directDmController.deliver(x.m.id,'preview'),/APPROVAL_EVIDENCE_MISSING/);assert.equal(x.state.calls.length,0);assert.equal(x.app.store.directDmIsolation.status(x.m.id).effects.length,0);}finally{await x.close();}
});
for(const kind of ['signature','snapshot','config','permissions'])test('READY1 rejects altered '+kind+' before transport',async()=>{
 const x=await setup();try{
  if(kind==='signature'){const j=JSON.parse(readFileSync(x.approvalFile));j.payload.evidence.review.reference='forged';writeFileSync(x.approvalFile,JSON.stringify(j));}
  if(kind==='snapshot')x.approve(p=>p.binding.ownerChatId='oc_changed');
  if(kind==='config'){x.config.binding.ownerChatId='oc_changed';writeFileSync(x.configFile,JSON.stringify(x.config));}
  if(kind==='permissions')chmodSync(x.approvalFile,0o644);
  await assert.rejects(x.app.directDmController.deliver(x.m.id,'preview'));assert.equal(x.state.sends.length,0);assert.equal(x.state.calls.length,0);
 }finally{await x.close();}
});
for(const mode of ['wrongApp','wrongTenant','lostReceipt','readFailure','wrongBody','formattedTime','wrongSender','wrongMessageTenant'])test('READY1 '+mode+' stays unverified and cannot resend',async()=>{
 const x=await setup();try{x.state.mode=mode;try{await x.app.directDmController.deliver(x.m.id,'preview');}catch{}
  const s=x.app.store.directDmIsolation.status(x.m.id);assert.ok(['DELIVERY_UNKNOWN','READBACK_FAILED'].includes(s.state));assert.notEqual(s.effects[0].state,'READBACK_VERIFIED');const count=x.state.sends.length;
  await assert.rejects(x.app.directDmController.deliver(x.m.id,'preview'));assert.equal(x.state.sends.length,count);records.push({case:mode,state:s.state,sendCalls:count});
 }finally{await x.close();}
});
test('READY1 revocation during original-message read prevents summary and keeps quarantine',async()=>{
 const x=await setup();try{await x.app.directDmController.deliver(x.m.id,'preview');const event=x.confirmation();x.state.readHook=async id=>{if(id===event.message_id)x.approve(p=>p.revoked=true);};await x.app.eventBridge.ingest('official','im.message.receive_v1',event);assert.equal(x.state.sends.length,1);assert.equal(x.app.store.load('official').sources.length,0);assert.equal(x.app.store.directDmIsolation.status(x.m.id).state,'AWAITING_CONFIRMATION');}finally{await x.close();}
});
test('READY1 expiry and stopped worker keep ordinary input isolated after restart with config removed',async()=>{
 const x=await setup();try{await x.app.directDmController.deliver(x.m.id,'preview');x.c.state.now=x.m.expiresAt+1;const event={...x.confirmation(),content:'ordinary new business',parent_id:'',create_time:x.m.expiresAt+1};await x.app.eventBridge.ingest('official','im.message.receive_v1',event);assert.equal(x.state.sends.length,1);await x.app.directDmController.close();await x.c.close();const app=await x.c.start({configured:false});assert.equal(app.directDmController,null);assert.ok(app.store.directDmIsolation.hold({identity:x.c.f.identity,message:{...event,message_id:'om_after_ready_restart'},channel:'test'}));assert.equal(app.store.load('official').sources.length,0);records.push({case:'worker-disabled-restart',isolation:true,sources:0});}finally{await x.close();}
});
test('READY1 thrown worker handler cannot fall through to business',async()=>{
 const x=await setup();try{x.app.eventBridge.onIsolatedMessage=async()=>{throw Error('SYNTHETIC_WORKER_OFFLINE');};await x.app.eventBridge.ingest('official','im.message.receive_v1',{...x.c.f.event,content:'ordinary business',parent_id:''});assert.equal(x.app.store.load('official').sources.length,0);assert.equal(x.state.sends.length,0);}finally{await x.close();}
});
test.after(()=>{writeFileSync(new URL('../../evidence/ready1-runtime-results.json',import.meta.url),JSON.stringify({mode:'complete isolated host with real authority and transport modules, synthetic CLI port',records,realPlatformCalls:0,realModels:0,blockedExternal},null,2));restoreExecutionGuard();});

test('READY1 signed local import latches one request and performs no I/O',async()=>{
 const x=await setup({arm:false});try{assert.equal(x.app.store.db.prepare('PRAGMA user_version').get().user_version,2);assert.equal(x.app.directDmController.register(x.m).state,'PREPARED');assert.equal(x.app.store.db.prepare('PRAGMA user_version').get().user_version,3);assert.equal(x.state.calls.length,0);assert.throws(()=>x.app.directDmController.register(x.m),/ALREADY_REGISTERED/);}finally{await x.close();}
});
test('READY1 principle approval alone cannot register a request or change data capability',async()=>{
 const x=await setup({arm:false});try{x.approve(p=>p.evidence.installation.approved=false);assert.throws(()=>x.app.directDmController.register(x.m),/APPROVAL_EVIDENCE_MISSING/);assert.equal(x.app.store.directDmIsolation.db.prepare('SELECT COUNT(*) n FROM requests').get().n,0);assert.equal(x.app.store.db.prepare('PRAGMA user_version').get().user_version,2);assert.equal(x.state.calls.length,0);}finally{await x.close();}
});
test('READY1 tampered manifest cannot register even with genuine approval of another manifest',async()=>{
 const x=await setup({arm:false});try{assert.throws(()=>x.app.directDmController.register({...x.m,ownerChatId:'oc_changed'}),/APPROVAL_BINDING|EXECUTION_BINDING_MISMATCH/); // Same denial, now also possible at the earlier execution-binding check.
assert.equal(x.app.store.directDmIsolation.db.prepare('SELECT COUNT(*) n FROM requests').get().n,0);assert.equal(x.state.calls.length,0);}finally{await x.close();}
});
