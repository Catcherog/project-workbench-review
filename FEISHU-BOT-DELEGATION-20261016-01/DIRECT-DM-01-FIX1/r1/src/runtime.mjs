import fs from 'node:fs';import {dirname,resolve} from 'node:path';import {randomUUID} from 'node:crypto';
import {processRun} from '../vendor/fix3/src/process.mjs';import {ExecutionState,executionStateClear,reconcileExecution} from '../vendor/fix3/src/execution-state.mjs';import {withinExecution} from '../vendor/fix3/src/execution-context.mjs';import {acquireOwner} from '../vendor/fix3/src/owner.mjs';import {digest} from './codec.mjs';
export class AdapterRuntime{
 constructor(file){fs.mkdirSync(dirname(file),{recursive:true,mode:0o700});this.file=file;this.owner=acquireOwner(file,{requiresClearance:true});try{this.ledger=new ExecutionState(file);}catch(e){if(executionStateClear(file))this.owner.release();throw e;}this.abort=new AbortController();this.queue=Promise.resolve();this.active=new Set();this.records=[];this.stopped=false;}
 call(role,frame,{timeoutMs=5000,inspectGroup}={}){
  if(this.stopped)return Promise.reject(Error('RUNTIME_STOPPED'));
  const task=this.queue.then(async()=>{
   if(this.stopped)throw Error('RUNTIME_STOPPED');if(!this.ledger.summary().processTerminationConfirmed)throw Error('TERMINATION_RECONCILIATION_REQUIRED');const id=this.ledger.begin(frame.rpcId,'managed');
   return withinExecution(event=>this.ledger.record(id,event),async()=>{
    let receipt,error;const responses=[];
    try{receipt=await processRun(process.execPath,[resolve(new URL('./adapter.mjs',import.meta.url).pathname)],{input:JSON.stringify({...frame,role})+'\n',timeoutMs,signal:this.abort.signal,maxBytes:1024*1024,onRecord:r=>responses.push(r),...(inspectGroup?{inspectGroup,terminateGraceMs:10,terminateBoundMs:80}:{})});
     this.records.push({executionId:id,rpcId:frame.rpcId,role,requestType:frame.operation,inputSha256:digest({...frame,role}),outputSha256:digest(receipt.stdout),pid:receipt.pid,pgid:receipt.pgid,exit:receipt.exit,stopReason:receipt.stopReason,terminationConfirmed:receipt.terminationConfirmed,lifecyclePersisted:receipt.lifecyclePersisted,residualPids:receipt.residualPids});
     if(receipt.exit!==0||receipt.stopReason)throw Error('ADAPTER_IO_UNKNOWN');if(responses.length!==1||responses[0].rpcId!==frame.rpcId)throw Error('INVALID_RPC_RESPONSE');
    }catch(e){error=e;}this.ledger.settle(id,error);
    if(!this.ledger.safe(id))throw Error('PROCESS_EXIT_UNCONFIRMED');if(error)throw error;return responses[0];
   });
  });this.queue=task.catch(()=>{});this.active.add(task);task.then(()=>this.active.delete(task),()=>this.active.delete(task));return task;
 }
 close({release=true}={}){if(this.closing)return this.closing;this.stopped=true;this.abort.abort();this.closing=(async()=>{let timer,settled=false;await Promise.race([Promise.allSettled([...this.active,this.queue]).then(()=>settled=true),new Promise(r=>timer=setTimeout(r,4000))]);clearTimeout(timer);const summary=this.ledger.seal();this.ledger.close();const result={settled,...summary,confirmed:settled&&this.active.size===0&&summary.processTerminationConfirmed};if(result.confirmed&&release)this.owner.release();this.stopReceipt=result;return result;})();return this.closing;}
 reconcile(id){if(!this.stopped||this.active.size)throw Error('RECONCILIATION_NOT_READY');const r=reconcileExecution(this.file,id);if(r.safetyCleared)this.owner.release();return r;}
}
export const rpcId=()=>randomUUID();
