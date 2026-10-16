import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import os from 'node:os';
import {join} from 'node:path';
import {ProbeBroker} from '../src/broker.mjs';
import {executionStateClear,executionStatePath} from '../src/execution-state.mjs';

test('all clearance paths reject parent confirmed with unsafe or unproved child records',async()=>{
 const cases=[{status:'pending'},{status:'running'},{status:'unknown'},{status:'confirmed'},
  {status:'confirmed',terminalConfirmed:true,residualPids:null},{status:'no_process',spawned:true,terminalConfirmed:true}];
 for(const child of cases){
  const root=await fs.mkdtemp(join(os.tmpdir(),'fix3-clearance-')),file=join(root,'broker.sqlite');
  const execute=async()=>{};execute.processLifecycle='required';
  const config={file,appId:'synthetic-app',tenantId:'synthetic-tenant',participants:[],deadline:Date.now()+60000,execute,verify:async()=>null,reply:async()=>null,readReply:async()=>null};
  const broker=new ProbeBroker(config),id=broker.terminations.begin('synthetic-request','managed');
  try{
   const run=broker.terminations.state.runs[id];Object.assign(run,{status:'confirmed',settledAt:new Date().toISOString(),processes:{synthetic:{processKey:'synthetic',spawned:true,pid:424242,pgid:424242,identity:'synthetic-only-no-signals',commandFingerprint:'synthetic',...child}}});broker.terminations.save();
   assert.equal(broker.terminations.safe(id),false);assert.equal(broker.terminations.summary().processTerminationConfirmed,false);assert.equal(executionStateClear(file),false);
   assert.throws(()=>broker.ownership.release(),/TERMINATION_NOT_CONFIRMED/);
   // Copy only synthetic ledger state, deliberately omit owner: restart must still deny.
   const copied=join(root,'copy.sqlite');await fs.copyFile(executionStatePath(file),executionStatePath(copied));
   assert.throws(()=>new ProbeBroker({...config,file:copied}),/TERMINATION_RECONCILIATION_REQUIRED/);
   const receipt=await broker.close();assert.equal(receipt.confirmed,false);assert.equal(existsSync(file+'.owner'),true);
   assert.equal(Object.keys(broker.terminations.state.runs[id].processes).length,1);
  }finally{await broker.close();await fs.rm(root,{recursive:true,force:true});}
 }
});
