import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs/promises';import os from 'node:os';import {join} from 'node:path';import {fileURLToPath} from 'node:url';
import {createDualRoleProbe,loadRole,selectRole,validateRoleBinding,validateRoleResult} from '../src/dual-role.mjs';
const fixture=fileURLToPath(new URL('./fixtures/fake-role-codex.mjs',import.meta.url));
test('one broker selects both roles for the same synthetic user and binds local receipts (OFFLINE)',async t=>{
 const root=await fs.mkdtemp(join(os.tmpdir(),'fix3-roles-')),probe=createDualRoleProbe({root,offlineFixture:fixture});
 try{
  const a={requestId:'synthetic-request-A',senderId:'synthetic-A',chatId:'synthetic-chat-A',taskType:'test-summary'};
  const b={requestId:'synthetic-request-B',senderId:'synthetic-A',chatId:'synthetic-chat-B',taskType:'action-extract'};
  for(const request of [a,b]){assert.equal((await probe.submit(request)).status,'queued');const record=probe.executions.at(-1),role=await loadRole(request.taskType);validateRoleBinding(record,{...record,requestId:request.requestId,agentId:request.taskType,configurationSha256:role.configurationSha256,instructionsSha256:role.instructionsSha256});const receipt=probe.receipts.find(x=>x.target.messageId===request.requestId);assert.equal(receipt.target.senderId,request.senderId);assert.equal(receipt.chatId,request.chatId);assert.equal(receipt.text.includes(record.envelope.result.summary),true);assert.equal(record.envelope.evidence.executionKind,'offline-fixture');assert.equal(record.historyPassedToRunner,false);assert.equal(record.prompt.includes(record.input.source_marker),false);}
  const [x,y]=probe.executions;assert.notEqual(x.configurationSha256,y.configurationSha256);assert.notEqual(x.instructionsSha256,y.instructionsSha256);assert.notEqual(x.jobDir,y.jobDir);assert.notEqual(x.input.source_marker,y.input.source_marker);assert.equal(x.result.pass_rate_percent,70);assert.equal(y.result.tasks[0].deadline,null);
  assert.equal((await probe.submit(a)).status,'duplicate');assert.equal(probe.executions.length,2);
  assert.equal((await probe.submit({...a,requestId:'bad',taskType:'unknown'})).status,'unknown_or_invalid_task');assert.equal((await probe.submit({...a,configurationPath:'/not-accepted'})).status,'unknown_or_invalid_task');assert.equal(probe.executions.length,2);
  assert.equal((await probe.close()).confirmed,true);
  const evidence={kind:'OFFLINE_ONLY',realModelCalls:0,entry:'createDualRoleProbe.submit -> ProbeBroker.accept -> process -> executeTracked -> runCodex(offline-fixture) -> validation -> local reply/readback',selections:probe.executions.map(r=>({requestId:r.requestId,agentId:r.agentId,configurationSha256:r.configurationSha256,instructionsSha256:r.instructionsSha256,runId:r.runId,executionKind:r.envelope.evidence.executionKind,sourceMarker:r.input.source_marker,historyPassedToRunner:r.historyPassedToRunner,result:r.result,terminationConfirmed:r.envelope.evidence.terminationConfirmed})),receipts:probe.receipts.filter(r=>r.target.messageId.startsWith('synthetic-request'))};t.diagnostic(JSON.stringify(evidence));
 }finally{await probe.close();await fs.rm(root,{recursive:true,force:true});}
});
test('role bindings and foreign input cannot pass result projection',async()=>{
 const record={requestId:'r',agentId:'test-summary',configurationSha256:'c',instructionsSha256:'i',runId:'run',launchFingerprint:'l'};
 for(const field of Object.keys(record))assert.throws(()=>validateRoleBinding({...record,[field]:'mismatch'},record),/BINDING_MISMATCH/);
 assert.equal(selectRole('test-summary').agentId,'test-summary');assert.equal(selectRole('action-extract').agentId,'action-extract');assert.equal(selectRole('sender:synthetic-A'),null);
 const role=await loadRole('test-summary');assert.throws(()=>validateRoleResult({summary:JSON.stringify({source_marker:'other-role',source:'synthetic.json:tests',total:10,passed:7,failed:2,blocked:1,pass_rate_percent:70}),missing:[],question:''},role,{source_marker:'this-role',tests:[]}),/ROLE_RESULT_CONTRACT/);
});
test('real path stays closed and starts no process when minimum isolation is blocked',async()=>{
 const root=await fs.mkdtemp(join(os.tmpdir(),'fix3-blocked-')),probe=createDualRoleProbe({root});
 try{await probe.submit({requestId:'blocked-request',senderId:'synthetic-A',chatId:'synthetic-chat',taskType:'test-summary'});assert.equal(probe.executions.length,0);assert.equal(probe.broker.db.prepare('SELECT status FROM messages WHERE id=?').get('blocked-request').status,'model_failed');assert.equal(Object.values(probe.broker.terminations.state.runs).flatMap(r=>Object.values(r.processes)).some(p=>p.spawned),false);assert.equal((await probe.close()).confirmed,true);}finally{await probe.close();await fs.rm(root,{recursive:true,force:true});}
});
