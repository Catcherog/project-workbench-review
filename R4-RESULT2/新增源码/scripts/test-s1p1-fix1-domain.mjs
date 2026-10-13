import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import * as d from '../dist-local/domain.mjs';
import {fixtureState,operation,anchor,output,planFor} from './s1p1-fixtures.mjs';

const results=[],get=(s,id)=>s.sources.find(r=>r.id===id);
const submit=(s,id,text='',manual={},options={})=>{const op=operation(s,id,text,manual);Object.assign(op,options);return {s:d.applyWorkItemOperation(s,op,anchor),op};};
const undo=(s,id,op)=>d.applyWorkItemOperation(s,{workspaceId:s.workspaceId,sourceId:id,action:'p1-undo',requestId:'undo-'+op.requestId,operationId:op.requestId},anchor);
function check(id,name,fn){try{const evidence=fn();results.push({id,name,passed:true,evidence});console.log('PASS',id,name);}catch(error){results.push({id,name,passed:false,error:error.stack});throw error;}}
try{
check('F01-restore','旧检查首次写入后撤销，摘要/状态/nextCheckAt恢复，保留后增进展',()=>{
 let {s,ids}=fixtureState();const id=ids.action,source=get(s,id);source.workItem.handling={state:'waiting',nextCheckAt:'2026-10-14T08:00:00+08:00'};
 const before=d.workItemState(s,source),first=submit(s,id,'',{check:{state:'scheduled',date:'2026-10-15'}});
 s=submit(first.s,id,'已收到初稿').s;s=undo(s,id,first.op);const after=d.workItemState(s,get(s,id));
 assert.deepEqual(after.timing,before.timing);assert.equal(after.nextCheckAt,before.nextCheckAt);assert.equal(d.timeLabel(after.timing.check),d.timeLabel(before.timing.check));
 assert.equal(Object.hasOwn(get(s,id).workItem.p1,'check'),false);assert.deepEqual(get(s,id).workItem.p1.progress.map(p=>p.text),['已收到初稿']);
 return {summary:d.timeLabel(after.timing.check),status:after.timing.status,nextCheckAt:after.nextCheckAt,progress:get(s,id).workItem.p1.progress};
});
check('F01-presence','恢复缺省/空对象/null/空数组原存在状态，不覆盖后来字段',()=>{
 for(const initial of [undefined,{},null,{progress:[]},{check:{}},{check:null}]){
  const {s,ids}=fixtureState(),source=get(s,ids.action);if(initial!==undefined)source.workItem.p1=structuredClone(initial);
  const before=structuredClone(source.workItem),first=submit(s,ids.action,'已收到初稿',{check:{state:'scheduled',date:'2026-10-15'}}),after=undo(first.s,ids.action,first.op);
  assert.equal(Object.hasOwn(get(after,ids.action).workItem,'p1'),Object.hasOwn(before,'p1'));assert.deepEqual(get(after,ids.action).workItem.p1,before.p1);
 }
 const {s,ids}=fixtureState(),first=submit(s,ids.action,'',{check:{state:'scheduled',date:'2026-10-15'}});get(first.s,ids.action).workItem.p1.check.laterNote='后来注记';
 const after=undo(first.s,ids.action,first.op);assert.deepEqual(get(after,ids.action).workItem.p1.check,{laterNote:'后来注记'});
 return {initialContainers:6,laterFieldRetained:true};
});
check('F01-empty-clear','已有空时间对象回退旧安排，明确clear/pending不回退',()=>{
 const {s,ids}=fixtureState(),r=get(s,ids.action);r.workItem.handling={nextCheckAt:'2026-10-14T08:00:00+08:00'};const before=d.workItemState(s,r);
 for(const node of [{},{state:'unchanged'},{laterNote:'历史残留'}]){r.workItem.p1={check:node,completion:{}};const after=d.workItemState(s,r);assert.deepEqual(after.timing,before.timing);assert.equal(after.nextCheckAt,before.nextCheckAt);}
 for(const state of ['clear','pending']){r.workItem.p1.check={state};assert.equal(d.workItemState(s,r).nextCheckAt,'');assert.equal(d.itemTiming(s,r).check.state,state);}
 return {emptyFallback:true,explicitClearAndPendingPreserved:true};
});
check('F01-atomic','后续同字段变动阻止整次撤销且不修改进展',()=>{
 const {s,ids}=fixtureState(),first=submit(s,ids.action,'已联系负责人',{check:{state:'scheduled',date:'2026-10-15'}}),later=submit(first.s,ids.action,'',{check:{state:'scheduled',date:'2026-10-16'}}).s;
 const before=JSON.stringify(later);assert.throws(()=>undo(later,ids.action,first.op),/后续修改/);assert.equal(JSON.stringify(later),before);return {atomic:true};
});
check('F02-binding','选择绑定显示候选，手选/文字/模型候选变化使旧选择失效',()=>{
 const text='周三检查',plan=planFor(text),input={text,occurredAt:anchor,manual:{check:{state:'scheduled',date:'2026-10-15'}}};
 const first=d.combineEntry(plan,input),resolution={check:{choice:'manual',fingerprint:first.conflicts[0].fingerprint}};
 assert.equal(d.combineEntry(plan,{...input,resolution}).changes.check.date,'2026-10-15');
 for(const [p,i] of [[plan,{...input,manual:{check:{state:'scheduled',date:'2026-10-16'}}}],[plan,{...input,text:'补充：周三检查'}],[{...plan,check:{...plan.check,date:'2026-10-21'}},input]]){assert.equal(d.combineEntry(p,{...i,resolution}).conflicts[0].field,'check');}
 assert.equal(d.combineEntry(plan,{...input,resolution:{check:'manual'}}).conflicts.length,1);
 const newer={...input,manual:{check:{state:'scheduled',date:'2026-10-16'}}},candidate=d.combineEntry(plan,newer).conflicts[0];
 const saved=d.combineEntry(plan,{...newer,resolution:{check:{choice:'manual',fingerprint:candidate.fingerprint}}});assert.equal(saved.changes.check.date,candidate.manual.date);
 return {initial:'2026-10-15',newCandidate:candidate.manual.date,saved:saved.changes.check.date,oldBareChoiceRejected:true};
});
check('F03-identity','创建→修改→再次修改→撤销第二次修改，同一进展与独立操作',()=>{
 let {s,ids}=fixtureState();const first=submit(s,ids.action,'已联系负责人'),r1=first.s.receipts['work-item:'+first.op.requestId].result;
 const edit=(state,receipt,text)=>{const op=operation(state,ids.action,text);op.input.editProgressId=d.receiptProgressId(receipt);return {s:d.applyWorkItemOperation(state,op,anchor),op};};
 const second=edit(first.s,r1,'已收到初稿'),r2=second.s.receipts['work-item:'+second.op.requestId].result,legacy={...r2};delete legacy.progressId;
 assert.equal(d.receiptProgressId(legacy),r1.progressId);const third=edit(second.s,legacy,'补充进展：完成复核'),r3=third.s.receipts['work-item:'+third.op.requestId].result;
 assert.equal(r1.progressId,r2.progressId);assert.equal(r2.progressId,r3.progressId);assert.notEqual(r2.operationId,r3.operationId);
 const after=undo(third.s,ids.action,third.op);assert.equal(get(after,ids.action).workItem.p1.progress.length,1);assert.equal(get(after,ids.action).workItem.p1.progress[0].text,'已收到初稿');
 return {progressId:r3.progressId,operationIds:[r1.operationId,r2.operationId,r3.operationId],restored:'已收到初稿'};
});
check('F04-version','纯时间提交仍受版本校验，核对新版本可保存',()=>{
 const {s,ids}=fixtureState(),old=operation(s,ids.action,'',{check:{state:'scheduled',date:'2026-10-16'}}),later=submit(s,ids.action,'已收到初稿').s;
 assert.throws(()=>d.applyWorkItemOperation(later,old,anchor),/事项已变化/);const checked=operation(later,ids.action,'',old.input.manual),after=d.applyWorkItemOperation(later,checked,anchor);
 assert.equal(get(after,ids.action).workItem.p1.check.date,'2026-10-16');return {oldVersion:old.expectedVersion,checkedVersion:checked.expectedVersion,saved:'2026-10-16'};
});
check('F05-states','资料无后续/新增等待/有效安排/两项待定保留分类及正确回执',()=>{
 let {s,ids}=fixtureState();const id=ids.reference,statuses=[d.itemTiming(s,get(s,id)).status],waiting=submit(s,id,'等待模拟工程师提供报告');s=waiting.s;statuses.push(s.receipts['work-item:'+waiting.op.requestId].result.timing.status);
 s=submit(s,id,'',{check:{state:'scheduled',date:'2026-10-16'}}).s;statuses.push(d.itemTiming(s,get(s,id)).status);
 s=submit(s,id,'',{check:{state:'pending'},completion:{state:'pending'}}).s;statuses.push(d.itemTiming(s,get(s,id)).status);
 assert.deepEqual(statuses,['无需时间安排','时间待确认','已安排','明确待定']);assert.equal(get(s,id).workItem.nature,'reference');return {statuses,nature:'reference'};
});
check('F05-active','资料当前待核实/待决策/明确继续与历史已结束相区分',()=>{
 for(const patch of [{pendingChange:{nature:'decision'}},{pendingChange:{nature:'risk'}},{p1:{lifecycle:{state:'open'}}}]){const {s,ids}=fixtureState(),r=get(s,ids.reference);Object.assign(r.workItem,patch);assert.equal(d.itemTiming(s,r).status,'时间待确认');}
 const {s,ids}=fixtureState(),r=get(s,ids.reference);r.workItem.p1={waiting:{who:'历史来源',result:'历史结果'},lifecycle:{state:'closed'}};r.workItem.handling={state:'handled'};assert.equal(d.itemTiming(s,r).status,'无需时间安排');return {activeCases:3,closedHistoricalWaiting:false};
});
check('F06-boundaries','按检查/完成、日期/时刻、时区比较边界，并保持日期精度',()=>{
 const matrix=[
  ['check','2026-10-13','','Asia/Shanghai','2026-10-13T09:59:59+08:00',true],
  ['check','2026-10-13','','Asia/Shanghai','2026-10-13T10:00:00+08:00',false],
  ['completion','2026-10-13','','Asia/Shanghai','2026-10-13T15:00:00+08:00',true],
  ['completion','2026-10-13','','Asia/Shanghai','2026-10-13T23:59:59+08:00',true],
  ['completion','2026-10-13','','Asia/Shanghai','2026-10-14T00:00:00+08:00',false],
  ['check','2026-10-13','','-04:00','2026-10-13T20:00:00+08:00',true],
  ['check','2026-10-13','','-04:00','2026-10-13T14:00:00Z',false],
  ['completion','2026-10-13','','-04:00','2026-10-14T03:59:59Z',true],
  ['completion','2026-10-13','','-04:00','2026-10-14T04:00:00Z',false],
  ['completion','2026-10-13','','UTC','2026-10-13T23:59:59Z',true],
  ['completion','2026-10-14','','+14:00','2026-10-14T09:59:59Z',true],
  ...['check','completion'].flatMap(key=>[
   [key,'2026-10-13','16:00','Asia/Shanghai','2026-10-13T15:00:00+08:00',true],
   [key,'2026-10-13','16:00','Asia/Shanghai','2026-10-13T16:00:00+08:00',false],
   [key,'2026-10-13','10:00','-04:00','2026-10-13T13:59:59Z',true],
   [key,'2026-10-13','10:00','-04:00','2026-10-13T14:00:00Z',false]])
 ];
 const text='停止跟进',plan=planFor(text),evidence=[];
 for(const [key,date,time,zone,now,expected] of matrix){
  const choice={state:'scheduled',date,time,zone},input={text,occurredAt:now,manual:{[key]:choice}},result=d.combineEntry(plan,input);
  assert.equal(result.conflicts.some(c=>c.field==='followup'),expected,JSON.stringify(input));
  const {s,ids}=fixtureState(),next=submit(s,ids.action,'',{[key]:choice}).s,t=d.itemTiming(next,get(next,ids.action),now),node=t[key];
  assert.equal(node.precision,time?'minute':'date');if(!time&&key==='completion')assert.equal(node.effectiveAt,undefined);
  if(key==='completion')assert.equal(t.completionDue.some(c=>c.label.includes('时间已过')),!expected);
  else assert.equal(Date.parse(node.effectiveAt)>Date.parse(now),expected);
  evidence.push({key,date,time,zone,now,conflict:expected,summary:d.timeLabel(node),due:t.completionDue.map(c=>c.label)});
 }
 return evidence;
});
check('F06-choice-history','结束选择也绑定安排；未触碰的历史时间不作为新安排',()=>{
 const text='停止跟进',p=planFor(text),input={text,occurredAt:anchor,manual:{check:{state:'scheduled',date:'2026-10-16'}}},c=d.combineEntry(p,input).conflicts[0],resolution={followup:{choice:'end',fingerprint:c.fingerprint}};
 assert.equal(d.combineEntry(p,{...input,resolution}).changes.check,undefined);
 assert.equal(d.combineEntry(p,{...input,resolution,manual:{check:{state:'scheduled',date:'2026-10-17'}}}).conflicts[0].field,'followup');
 const {s,ids}=fixtureState(),first=submit(s,ids.action,'',input.manual),old=structuredClone(get(first.s,ids.action).workItem.p1.check),after=submit(first.s,ids.action,text).s;
 assert.deepEqual(get(after,ids.action).workItem.p1.check,old);assert.equal(d.workItemState(after,get(after,ids.action)).closed,true);return {changedCandidateRejected:true,untouchedHistoricalTimeRetained:true};
});
}finally{writeFileSync(output+'/fix1-domain-results.json',JSON.stringify({scope:'FIX1 domain operations; synthetic inputs, no model or external writes',results},null,2));}
