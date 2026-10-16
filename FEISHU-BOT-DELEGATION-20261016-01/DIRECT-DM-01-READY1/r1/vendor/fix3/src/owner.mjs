import fs from 'node:fs';
import {dirname} from 'node:path';
import {randomUUID} from 'node:crypto';
import {processIdentity} from './process.mjs';
import {executionStateClear} from './execution-state.mjs';
export function acquireOwner(file,{requiresClearance=false}={}){
  const path=file+'.owner';fs.mkdirSync(dirname(file),{recursive:true,mode:0o700});
  try{fs.mkdirSync(path,{mode:0o700});}catch(e){if(e.code==='EEXIST')throw Error('BROKER_ALREADY_OWNED: inspect owner before recovery');throw e;}
  const owner={id:randomUUID(),pid:process.pid,identity:processIdentity(process.pid),createdAt:new Date().toISOString(),requiresClearance};
  fs.writeFileSync(path+'/owner.json',JSON.stringify(owner),{mode:0o600});
  return {owner,path,release(){const now=JSON.parse(fs.readFileSync(path+'/owner.json'));if(now.id!==owner.id)throw Error('OWNER_CHANGED');if(now.requiresClearance&&!executionStateClear(file))throw Error('TERMINATION_NOT_CONFIRMED');fs.unlinkSync(path+'/owner.json');fs.rmdirSync(path);}};
}
export function inspectOwner(file){
  const path=file+'.owner';let owner;try{owner=JSON.parse(fs.readFileSync(path+'/owner.json'));}catch{return {state:'unknown',recoverable:false};}
  let current;try{current=processIdentity(owner.pid);}catch{return {state:'inspection_unavailable',owner,recoverable:false};}
  const terminationClear=!owner.requiresClearance||executionStateClear(file);
  return {state:current===owner.identity?'active':current===null?'exited':'pid_reused',owner,currentIdentity:current,terminationClear,recoverable:!!owner.identity&&current===null&&terminationClear};
}
export function recoverOwner(file,expectedOwnerId){
  const s=inspectOwner(file);if(!s.recoverable||s.owner.id!==expectedOwnerId)throw Error('OWNER_RECOVERY_DENIED');
  const path=file+'.owner';fs.unlinkSync(path+'/owner.json');fs.rmdirSync(path);return s;
}
