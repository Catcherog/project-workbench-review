import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import * as d from '../dist-local/domain.mjs';
import {fixtureState,operation} from './s1p1-fixtures.mjs';

const folder=mkdtempSync(path.join(tmpdir(),'uat1-contracts-'));
try{
 await build({entryPoints:['app/integration/receipt-scope.ts'],bundle:true,platform:'node',format:'esm',outfile:path.join(folder,'scope.mjs')});
 const {receiptInScope}=await import(pathToFileURL(path.join(folder,'scope.mjs')));
 const {s,ids}=fixtureState('scope-a'), op=operation(s,ids.action,'已收到合成样件');
 const saved=d.applyWorkItemOperation(s,op,'2026-10-15T01:00:00Z'), receipt=d.entryReceipts(saved,ids.action)[0];
 const checks=[];
 function check(name,fn){fn();checks.push(name);console.log('PASS',name);}
 check('durable workspace/item/operation binding',()=>{assert.equal(receipt.workspaceId,'scope-a');assert.equal(receiptInScope(saved,receipt).operationId,op.requestId);});
 check('same IDs and even the same operation key in another workspace never validate an old identity',()=>{const other=structuredClone(saved);other.workspaceId='scope-b';assert.equal(receiptInScope(other,receipt),null);});
 check('unbound cache, missing receipt, wrong item and wrong operation fail closed',()=>{
  const missing=structuredClone(saved);delete missing.receipts['work-item:'+op.requestId];
  for(const [state,value] of [[saved,{...receipt,workspaceId:undefined}],[missing,receipt],[saved,{...receipt,sourceId:ids.risk}],[saved,{...receipt,operationId:'absent'}]])assert.equal(receiptInScope(state,value),null);
 });
 check('archived item cannot be acted upon through an old receipt',()=>{const state=structuredClone(saved);state.sources.find(x=>x.id===ids.action).archived=true;assert.equal(receiptInScope(state,receipt),null);});
 check('current durable undo wins over cached saved and duplicate labels',()=>{const undone=d.applyWorkItemOperation(saved,{workspaceId:saved.workspaceId,sourceId:ids.action,requestId:'undo-contract',action:'p1-undo',operationId:op.requestId},'2026-10-15T01:01:00Z');assert.ok(receiptInScope(undone,receipt).undoneAt);assert.ok(receiptInScope(undone,{...receipt,duplicate:true}).undoneAt);});
 check('duplicate image label preserves the original durable identity without replacing its state',()=>{assert.equal(receiptInScope(saved,{...receipt,duplicate:true,progress:'stale cache'}).progress,receipt.progress);assert.equal(receiptInScope(saved,{...receipt,duplicate:true}).duplicate,true);});
 check('closed and newer-arrangement semantics remain durable',()=>{const state=structuredClone(saved);Object.assign(state.receipts['work-item:'+op.requestId].result,{closed:true,pendingChanges:[{id:'check',message:'较新安排未覆盖'}]});const live=receiptInScope(state,receipt);assert.equal(live.closed,true);assert.equal(live.pendingChanges.length,1);});
 check('entry history rejects unrelated or malformed operation keys',()=>{const state=structuredClone(saved);state.receipts['other:'+op.requestId]={result:receipt};state.receipts['work-item:wrong']={result:receipt};assert.equal(d.entryReceipts(state,ids.action).length,1);});
 console.log(JSON.stringify({passed:checks.length,checks}));
}finally{rmSync(folder,{recursive:true,force:true});}
