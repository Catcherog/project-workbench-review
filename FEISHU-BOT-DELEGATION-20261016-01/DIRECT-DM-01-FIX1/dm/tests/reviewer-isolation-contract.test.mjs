// Reviewer-authored synthetic contracts. Original candidate and original fixture are unchanged.
import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture} from './fixture.mjs';
import {DirectDmIsolation} from '../candidate/scripts/direct-dm-isolation.mjs';

function late(f,id,extra={}) {
 return {...f.event,message_id:id,create_time:f.manifest.expiresAt+1000,
   parent_id:'',root_id:'',content:'稍晚回复：拒绝本轮合成测试',...extra};
}
function source(f,m){return {id:'source_'+m.message_id,excerpt:m.content,
 personalMessage:{scope:f.identity.scope,accountId:f.identity.userId,
 messageId:m.message_id,chatId:m.chat_id,senderId:m.sender_id,
 rawCreateTime:String(m.create_time),parentId:m.parent_id,rootId:m.root_id}};}

test('CONTROL: late direct reply to preview is quarantined',()=>{
 const f=fixture();try{f.sentPreview();f.gate.stop(f.manifest.id);
 assert.equal(f.gate.hold({identity:f.identity,message:late(f,'om_review_direct',{parent_id:'om_fixture_preview'}),channel:'review'}),true);
 }finally{f.close();}
});
test('B01: late unthreaded test response must not fall through to business',()=>{
 const f=fixture();try{f.sentPreview();f.gate.stop(f.manifest.id);
 assert.equal(f.gate.hold({identity:f.identity,message:late(f,'om_review_unthreaded'),channel:'review'}),true);
 }finally{f.close();}
});
test('CONTROL: raw root-only late reply is recognized',()=>{
 const f=fixture();try{f.sentPreview();
 assert.equal(f.gate.classify(f.identity,late(f,'om_review_rawroot',{root_id:'om_fixture_preview'}))?.requestId,f.manifest.id);
 }finally{f.close();}
});
test('B02a: final source barrier must preserve a known root-only reference',()=>{
 const f=fixture();try{f.sentPreview();
 const m=late(f,'om_review_sourceroot',{root_id:'om_fixture_preview'});
 // Do not call hold(raw) first: doing so would mask metadata loss via known_message lookup.
 assert.equal(f.gate.sourceHeld(source(f,m)),true);
 }finally{f.close();}
});
test('CONTROL: source barrier recognizes direct parent',()=>{
 const f=fixture();try{f.sentPreview();
 const m=late(f,'om_review_sourceparent',{parent_id:'om_fixture_preview'});
 assert.equal(f.gate.sourceHeld(source(f,m)),true);
 }finally{f.close();}
});
test('B02b: reply to a quarantined reply remains in the quarantine chain',()=>{
 const f=fixture();try{f.sentPreview();
 assert.equal(f.gate.hold({identity:f.identity,message:late(f,'om_review_first',{parent_id:'om_fixture_preview'}),channel:'review'}),true);
 const follow=late(f,'om_review_follow',{parent_id:'om_review_first'});
 assert.equal(f.gate.hold({identity:f.identity,message:follow,channel:'review'}),true);
 }finally{f.close();}
});
test('CONTROL: original request marker remains quarantined after stop',()=>{
 const f=fixture();try{f.sentPreview();f.gate.stop(f.manifest.id);
 assert.equal(f.gate.hold({identity:f.identity,message:late(f,'om_review_marker',{content:`拒绝 ${f.manifest.id}`}),channel:'review'}),true);
 }finally{f.close();}
});
test('DM-B03a: interrupted pre-send intent should be reported unknown after reopen',()=>{
 const f=fixture();f.gate.reserveEffect(f.manifest.id,'preview',f.policy);f.close();
 // Simulates persisted SENDING followed by process exit before receipt recording.
 const gate=new DirectDmIsolation(f.file,{clock:()=>f.manifest.issuedAt});
 try{assert.equal(gate.status(f.manifest.id).state,'DELIVERY_UNKNOWN');}finally{gate.close();}
});
test('CONTROL: unresolved pre-send intent is not blindly retried after reopen',()=>{
 const f=fixture();f.gate.reserveEffect(f.manifest.id,'preview',f.policy);f.close();
 const gate=new DirectDmIsolation(f.file,{clock:()=>f.manifest.issuedAt});
 try{assert.throws(()=>gate.reserveEffect(f.manifest.id,'preview',f.policy));}finally{gate.close();}
});
