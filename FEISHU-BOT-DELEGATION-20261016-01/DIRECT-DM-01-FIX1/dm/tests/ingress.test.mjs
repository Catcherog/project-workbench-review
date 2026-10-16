import test from 'node:test';
import assert from 'node:assert/strict';
import {join} from 'node:path';
import {LocalStore} from '../candidate/scripts/local-store.mjs';
import {AgentMonitor} from '../candidate/scripts/agent-monitor.mjs';
import {PersonalMessageReader} from '../candidate/scripts/personal-message-reader.mjs';
import {NewGroupReader} from '../candidate/scripts/new-group-reader.mjs';
import {FeishuEventBridge} from '../candidate/scripts/feishu-event-bridge.mjs';
import {CoreFeishuInput} from '../candidate/scripts/core-feishu-input.mjs';
import * as domain from '../candidate/dist-local/domain.mjs';
import {fixture} from './fixture.mjs';

async function workspace(f) {
 const store=new LocalStore(join(f.directory,'business'),{testMode:true});await store.initialize(null);
 store.insert(domain.emptyState('synthetic','Synthetic offline work area','demo'));store.directDmIsolation=f.gate;return store;
}
function shortcut(e) {return {...e,sender:{id:e.sender_id,sender_type:e.sender_type},create_time:String(e.create_time),msg_type:'text'};}
function raw(e) {return {...shortcut(e),body:{content:JSON.stringify({text:e.content})}};}
test('actual event bridge excludes preview, reply and output before business read/write',async()=>{
 const f=fixture(),store=await workspace(f);let calls=0,onMessage=0;const monitor=new AgentMonitor({store,domain,testMode:true,clock:()=>new Date(f.manifest.issuedAt-1000).toISOString()});
 monitor.configure('synthetic',{revision:0,enabled:true,personal:false,intervalSeconds:60});
 const bridge=new FeishuEventBridge({store,domain,monitor,testMode:true,client:{identity:async()=>f.identity,run:async()=>{calls++;throw Error('Unexpected business read');}},onMessage:()=>onMessage++});
 bridge.configure('synthetic',{revision:0,enabled:true});
 try{for(const event of [f.previewRead,f.event,{message_id:'om_result',chat_id:f.manifest.ownerChatId,sender_id:f.manifest.botId,content:f.manifest.summary}])await bridge.ingest('synthetic','im.message.receive_v1',event);
  assert.equal(store.load('synthetic').sources.length,0);assert.equal(calls,0);assert.equal(onMessage,0);
 }finally{await bridge.close();await monitor.close();store.close();f.close();}
});
test('actual private and mention readers exclude test data but retain normal messages',async()=>{
 const f=fixture();let calls=0;const normal={...f.event,message_id:'om_normal',chat_id:'oc_ordinary',content:'正常反馈',parent_id:'',create_time:f.manifest.issuedAt+500};
 const client={run:async args=>{calls++;return args[0]==='api'?{items:[raw(f.event),raw(normal)]}:{messages:[shortcut(f.event),shortcut(normal)],has_more:false};}};
 try{const result=await new PersonalMessageReader({client}).read({start:new Date(f.manifest.issuedAt).toISOString(),end:new Date(f.manifest.expiresAt).toISOString(),identity:f.identity,isolation:f.gate});
  assert.deepEqual(result.messages.map(x=>x.message_id),['om_normal']);assert.deepEqual(result.messages[0].channels,['private','mention']);assert.equal(calls,4);
 }finally{f.close();}
});
test('actual group discovery blocks copied test triggers and messages',async()=>{
 const f=fixture(),group='oc_fixture_group',event={...f.event,chat_id:group,chat_type:'group'};let groupReads=0;
 const client={run:async args=>{
  if(args[1]==='+chat-list')return {chats:[{chat_id:group,name:'Synthetic group'}],has_more:false};
  if(args[1]==='+chat-messages-list'){groupReads++;return {messages:[shortcut(event)],has_more:false};}
  if(args[0]==='api')return {items:[raw(event)]};throw Error('unexpected read');
 }};
 try{
  const reader=new NewGroupReader(client),start=new Date(f.manifest.issuedAt).toISOString(),end=new Date(f.manifest.expiresAt).toISOString();
  const first=await reader.read({start,end,triggers:[shortcut(event)],identity:f.identity,isolation:f.gate});assert.equal(Object.keys(first.state.groups).length,0);assert.equal(groupReads,0);
  const state={membershipIds:[group],listedAt:start,groups:{[group]:{id:group,name:'Synthetic group',since:start,through:start}}};
  const next=await reader.read({start,end,state,identity:f.identity,isolation:f.gate});assert.equal(next.messages.length,0);assert.equal(groupReads,1);
 }finally{f.close();}
});
test('actual monitor final barrier catches a reader that omitted early filtering',async()=>{
 const f=fixture(),store=await workspace(f);let time=f.manifest.issuedAt-1000;
 const reader={identity:async()=>f.identity,read:async()=>({messages:[shortcut(f.event)],complete:true,issues:[]})};
 const monitor=new AgentMonitor({store,domain,reader,testMode:true,clock:()=>new Date(time).toISOString()});
 monitor.configure('synthetic',{revision:0,enabled:true,personal:true,intervalSeconds:60});time+=2000;
 try{await monitor.poll('synthetic');const state=store.load('synthetic');assert.equal(state.sources.length,0);assert.equal(monitor.status('synthetic').pending,0);assert.equal(monitor.status('synthetic').lastError,'');}finally{await monitor.close();store.close();f.close();}
});
test('actual final storage barrier blocks injected test sources atomically',async()=>{
 const f=fixture(),store=await workspace(f);try{
  const prior=store.load('synthetic'),state=structuredClone(prior);state.revision++;state.sources.push({id:'synthetic-test-source',excerpt:f.event.content,personalMessage:{scope:f.identity.scope,accountId:f.identity.userId,messageId:f.event.message_id,chatId:f.event.chat_id,senderId:f.event.sender_id,rawCreateTime:String(f.event.create_time)}});
  assert.throws(()=>store.transaction(()=>store.save(state,prior.revision)),/TEST_SOURCE_BLOCKED/);assert.deepEqual(store.load('synthetic'),prior);
  const ordinary=structuredClone(prior);ordinary.revision++;store.save(ordinary,prior.revision);assert.equal(store.load('synthetic').revision,ordinary.revision);
 }finally{store.close();f.close();}
});
test('actual input and automatic receipt paths stop before model or send',async()=>{
 const f=fixture();let effects=0;const source={id:'fixture-source',excerpt:f.event.content,personalMessage:{scope:f.identity.scope,accountId:f.identity.userId,messageId:f.event.message_id,chatId:f.event.chat_id,senderId:f.event.sender_id},inputEnvelope:{origin:'feishu',actor:'colleague',jobId:'fixture-job'}};
 const input=new CoreFeishuInput({store:{directDmIsolation:f.gate,load:()=>({sources:[source]})},assistant:{get:()=>{effects++;},start:()=>{effects++;}},domain,client:{run:()=>{effects++;}},reader:{}});
 try{assert.equal((await input.receive({workspaceId:'synthetic',sourceId:source.id,identity:f.identity,parentId:'',senderId:f.event.sender_id})).status,'test_quarantined');assert.equal((await input.receipt({workspaceId:'synthetic',sourceId:source.id})).status,'test_quarantined');await input.resumeBudgetQueue('synthetic');assert.equal(effects,0);}finally{f.close();}
});
