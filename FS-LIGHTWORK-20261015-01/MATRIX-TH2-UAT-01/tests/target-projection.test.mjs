import test from 'node:test';
import assert from 'node:assert/strict';
import { projectRows, planWrites } from '../src/target-projection.mjs';
const scope={sourcePersonId:'private-person',sourceItemId:'private-item',sourceType:'private-type',sourceProjectKey:'private-space',sourceRegistrationId:'private-registration',aliasId:'test-t02',aliasName:'T02测试人员'};
function outputs(hours='8'){
  const row={source:{workItemId:scope.sourceItemId,type:scope.sourceType,space:scope.sourceProjectKey,rowId:'private-row'},person:{id:scope.sourcePersonId},registrationId:scope.sourceRegistrationId,ownership:{projectRef:null,label:'非项目'},note:'合成测试',version:1,readAt:'2026-10-16T06:00:00Z',startInclusive:1789315200000,endInclusive:1789919999999,endExclusive:1789920000000,hours};
  return ['week','month'].map(mode=>({mode,unit:'hour',timeZone:'Asia/Shanghai',rowsRead:1,errors:[],pending:[],coverageGaps:[{source:'project-source',status:'no_records',total:0}],cells:[{person:row.person,kind:'actual',hours,rows:[structuredClone(row)],nonProjectItemCount:1,period:{key:mode==='week'?'2026-09-14':'2026-09',label:mode==='week'?'2026-09-14—2026-09-20':'2026-09',startInclusive:1789315200000,endExclusive:1789920000000}}]}));
}
const project=o=>projectRows(o,scope,'run-1','2026-10-16T06:01:00Z');
test('projection hides source identities and keeps weekly/monthly actual values separate',()=>{
  const r=project(outputs());assert.equal(r.length,2);assert.deepEqual(r.map(x=>x['实际小时']),[8,8]);assert.equal(r[0]['非项目事项数'],1);assert.doesNotMatch(JSON.stringify(r),/private-/);assert.match(r[0]['覆盖缺口'],/no_records/);assert.match(r[0]['范围说明'],/不代表全部/);
});
test('second run updates the same two records instead of creating duplicates',()=>{
  const rows=project(outputs());const first=planWrites(rows,[]);assert.ok(first.every(x=>!x.recordId));
  const existing=rows.map((x,i)=>({...x,record_id:'rec'+i}));
  const second=planWrites(rows,existing,['rec0','rec1']);assert.deepEqual(second.map(x=>x.recordId),['rec0','rec1']);
});
test('duplicate, unowned or unrelated target records stop writes',()=>{
  const rows=project(outputs()),r={...rows[0],record_id:'rec0'};
  assert.throws(()=>planWrites(rows,[r,r],['rec0']),/duplicate_target/);
  assert.throws(()=>planWrites(rows,[r],[]),/not_owned/);
  assert.throws(()=>planWrites(rows,[{record_id:'other','汇总键':'unrelated'}],['other']),/unexpected_target/);
});
test('wrong person and unverified source ownership are rejected before projection',()=>{
  const o=outputs();o[0].cells[0].person={id:'another-person'};assert.throws(()=>project(o),/unexpected_source/);
  const p=outputs();p[0].cells[0].rows[0].ownership.projectRef='guessed-project';assert.throws(()=>project(p),/scope_mismatch/);
});
test('missing or pending results cannot replace known values with zero',()=>{
  const o=outputs();o[0].cells=[];assert.throws(()=>project(o),/source_not_ready/);
  const p=outputs();p[0].pending=[{reason:'cross_week_unallocated'}];assert.throws(()=>project(p),/source_not_ready/);
  assert.equal(project(outputs('0'))[0]['实际小时'],0);
});
test('week and month from differing source versions cannot be mixed',()=>{
  const o=outputs();o[1].cells[0].rows[0].version=2;assert.throws(()=>project(o),/source_mismatch/);
});
