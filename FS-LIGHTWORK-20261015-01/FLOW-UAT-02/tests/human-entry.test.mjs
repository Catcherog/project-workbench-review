import test from 'node:test';
import assert from 'node:assert/strict';
import {aggregate,F} from '../src/aggregate.mjs';
import {projectReal} from '../src/real-projection.mjs';
const ts=s=>({timestamp:Date.parse(s),iso_time:s});
function row(id='A',hours='8',registration){return [
 {key:'group_uuid',value:id},{key:F.person,value:{key:'private-user',name:'Private name'}},
 {key:F.period,value:{start_time:ts('2026-09-14T00:00:00+08:00'),end_time:ts('2026-09-20T23:59:59+08:00')}},
 {key:F.hours,value:hours},...(registration===undefined?[]:[{key:F.registration,value:registration}])];}
function snap(rows=[row()],item='private-item'){return {readAt:'2026-10-16T08:00:00Z',complete:true,response:{pagination:{has_more:false},work_item_attribute:{work_item_id:item,work_item_name:'Private source',owned_project:{key:'private-space'},work_item_type:{key:'test-type'}},work_item_fields:[{key:F.parent,value:rows},{key:'updated_at',value:ts('2026-10-16T07:00:00Z')}]}};}
const agg=(s,extra={})=>aggregate(s,{registrationPolicy:'source_locator',...extra});
test('strict baseline still requires a registration ID',()=>{assert.equal(aggregate([snap()]).cells.length,0);assert.ok(aggregate([snap()]).errors.length);});
test('human registration can omit the technical ID without source mutation',()=>{const s=snap(),before=JSON.stringify(s),out=agg([s]);assert.equal(out.cells[0].hours,'8');assert.equal(out.cells[0].rows[0].registrationDerived,true);assert.equal(JSON.stringify(s),before);});
test('different repeat multiplicity remains one 8-hour human row',()=>{const a=snap(),b=snap([row(),row()]);assert.equal(agg([a,b]).cells[0].hours,'8');assert.equal(agg([b,a]).cells[0].hours,'8');});
test('distinct native rows must not collapse just because values match',()=>{assert.equal(agg([snap([row('A'),row('B')])]).cells[0].hours,'16');});
test('missing native row ID remains invalid',()=>{const s=snap();s.response.work_item_fields[0].value[0].shift();assert.equal(agg([s]).cells.length,0);assert.ok(agg([s]).errors.length);});
test('explicit duplicate registration across sources still needs review',()=>{const out=agg([snap([row('A','8','same-id')],'one'),snap([row('B','8','same-id')],'two')]);assert.equal(out.crossSourceCandidates.length,1);assert.equal(out.crossSourceCandidates[0].registration,'same-id');});
test('empty real scope is null and never inherits sample hours',()=>{const outputs=['week','month'].map(mode=>agg([snap([])],{mode}));const r=projectReal(outputs,{allowedPersonIds:['private-user'],aliases:{},runId:'real-1',readAt:'2026-10-16T08:00:00Z',totalItems:16,unregisteredItems:16,failedItems:0});assert.equal(r.length,1);assert.equal(r[0]['数据集'],'real');assert.equal(r[0]['实际小时'],null);assert.equal(r[0]['人员'],null);assert.equal(r[0]['周期'],null);assert.equal(r[0]['待登记事项数'],16);assert.equal(r[0]['刷新结果'],'success_no_records');});
test('real numeric zero is preserved separately from missing records and identity stays private',()=>{const outputs=['week','month'].map(mode=>agg([snap([row('A','0')])],{mode}));const r=projectReal(outputs,{allowedPersonIds:['private-user'],aliases:{'private-user':{id:'person-01',name:'体验登记人01'}},runId:'real-1',readAt:'2026-10-16T08:00:00Z',totalItems:16,unregisteredItems:15,failedItems:0});assert.equal(r[0]['实际小时'],0);assert.equal(r[0]['数据集'],'real');assert.doesNotMatch(JSON.stringify(r),/private-|Private name|Private source/);});

test('a stable alias does not authorize another person for display',()=>{const outputs=['week','month'].map(mode=>agg([snap()],{mode}));assert.throws(()=>projectReal(outputs,{allowedPersonIds:['another-user'],aliases:{'private-user':{id:'person-01',name:'体验登记人01'}}}),/person_outside_display_scope/);});
