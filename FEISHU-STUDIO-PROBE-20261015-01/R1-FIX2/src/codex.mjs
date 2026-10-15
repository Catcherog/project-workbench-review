import fs from 'node:fs/promises';
import {resolve,join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
import {processRun,cleanEnv} from './process.mjs';
import {buildLaunch,permissionArgs,hash} from './launch.mjs';
import {ExecutionBudget} from './budget.mjs';
import {recordExecution} from './execution-context.mjs';
export {processRun,cleanEnv,permissionArgs,hash,buildLaunch};
const budgetFile=fileURLToPath(new URL('../runtime/model-budget.sqlite',import.meta.url));
export const resultSchema={type:'object',additionalProperties:false,required:['marker','summary','missing','question'],properties:{marker:{type:'string'},summary:{type:'string',maxLength:1800},missing:{type:'array',maxItems:10,items:{type:'string',maxLength:200}},question:{type:'string',maxLength:500}}};
export function validResult(r,marker){return !!r&&Object.keys(r).sort().join(',')==='marker,missing,question,summary'&&r.marker===marker&&typeof r.summary==='string'&&r.summary.length<=1800&&typeof r.question==='string'&&r.question.length<=500&&Array.isArray(r.missing)&&r.missing.length<=10&&r.missing.every(x=>typeof x==='string'&&x.length<=200);}
export function validateCompletion(envelope,marker){
 const {result,evidence}=envelope||{};if(!validResult(result,marker)||!evidence||evidence.exit!==0||evidence.stopReason||!evidence.terminationConfirmed||!evidence.completed||evidence.failed||!evidence.valid||evidence.marker!==marker)throw Error('MODEL_NOT_COMPLETED');
 if(evidence.events.filter(e=>e.type==='turn.completed').length!==1||evidence.events.some(e=>['turn.failed','error'].includes(e.type)))throw Error('INVALID_COMPLETION_EVENT');
 if(hash(result)!==evidence.outputSha256||!evidence.runId||!evidence.launchFingerprint)throw Error('INVALID_COMPLETION_BINDING');
 return envelope;
}
export async function implementationFingerprint(){
 const files=['codex.mjs','process.mjs','launch.mjs','budget.mjs','worker-adapter.mjs','isolation-evidence.mjs','execution-context.mjs','execution-state.mjs','owner.mjs'];const hashes={};
 for(const name of files)try{hashes[name]=hash(await fs.readFile(new URL(name,import.meta.url)));}catch{hashes[name]='absent';}
 return {files:hashes,fingerprint:hash(hashes)};
}
export async function runCodex({binary,prefixArgs=[],jobDir,prompt,marker,model='gpt-6-astra',effort='max',timeoutMs=180000,signal,executionKind='real-model'}){
 const runId=randomUUID();let processAttempted=false;
 try{
 if(signal?.aborted)throw Error('CANCELLED_BEFORE_START');
 if(timeoutMs<1||timeoutMs>180000)throw Error('INVALID_TIMEOUT');
 if(!['real-model','offline-fixture'].includes(executionKind))throw Error('INVALID_EXECUTION_KIND');
 let budget,callId,confirmed=true;
 if(executionKind==='real-model'){
  const snapshot=JSON.parse(await fs.readFile(new URL('../evidence/round-budget.json',import.meta.url),'utf8'));
  budget=new ExecutionBudget(budgetFile,snapshot);try{callId=budget.reserve();}catch(e){budget.close();throw e;}
 }
 let processReceipt;
 try{
  if(signal?.aborted)throw Error('CANCELLED_BEFORE_START');
  await fs.mkdir(jobDir,{recursive:true,mode:0o700});
  // Parent-written evidence/final output sits outside the model-readable job directory.
  const recordDir=resolve(dirname(jobDir),'.receipts',runId);await fs.mkdir(recordDir,{recursive:true,mode:0o700});
  const schemaFile=join(recordDir,'schema.json'),outputFile=join(recordDir,'final.json');
  await fs.writeFile(schemaFile,JSON.stringify(resultSchema),{mode:0o600,flag:'wx'});
  const launch=buildLaunch({binary,prefixArgs,jobDir,outputFile,schemaFile,model,effort,executionKind});
  const executorFingerprint=hash(await fs.readFile(binary));
  const implementation=await implementationFingerprint(),events=[],eventKinds={};
  const onRecord=e=>{
   const kind=e.type+':'+(e.item?.type||'');eventKinds[kind]=(eventKinds[kind]||0)+1;
   if(['thread.started','turn.started','turn.completed','turn.failed','error'].includes(e.type))events.push(e);
   if(['item.started','item.completed','item.failed'].includes(e.type)&&['command_execution','agent_message'].includes(e.item?.type))events.push(e);
  };
  recordExecution({type:'runner',runId});processAttempted=true;
  processReceipt=await processRun(binary,launch.args,{cwd:launch.cwd,env:launch.env,input:prompt,timeoutMs,signal,onRecord,onSpawn:r=>budget?.spawned(callId,r)});
  confirmed=processReceipt.terminationConfirmed&&processReceipt.lifecyclePersisted!==false;
  let result;try{result=JSON.parse(await fs.readFile(outputFile,'utf8'));}catch{}
  const completed=events.filter(e=>e.type==='turn.completed').length===1,failed=events.some(e=>['turn.failed','error'].includes(e.type));
  const last=events.filter(e=>e.type==='item.completed'&&e.item?.type==='agent_message').at(-1);let finalMatches=false;try{finalMatches=hash(JSON.parse(last.item.text))===hash(result);}catch{}
  const evidence={runId,marker,executionKind,implementation,executorFingerprint,launch:launch.descriptor,launchFingerprint:launch.fingerprint,permissionFingerprint:launch.descriptor.permissionFingerprint,pid:processReceipt.pid,pgid:processReceipt.pgid,startedAt:processReceipt.startedAt,endedAt:processReceipt.endedAt,exit:processReceipt.exit,stopReason:processReceipt.stopReason,terminationConfirmed:confirmed,physicalTerminationConfirmed:processReceipt.terminationConfirmed,lifecyclePersisted:processReceipt.lifecyclePersisted,signals:processReceipt.signals,residualPids:processReceipt.residualPids,completed,failed,valid:validResult(result,marker)&&finalMatches,inputSha256:hash(prompt),outputSha256:result?hash(result):null,eventKinds,events,diagnosticSummary:{stderrBytes:Buffer.byteLength(processReceipt.stderr),stderrSha256:hash(processReceipt.stderr),spawnError:processReceipt.spawnError||null}};
  await fs.writeFile(join(recordDir,'execution.json'),JSON.stringify(evidence,null,2),{mode:0o600,flag:'wx'});
  const envelope={result,evidence};
  try{validateCompletion(envelope,marker);}catch(e){throw Object.assign(e,{evidence,recordDir});}
  return envelope;
 }finally{if(budget){budget.finish(callId,confirmed);budget.close();}}
 }finally{if(!processAttempted)recordExecution({type:'not_started',processKey:runId+'-preflight',runId,reason:'runner_did_not_call_process_manager'});}
}
