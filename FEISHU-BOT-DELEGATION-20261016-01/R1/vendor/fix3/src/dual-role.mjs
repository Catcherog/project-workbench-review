// Synthetic transport only. Real launch remains blocked by composed sandbox preflight.
import fs from 'node:fs/promises';
import {resolve,join,relative,isAbsolute} from 'node:path';
import {randomUUID} from 'node:crypto';
import {ProbeBroker} from './broker.mjs';
import {runCodex,validateCompletion,hash} from './codex.mjs';
import {recordExecution} from './execution-context.mjs';
const kinds=new Set(['test-summary','action-extract']);
export const selectRole=text=>kinds.has(text)?{agentId:text}:null;
export async function loadRole(id){
 if(!kinds.has(id))throw Error('UNKNOWN_TASK_TYPE');
 const config=JSON.parse(await fs.readFile(new URL('../roles/'+id+'.json',import.meta.url),'utf8'));
 if(config.agent_id!==id||config.task_type!==id||config.instruction_file!==id+'.md'||config.input_file!=='synthetic.json')throw Error('ROLE_CONFIGURATION_MISMATCH');
 const instructions=await fs.readFile(new URL('../roles/'+config.instruction_file,import.meta.url),'utf8');
 return {config,instructions,configurationSha256:hash(config),instructionsSha256:hash(instructions)};
}
export function validateRoleResult(result,role,input){
 let value;try{value=JSON.parse(result.summary);}catch{throw Error('ROLE_RESULT_NOT_JSON');}
 const keys=Object.keys(value||{}).sort().join(',');
 if(keys!==role.config.result_contract.keys.slice().sort().join(',')||value.source_marker!==input.source_marker||result.missing.length||result.question)throw Error('ROLE_RESULT_CONTRACT');
 if(role.config.agent_id==='test-summary'){
  const n=input.tests.length,passed=input.tests.filter(x=>x.status==='passed').length,failed=input.tests.filter(x=>x.status==='failed').length,blocked=input.tests.filter(x=>x.status==='blocked').length;
  if(value.source!=='synthetic.json:tests'||value.total!==n||value.passed!==passed||value.failed!==failed||value.blocked!==blocked||value.pass_rate_percent!==100*passed/n)throw Error('INVALID_STATISTICS');
 }else{
  const expected=[{task:'补充接口说明',owner:'合成成员甲',deadline:null},{task:'复核测试结果',owner:'合成成员乙',deadline:'2026-10-19'}];
  if(value.source!=='synthetic.json:minutes'||!Array.isArray(value.tasks)||value.tasks.length!==2||value.tasks.some((x,i)=>Object.keys(x).sort().join(',')!=='deadline,owner,task'||Object.entries(expected[i]).some(([k,v])=>x[k]!==v)))throw Error('INVALID_ACTION_ITEMS');
 }
 return value;
}
export function validateRoleBinding(record,expected){
 for(const key of ['requestId','agentId','configurationSha256','instructionsSha256','runId','launchFingerprint'])if(!record[key]||record[key]!==expected[key])throw Error('ROLE_BINDING_MISMATCH:'+key);
}
export function createDualRoleProbe({root,offlineFixture}={}){
 if(!root)throw Error('ROOT_REQUIRED');root=resolve(root);const sourceEvents=new Map(),receipts=[],executions=[],claims=new Set();
 const execute=async input=>{
  let runnerEntered=false;
  try{
   const role=await loadRole(input.task.agentId);
   if(!offlineFixture)throw Error('REAL_LAUNCH_BLOCKED: nested parent/command sandbox unavailable');
   if(claims.has(role.config.agent_id))throw Error('ROLE_ATTEMPT_ALREADY_CONSUMED');
   const job=resolve(input.jobDir),rel=relative(join(root,'jobs'),job);if(!rel||rel.startsWith('..')||isAbsolute(rel))throw Error('JOB_SCOPE_MISMATCH');
   await fs.mkdir(job,{recursive:true,mode:0o700});const realRel=relative(await fs.realpath(join(root,'jobs')),await fs.realpath(job));if(!realRel||realRel.startsWith('..')||isAbsolute(realRel))throw Error('JOB_SYMLINK_ESCAPE');
   const source_marker=randomUUID();
   const synthetic=role.config.agent_id==='test-summary'?{source_marker,tests:Array.from({length:10},(_,i)=>({id:'case-'+i,status:i<7?'passed':i<9?'failed':'blocked'}))}:{source_marker,minutes:['合成成员甲补充接口说明，未约定截止日期','合成成员乙复核测试结果，截止日期 2026-10-19']};
   await fs.writeFile(join(job,'synthetic.json'),JSON.stringify(synthetic),{flag:'wx',mode:0o600});
   const prompt=role.instructions+'\n控制器会话 marker：'+input.marker;
   if(prompt.includes(source_marker))throw Error('SOURCE_MARKER_LEAKED_IN_PROMPT');
   claims.add(role.config.agent_id);runnerEntered=true;
   const envelope=await runCodex({binary:process.execPath,prefixArgs:[resolve(offlineFixture)],jobDir:job,prompt,marker:input.marker,executionKind:'offline-fixture',model:'gpt-6-astra',effort:'low',signal:input.signal});
   validateCompletion(envelope,input.marker);
   if(envelope.evidence.inputSha256!==hash(prompt))throw Error('PROMPT_BINDING_MISMATCH');
   const value=validateRoleResult(envelope.result,role,synthetic);
   const record={requestId:input.requestId,sessionKey:input.sessionKey,agentId:role.config.agent_id,configurationSha256:role.configurationSha256,instructionsSha256:role.instructionsSha256,runId:envelope.evidence.runId,launchFingerprint:envelope.evidence.launchFingerprint,jobDir:job,input:synthetic,prompt,historyPassedToRunner:false,result:value,envelope};
   const currentRole=await loadRole(input.task.agentId);validateRoleBinding(record,{requestId:input.requestId,agentId:input.task.agentId,configurationSha256:currentRole.configurationSha256,instructionsSha256:currentRole.instructionsSha256,runId:envelope.evidence.runId,launchFingerprint:envelope.evidence.launchFingerprint});
   executions.push(record);return {marker:envelope.result.marker,summary:envelope.result.summary};
  }finally{if(!runnerEntered)recordExecution({type:'not_started',processKey:'role-preflight-'+input.requestId,reason:'real_launch_blocked_or_invalid_request'});}
 };execute.processLifecycle='required';
 const broker=new ProbeBroker({file:join(root,'broker.sqlite'),appId:'synthetic-app',tenantId:'synthetic-tenant',participants:[{id:'synthetic-A',alias:'A'},{id:'synthetic-B',alias:'B'}],deadline:Date.now()+600000,maxCalls:2,selectTask:selectRole,execute,
  verify:async id=>sourceEvents.get(id),reply:async(target,text)=>{const r={messageId:'local-receipt-'+receipts.length,chatId:target.chatId,text,target};receipts.push(r);return r;},readReply:async id=>receipts.find(x=>x.messageId===id)});
 const admittedSessions=new Set();
 const submit=async request=>{
  if(Object.keys(request).sort().join(',')!=='chatId,requestId,senderId,taskType'||!kinds.has(request.taskType))return {status:'unknown_or_invalid_task'};
  const event={appId:'synthetic-app',tenantId:'synthetic-tenant',senderId:request.senderId,senderType:'user',chatId:request.chatId,chatType:'p2p',messageId:request.requestId,text:request.taskType,createdAt:Date.now()};
  const session=request.senderId+'|'+request.chatId;
  if(!admittedSessions.has(session)){const start={...event,messageId:'activate-'+request.requestId,text:'联调开始'};sourceEvents.set(start.messageId,start);await broker.accept(start);await broker.queue;admittedSessions.add(session);}
  sourceEvents.set(event.messageId,event);const admission=await broker.accept(event);await broker.queue;return admission;
 };
 return {submit,broker,receipts,executions,close:()=>broker.close()};
}
