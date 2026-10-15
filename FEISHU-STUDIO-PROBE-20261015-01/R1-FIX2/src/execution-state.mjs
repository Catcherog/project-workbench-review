import fs from 'node:fs';
import {dirname} from 'node:path';
import {randomUUID} from 'node:crypto';
import {processIdentity,liveGroupMembers,executionHostFingerprint} from './process.mjs';
const safe=new Set(['no_process','confirmed','confirmed_legacy','reconciled_exited']);
export const executionStatePath=file=>file+'.executions.json';
export function readExecutionState(file){
 const state=JSON.parse(fs.readFileSync(executionStatePath(file),'utf8'));
 if(state.version!==1||!state.runs||Array.isArray(state.runs))throw Error('INVALID_EXECUTION_LEDGER');
 return state;
}
export function executionStateClear(file){
 try{const s=readExecutionState(file);return s.hostFingerprint===executionHostFingerprint()&&!s.persistenceFault&&!fs.existsSync(executionStatePath(file)+'.fault')&&Object.values(s.runs).every(r=>safe.has(r.status));}catch{return false;}
}
function atomicSave(path,state){
 fs.mkdirSync(dirname(path),{recursive:true,mode:0o700});const tmp=path+'.'+randomUUID()+'.tmp';let fd;
 try{fd=fs.openSync(tmp,'wx',0o600);fs.writeFileSync(fd,JSON.stringify(state,null,2));fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(tmp,path);}finally{if(fd!==undefined)fs.closeSync(fd);if(fs.existsSync(tmp))fs.unlinkSync(tmp);}
}

export class ExecutionState{
 constructor(file){
  this.file=file;this.path=executionStatePath(file);this.closed=false;
  this.state=fs.existsSync(this.path)?readExecutionState(file):{version:1,hostFingerprint:executionHostFingerprint(),persistenceFault:false,runs:{}};
  if(fs.existsSync(this.path)&&!executionStateClear(file))throw Error('TERMINATION_RECONCILIATION_REQUIRED');
  this.persist=atomicSave;atomicSave(this.path,this.state);
 }
 save(){try{this.persist(this.path,this.state);return true;}catch(e){this.state.persistenceFault=true;this.state.faultReason=e.code||e.message;try{fs.writeFileSync(this.path+'.fault','termination persistence requires reconciliation',{mode:0o600});}catch{}return false;}}
 fault(reason){this.state.persistenceFault=true;this.state.faultReason=reason;this.save();}
 safe(id){return !!this.state.runs[id]&&safe.has(this.state.runs[id].status)&&!this.state.persistenceFault;}
 begin(messageId,mode){
  const id=randomUUID();this.state.runs[id]={id,messageId,mode,status:'pending',sealed:false,runnerIds:[],processes:{},createdAt:new Date().toISOString()};
  if(!this.save())throw Error('TERMINATION_LEDGER_UNWRITABLE');return id;
 }
 record(id,event){
  const r=this.state.runs[id];if(!r)return false;
  // A late intent may not spawn. Late terminal callbacks never rewrite a sealed decision.
  if(this.closed||r.sealed)return !['intent','started'].includes(event.type);
  if(event.runId&&!r.runnerIds.includes(event.runId))r.runnerIds.push(event.runId);
  if(event.type==='runner')return this.save();
  const key=event.processKey;if(!key)return false;
  const p=r.processes[key]||{processKey:key};
  if(event.type==='intent')Object.assign(p,{status:'pending',commandFingerprint:event.commandFingerprint});
  else if(event.type==='not_started')Object.assign(p,{status:'no_process',spawned:false,reason:event.reason});
  else if(event.type==='started')Object.assign(p,{status:'running',spawned:true,pid:event.pid,pgid:event.pgid,identity:event.identity});
  else if(event.type==='finished'){
   const binding=!event.spawned||(Number.isSafeInteger(p.pid)&&p.pid===event.pid&&p.pgid===event.pgid&&typeof p.identity==='string'&&p.identity.length>0&&p.identity===event.identity);
   const confirmed=event.terminationConfirmed===true&&binding&&Array.isArray(event.residualPids)&&event.residualPids.length===0;
   Object.assign(p,{status:confirmed?(event.spawned?'confirmed':'no_process'):'unknown',spawned:event.spawned,exit:event.exit,stopReason:event.stopReason,residualPids:event.residualPids});
   if(binding)Object.assign(p,{pid:event.pid,pgid:event.pgid,identity:event.identity});
   else p.bindingMismatch=true; // never replace the started process identity with a mismatched receipt
   if(!confirmed)r.unknownSticky=true;
  }else return false;
  r.processes[key]=p;
  if(r.unknownSticky)r.status='unknown';
  return this.save();
 }
 settle(id,error){
  const r=this.state.runs[id];if(!r||this.closed||r.sealed)return;
  const ps=Object.values(r.processes),hint=error?.evidence;
  if(hint?.terminationConfirmed===false){r.unknownSticky=true;r.failureHint='executor_reported_unknown';}
  if(r.unknownSticky||this.state.persistenceFault)r.status='unknown';
  else if(ps.length)r.status=ps.every(p=>safe.has(p.status))?(ps.some(p=>p.spawned)?'confirmed':'no_process'):'unknown';
  else if(r.mode==='logical-only')r.status='no_process';
  // Backward compatibility for the reviewer's explicitly safe, controller-owned fake executor.
  // A bare result field cannot enter here, and this cannot override any process-manager record.
  else if(r.mode==='opaque'&&hint?.terminationConfirmed===true&&Array.isArray(hint.residualPids)&&!hint.residualPids.length)r.status='confirmed_legacy';
  else r.status='unknown';
  r.settledAt=new Date().toISOString();if(r.status==='unknown')r.unknownSticky=true;this.save();
 }
 seal(){for(const r of Object.values(this.state.runs)){if(!safe.has(r.status)){r.status='unknown';r.unknownSticky=true;}r.sealed=true;}this.save();return this.summary();}
 summary(){const unknown=Object.values(this.state.runs).filter(r=>!safe.has(r.status)).map(r=>({executionId:r.id,messageId:r.messageId,status:r.status,runnerIds:r.runnerIds,processes:Object.values(r.processes)}));return {processTerminationConfirmed:!unknown.length&&!this.state.persistenceFault,unknownExecutions:unknown,persistenceFault:!!this.state.persistenceFault};}
 close(){this.closed=true;}
}

/** Explicit post-close reconciliation only. No PID killing or automatic lease recovery. */
export function reconcileExecution(file,id,{identity=processIdentity,members=liveGroupMembers}={}){
 const state=readExecutionState(file),r=state.runs[id];if(state.hostFingerprint!==executionHostFingerprint())throw Error('EXECUTION_HOST_MISMATCH');if(!r?.sealed)throw Error('RECONCILIATION_REQUIRES_SEALED_EXECUTION');
 const ps=Object.values(r.processes);if(!ps.length)throw Error('PROCESS_BINDING_MISSING');
 const checks=[];
 for(const p of ps){
  if(p.status==='no_process'){checks.push({processKey:p.processKey,noProcess:true});continue;}
  if(p.bindingMismatch)throw Error('PROCESS_BINDING_MISMATCH');
  if(!Number.isSafeInteger(p.pid)||p.pid<=0||p.pgid!==p.pid||!p.identity||!p.commandFingerprint)throw Error('PROCESS_BINDING_MISSING');
  const current=identity(p.pid);if(current!==null)throw Error(current===p.identity?'PROCESS_STILL_ACTIVE':'PID_REUSED_OR_MISMATCH');
  const live=members(p.pgid);if(!Array.isArray(live)||live.length)throw Error('PROCESS_GROUP_UNCONFIRMED');
  checks.push({processKey:p.processKey,pid:p.pid,pgid:p.pgid,identity:p.identity,absent:true});
 }
 r.status='reconciled_exited';r.reconciliation={at:new Date().toISOString(),checks};
 // A failed durable write is not repaired by assuming an empty or incomplete ledger is safe.
 if(Object.values(state.runs).every(x=>safe.has(x.status))){state.persistenceFault=false;delete state.faultReason;}
 atomicSave(executionStatePath(file),state);
 if(!state.persistenceFault&&fs.existsSync(executionStatePath(file)+'.fault'))fs.unlinkSync(executionStatePath(file)+'.fault');
 return {executionId:id,reconciled:true,safetyCleared:executionStateClear(file),checks};
}
