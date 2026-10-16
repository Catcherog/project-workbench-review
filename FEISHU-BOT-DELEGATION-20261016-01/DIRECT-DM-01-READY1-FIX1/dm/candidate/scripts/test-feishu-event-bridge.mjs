import assert from 'node:assert/strict';
import {mkdirSync,mkdtempSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {LocalStore} from './local-store.mjs';
import {AgentMonitor} from './agent-monitor.mjs';
import {FeishuEventBridge} from './feishu-event-bridge.mjs';
import * as domain from '../dist-local/domain.mjs';
const output=path.resolve('work/event-bridge-tests');mkdirSync(output,{recursive:true});const store=new LocalStore(mkdtempSync(path.join(output,'data-')),{testMode:true});await store.initialize(null);
const s=domain.emptyState('event-test','事件接入隔离验证','demo');store.insert(s);const monitor=new AgentMonitor({store,domain,testMode:true});monitor.configure(s.workspaceId,{revision:0,enabled:true,personal:false,intervalSeconds:60});
const identity={scope:'test/app',userId:'ou_me'},stamp=String(Date.now()+100),raw={message_id:'om_push',chat_id:'oc_allowed',create_time:stamp,update_time:stamp,msg_type:'text',sender:{id:'ou_engineer'},body:{content:'{"text":"实际原文：客户要求核实交付影响。"}'}};let calls=0;
const client={identity:async()=>identity,run:async args=>{calls++;return args[0]==='api'?{items:[raw]}:{messages:[{message_id:'om_push',chat_id:'oc_allowed',content:'实际原文：客户要求核实交付影响。',chat_name:'模拟已关注群'}]};}};
const bridge=new FeishuEventBridge({store,domain,monitor,client,testMode:true});bridge.configure(s.workspaceId,{revision:0,enabled:true});const event={message_id:'om_push',chat_id:'oc_allowed',chat_type:'group',sender_id:'ou_engineer',mentions:[{id:'ou_me'}],content:'推送内容不直接采用'};const results=[];
async function test(name,fn){await fn();results.push({name,passed:true});console.log('PASS',name);}
try{
 await test('only an in-scope group event is read back through the current user',async()=>{await bridge.ingest(s.workspaceId,'im.message.receive_v1',event);const source=store.load(s.workspaceId).sources[0];assert.match(source.excerpt,/实际原文/);assert.equal(source.personalMessage.accountId,'ou_me');assert.equal(bridge.status(s.workspaceId).received,1);});
 await test('duplicate event delivery does not create another source',async()=>{await bridge.ingest(s.workspaceId,'im.message.receive_v1',{...event,event_id:'different-delivery'});assert.equal(store.load(s.workspaceId).sources.length,1);assert.equal(bridge.status(s.workspaceId).received,1);});
 await test('unrelated bot group and bot private messages do not expand personal scope',async()=>{const count=calls;await bridge.ingest(s.workspaceId,'im.message.receive_v1',{...event,chat_id:'oc_other',mentions:[]});await bridge.ingest(s.workspaceId,'im.message.receive_v1',{...event,chat_type:'p2p'});assert.equal(calls,count);});
 await test('generated user notes enter as unread document links for the research loop',async()=>{await bridge.ingest(s.workspaceId,'vc.note.generated_v1',{note_token:'FixtureNoteToken',timestamp:String(Date.now()+200),event_id:'note-event'});const sources=store.load(s.workspaceId).sources;assert.equal(sources.length,2);assert.ok(sources.some(s=>s.riskEvent&&s.excerpt.includes('/docx/')));assert.equal(monitor.feed(s.workspaceId).events.length,2);});
 await test('paused subscriptions ignore late incoming events',async()=>{bridge.configure(s.workspaceId,{revision:1,enabled:false});const before=store.load(s.workspaceId);await bridge.ingest(s.workspaceId,'vc.note.generated_v1',{note_token:'AnotherNoteToken',timestamp:String(Date.now()+300)});assert.deepEqual(store.load(s.workspaceId),before);});
}finally{await bridge.close();await monitor.close();writeFileSync(path.join(output,'checks.json'),JSON.stringify({passed:results.length,results,mode:'isolated-push-simulation'},null,2));store.close();}
