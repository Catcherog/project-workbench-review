import test from 'node:test';
import assert from 'node:assert/strict';
import {buildBootstrap, buildContinuity, normalizeAmSnapshot} from '../core/index.mjs';

const at='2026-11-05T08:00:00+08:00';
function snapshot() {return {schemaVersion:1,workspaceId:'test-workspace',viewerId:'owner',revision:1,generatedAt:at,
  coverage:{status:'partial',checkedAt:at,reasons:['测试范围只有已登记事项']},
  projects:[{id:'p',title:'项目甲',kind:'project',status:'active'},
    {id:'outside',title:'部门协同',kind:'outside',status:'unknown'}],
  items:[{id:'pending',projectId:'p',title:'核对交付',version:2,semanticVersion:1,businessState:'waiting',priority:'P1',requiresViewerAction:false,
    dueAt:'2026-11-08',deadlineKind:'commitment',nextCheckAt:'2026-11-06T10:00:00+08:00'},
    {id:'out',projectId:'outside',title:'整理部门意见',version:1,semanticVersion:0,businessState:'open',priority:'P2',requiresViewerAction:true,deadlineKind:'check'},
    {id:'unbound',projectId:null,title:'归属不明',businessState:'open',priority:'P0',requiresViewerAction:true},
    {id:'done',projectId:'outside',title:'有依据的已完成事项',businessState:'closed',priority:'P1'}],
  facts:[],reviews:[],reminders:[{id:'r',itemId:'pending',projectId:'p',title:'原回执待核对',body:'先核对原请求',priority:'P1',kind:'delivery_unknown',displayState:'unread'}],
  sources:[],decisions:[],receipts:[]};}

test('outside topics use registered subject IDs and never collect unknown attribution',()=>{
  const s=snapshot(), result=buildContinuity(s);
  assert.deepEqual(result.outside.map(t=>t.projectId),['outside']);
  assert.deepEqual(result.outside[0].items.map(i=>i.id),['out']);
  assert.equal(result.openCount,2);
  assert.ok(!JSON.stringify(result).includes('unbound'));
});

test('a reopened page carries original waiting identity, date and check point without a new task',()=>{
  const s=snapshot(), before=JSON.stringify(s), first=buildContinuity(s);
  const next=JSON.parse(JSON.stringify(s));next.generatedAt='2026-11-06T09:00:00+08:00';
  const second=buildContinuity(next);
  assert.deepEqual(second.attention,first.attention);
  assert.equal(first.waitingCount,1);assert.equal(first.uncertainDeliveryCount,1);
  assert.equal(second.attention[0].itemId,'pending');
  assert.equal(second.attention[0].nextCheckAt,'2026-11-06T10:00:00+08:00');
  assert.equal(JSON.stringify(s),before);
});

test('read or snoozed presentation does not close the underlying business item',()=>{
  const s=snapshot();s.reminders[0].displayState='snoozed';
  const result=buildContinuity(s);
  assert.equal(result.uncertainDeliveryCount,1);assert.equal(result.waitingCount,1);
  assert.equal(result.openCount,2);assert.equal(s.items[0].businessState,'waiting');
});

test('paused items do not acquire an ordinary manager action and source changes stay visible',()=>{
  const s=snapshot();s.items[1].businessState='paused';
  s.reminders.push({...s.reminders[0],id:'s',kind:'source_changed'});
  const result=buildContinuity(s);
  assert.equal(result.pausedCount,1);assert.equal(result.needsReviewCount,1);
  assert.ok(!result.attention.some(r=>r.itemId==='out'));
});

test('native seconds are converted once, missing project IDs never become an outside bucket',()=>{
  const snapshot=normalizeAmSnapshot({workspaceId:'test-workspace',viewerId:'owner',generatedAt:at,
    projects:[{key:'p',title:'项目甲'}],items:[{id:'x',project_ref:'p',state:'waiting',next_check:1793926800}],
    queries:{},reminders:[]});
  assert.equal(snapshot.items[0].nextCheckAt,new Date(1793926800000).toISOString());
  const result=buildBootstrap(snapshot);
  assert.deepEqual(result.continuity.outside,[]);
  assert.equal(result.continuity.scope,'registered_authorized_items');
});
