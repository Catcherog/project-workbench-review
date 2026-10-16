import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdirSync,writeFileSync} from 'node:fs';
import {DirectDmIsolation} from '../candidate/scripts/direct-dm-isolation.mjs';
import {PersonalMessageReader} from '../candidate/scripts/personal-message-reader.mjs';
import {fixture} from './fixture.mjs';

const evidence=[];
const late=(f,id,more={})=>({...f.event,message_id:id,create_time:f.manifest.expiresAt+86400000,parent_id:'',root_id:'',content:'arbitrary words without any test marker',...more});
test('DM-B01 persistent boundary holds arbitrary future input without using words or expiry',()=>{
 const f=fixture();try{f.sentPreview();f.gate.stop(f.manifest.id);for(const text of ['普通业务进展','拒绝','unrelated ordinary text',''])assert.equal(f.gate.hold({identity:f.identity,message:late(f,'om_words_'+text.length,{content:text}),channel:'late'}),true);
  assert.equal(f.gate.hold({identity:f.identity,message:late(f,'om_other_chat',{chat_id:'oc_ordinary_personal_chat'}),channel:'normal'}),false);
  assert.equal(f.gate.hold({identity:f.identity,message:late(f,'om_old_history',{create_time:f.manifest.issuedAt-1000}),channel:'history'}),false);
  assert.equal(f.gate.hold({identity:f.identity,message:late(f,'om_time_missing',{create_time:undefined}),channel:'incomplete'}),true);
  evidence.push({case:'passive-boundary',arbitraryLateInputHeld:true,sameChatNormalInputAlsoHeld:true,otherChatsUnaffected:true,oldHistoryUnaffected:true});
 }finally{f.close();}
});
test('DM-B02 final root/parent variants work without a preceding hold or passive-chat match',()=>{
 const f=fixture();try{f.sentPreview();for(const field of ['rootId','root_id','parentId','parent_id']){
  const m=late(f,'om_final_'+field,{chat_id:'oc_unreserved',content:'no request marker'});
  const p={scope:f.identity.scope,accountId:f.identity.userId,messageId:m.message_id,chatId:m.chat_id,senderId:m.sender_id,rawCreateTime:String(m.create_time),[field]:'om_fixture_preview'};
  assert.equal(f.gate.sourceHeld({id:'source-'+field,excerpt:m.content,personalMessage:p}),true);
 }
 const p={scope:f.identity.scope,accountId:f.identity.userId,chatId:'oc_unreserved',raw:{message_id:'om_raw_case_root',chat_id:'oc_unreserved',root_id:'om_fixture_preview',create_time:f.manifest.expiresAt+1000}};
 assert.equal(f.gate.sourceHeld({id:'case-source',excerpt:'no marker',caseChat:p}),true);
 }finally{f.close();}
});
test('DM-B02 quarantined reference chains propagate beyond outbound effects',()=>{
 const f=fixture();try{f.sentPreview();let parent='om_fixture_preview';for(let i=0;i<4;i++){
  const m=late(f,'om_chain_'+i,{chat_id:'oc_unreserved',content:'no marker',[i%2?'root_id':'parent_id']:parent});
  assert.equal(f.gate.hold({identity:f.identity,message:m,channel:'chain'}),true);parent=m.message_id;
 }assert.equal(f.gate.classify(f.identity,late(f,'om_chain_last',{chat_id:'oc_unreserved',root_id:parent}))?.reason,'quarantined_reference_chain');
 }finally{f.close();}
});
test('DM-B02 reader preserves authoritative parent/root fields even if shortcut omits them',async()=>{
 const f=fixture();try{const m=late(f,'om_mapping'),original={...m,create_time:String(m.create_time),parent_id:'om_parent',root_id:'om_root',sender:{id:m.sender_id}};
  const shortcut={message_id:m.message_id,chat_id:m.chat_id,content:m.content,create_time:'display only',sender:{id:m.sender_id}};
  const reader=new PersonalMessageReader({client:{run:async args=>args[0]==='api'?{items:[original]}:{messages:[shortcut],has_more:false}}});
  const result=await reader.read({start:new Date(f.manifest.issuedAt).toISOString(),end:new Date(f.manifest.expiresAt+90000000).toISOString(),identity:f.identity});
  assert.equal(result.messages[0].root_id,'om_root');assert.equal(result.messages[0].parent_id,'om_parent');assert.equal(result.messages[0].chat_type,'p2p');
 }finally{f.close();}
});
test('DM-B02 readback failure cannot produce a partially trusted source batch',async()=>{
 const f=fixture();try{const m=late(f,'om_failed_readback');const reader=new PersonalMessageReader({client:{run:async args=>args[0]==='api'?{items:[]}:{messages:[{...m,sender:{id:m.sender_id}}],has_more:false}}});
  await assert.rejects(reader.read({start:new Date(f.manifest.issuedAt).toISOString(),end:new Date(f.manifest.expiresAt+90000000).toISOString(),identity:f.identity,isolation:f.gate}),/消息原始时间/);
 }finally{f.close();}
});
test('inconsistent trusted identity fields never authorize a human confirmation',async()=>{
 const f=fixture();try{f.sentPreview();let reads=0;await assert.rejects(f.gate.confirm(f.manifest.id,f.event,{identity:{...f.identity,appId:'another-app'},verify:async()=>{reads++;return f.event;},current:()=>f.policy}),/IDENTITY/);assert.equal(reads,0);assert.throws(()=>f.gate.reserveEffect(f.manifest.id,'summary',f.policy));}finally{f.close();}
});
test('DM-B03 uncertain owner inspection keeps the live intent and denies another send',()=>{
 const f=fixture();try{f.gate.reserveEffect(f.manifest.id,'preview',f.policy);const observer=new DirectDmIsolation(f.file,{clock:()=>f.manifest.issuedAt,inspectPid:()=> 'unknown'});try{assert.equal(observer.status(f.manifest.id).state,'PREVIEW_PENDING');assert.equal(observer.status(f.manifest.id).recovery.length,0);assert.throws(()=>observer.reserveEffect(f.manifest.id,'preview',f.policy));}finally{observer.close();}}finally{f.close();}
});
test('DM-B03 actual owner death recovers unknown once, preserving the intent and denying late mutation',async()=>{
 const f=fixture();let child,observer;try{
  child=spawn(process.execPath,[new URL('./fixtures/intent-owner.mjs',import.meta.url).pathname,f.file],{stdio:['pipe','pipe','pipe']});
  const exited=once(child,'exit');let output='',errors='';child.stderr.on('data',x=>errors+=x);
  const ready=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('OWNER_FIXTURE_TIMEOUT:'+errors)),5000);child.stdout.on('data',x=>{output+=x;if(output.includes('\n')){clearTimeout(timer);resolve(JSON.parse(output.trim()));}});child.on('error',e=>{clearTimeout(timer);reject(e);});});
  child.stdin.end(JSON.stringify({id:f.manifest.id,policy:f.policy,now:f.manifest.issuedAt+1}));const receipt=await ready;assert.notEqual(receipt.pid,process.pid);
  observer=new DirectDmIsolation(f.file,{clock:()=>f.manifest.issuedAt+2});assert.equal(observer.status(f.manifest.id).state,'PREVIEW_PENDING');
  const before=observer.db.prepare('SELECT payload FROM effects WHERE request_id=?').get(f.manifest.id).payload;
  child.kill('SIGKILL');await exited;assert.throws(()=>process.kill(receipt.pid,0),{code:'ESRCH'});
  observer.recoverInterrupted();const status=observer.status(f.manifest.id);assert.equal(status.state,'DELIVERY_UNKNOWN');assert.equal(status.recovery.length,1);assert.equal(status.recovery[0].payload.ownerObservation,'dead');
  assert.equal(observer.db.prepare('SELECT payload FROM effects WHERE request_id=?').get(f.manifest.id).payload,before);
  assert.throws(()=>observer.reserveEffect(f.manifest.id,'preview',f.policy));assert.throws(()=>observer.recordEffect(f.manifest.id,'preview',{messageId:'om_late',chatId:f.manifest.participantChatId}));observer.recoverInterrupted();assert.equal(observer.status(f.manifest.id).recovery.length,1);
  assert.equal(observer.hold({identity:f.identity,message:late(f,'om_after_owner_death'),channel:'late'}),true);
  evidence.push({case:'actual-owner-death',differentProcess:true,exitConfirmed:true,status:status.state,unknownAuditEntries:1,payloadPreserved:true,repeatSendDenied:true,lateReceiptRequiresSeparateReconciliation:true});
 }finally{if(child&&child.exitCode===null&&child.signalCode===null){child.kill('SIGKILL');await once(child,'exit');}observer?.close();f.close();}
});
test.after(()=>{mkdirSync('../evidence/after',{recursive:true});writeFileSync('../evidence/after/fix1-boundaries.json',JSON.stringify({evidence,realMessages:0,realModels:0},null,2));});
