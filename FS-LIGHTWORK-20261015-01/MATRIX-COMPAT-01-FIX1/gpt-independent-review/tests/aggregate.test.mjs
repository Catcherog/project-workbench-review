import test from 'node:test';
import assert from 'node:assert/strict';
import { aggregate, normalize, periodAt, sumHours, F } from '../src/aggregate.mjs';
const at=s=>Date.parse(s+'+08:00');
const person={namespace:'feishu-project-user-key',id:'9000000000000000001',name:'合成人员甲'};
function row({who=person.id,name=person.name,hours='8',start='2026-09-14T00:00:00',end='2026-09-20T23:59:59.999',rid='row-A',reg=rid}={}){
 return [{key:F.person,value:{key:who,name}},{key:F.hours,value:hours},{key:F.period,value:{start_time:{timestamp:at(start)},end_time:{timestamp:at(end)}}},{key:F.registration,value:reg},{key:'group_uuid',value:rid}];
}
function snap(rows=[row()],{version='2026-10-15T09:00:00+08:00',readAt='2026-10-16T09:00:00+08:00',item='synthetic-item-A',complete=true,total='8',ownership='非项目'}={}){
 return {readAt,complete,response:{pagination:{has_more:!complete},work_item_attribute:{owned_project:{key:'synthetic-space'},work_item_type:{key:'synthetic-type'},work_item_id:item,update_time:version,work_item_name:'合成测试事项'},work_item_fields:[{key:F.parent,value:rows},{key:F.total,value:total},{key:F.ownership,value:{label:ownership,value:'synthetic-option'}}]}};
}
const cell=(r,who=person.id,key='2026-09-14')=>r.cells.find(c=>c.person.id===who&&c.period.key===key);
test('C04 same-row person, period and hours remain associated',()=>{
 const r=aggregate([snap([row(),row({who:'9000000000000000002',hours:'3',rid:'B'}),row({hours:'2',rid:'C',start:'2026-09-21T00:00:00',end:'2026-09-27T23:59:59.999'})])]);
 assert.equal(cell(r).hours,'8');assert.equal(cell(r,'9000000000000000002').hours,'3');assert.equal(cell(r,person.id,'2026-09-21').hours,'2');
});
test('C05 identical query and duplicate rows do not multiply totals',()=>{
 const s=snap([row(),row()]);const r=aggregate([s,structuredClone(s)]);assert.equal(cell(r).hours,'8');assert.equal(cell(r).rows.length,1);
});
test('C05 server update replaces old hours independently of read order',()=>{
 const old=snap(),latest=snap([row({hours:'9'})],{version:'2026-10-15T10:00:00+08:00'});
 for(const ss of [[old,latest],[latest,old]])assert.equal(cell(aggregate(ss)).hours,'9');
});
test('C05 latest complete source snapshot removes deleted rows',()=>{
 const old=snap([row(),row({rid:'B',hours:'2'})]);const latest=snap([row()],{version:'2026-10-15T10:00:00+08:00'});
 assert.equal(cell(aggregate([old,latest])).hours,'8');
});
test('C05 same server version with different data fails closed',()=>{
 const r=aggregate([snap(),snap([row({hours:'9'})])]);assert.equal(r.cells.length,0);assert.equal(r.errors[0].code,'same_version_conflict');
});
test('C05 read time cannot resolve conflicting unversioned data',()=>{
 const r=aggregate([snap([],{version:null}),snap([row()],{version:null,readAt:'2026-10-16T10:00:00+08:00'})]);
 assert.equal(r.cells.length,0);assert.equal(r.errors[0].code,'unversioned_conflict');
});
test('C05 distinct legitimate rows of equal hours remain additive',()=>{
 assert.equal(cell(aggregate([snap([row(),row({rid:'B'})])])).hours,'16');
});
test('C05 ambiguous registration reused at different source locators is pending',()=>{
 const r=aggregate([snap(),snap([row()],{item:'synthetic-item-B'})]);assert.equal(cell(r).hours,null);assert.equal(r.pending.length,2);assert.equal(r.crossSourceCandidates.length,1);
});
test('C06 Beijing Sunday and Monday are separate weeks',()=>{
 assert.equal(periodAt(at('2026-09-20T23:59:59.999'),'week').key,'2026-09-14');assert.equal(periodAt(at('2026-09-21T00:00:00'),'week').key,'2026-09-21');
});
test('C06 interval ending exactly on Monday includes that instant and is pending',()=>{
 const r=aggregate([snap([row({end:'2026-09-21T00:00:00'})])]);assert.equal(r.pending[0].reason,'cross_week_unallocated');assert.ok(r.cells.every(c=>c.hours===null));
});
test('C06 cross-week record is not distributed, repeated or assigned to its start',()=>{
 const r=aggregate([snap([row({end:'2026-09-22T23:59:59.999',hours:'20'})])]);assert.equal(r.pending.length,1);assert.equal(r.cells.length,2);assert.ok(r.cells.every(c=>c.hours===null&&c.valueState==='pending'));
});
test('C06 cross-month week counts once weekly but awaits allocation monthly',()=>{
 const s=snap([row({start:'2026-09-28T00:00:00',end:'2026-10-04T23:59:59.999'})]);
 const w=aggregate([s]),m=aggregate([s],{mode:'month'});assert.equal(w.cells[0].hours,'8');assert.equal(w.cells.length,1);assert.equal(m.pending[0].reason,'cross_month_unallocated');assert.ok(m.cells.every(c=>c.hours===null));
});
test('C06 September row remains September in both modes',()=>{
 assert.equal(aggregate([snap()],{mode:'month'}).cells[0].period.key,'2026-09');assert.equal(aggregate([snap()]).cells[0].period.label,'2026-09-14—2026-09-20');
});
test('C06 decimal hours are exact and never multiplied by eight',()=>{
 const r=aggregate([snap([row({hours:'0.1'}),row({rid:'B',hours:'0.2'})])]);assert.equal(cell(r).hours,'0.3');assert.equal(sumHours(['0008.000']),'8');
});
test('C07 no rows differs from an explicit zero',()=>{
 const options={people:[person],periods:[at('2026-09-14T00:00:00')]};
 const absent=cell(aggregate([snap([])],options)),zero=cell(aggregate([snap([row({hours:'0'})])],options));
 assert.equal(absent.hours,null);assert.equal(absent.valueState,'no_records');assert.equal(zero.hours,'0');assert.equal(zero.valueState,'explicit_zero');assert.ok(!JSON.stringify(zero).includes('已确认未安排'));
});
test('C07 null numeric field is invalid, never zero',()=>{
 const r=aggregate([snap([row({hours:null})])]);assert.equal(r.cells.length,0);assert.equal(r.errors[0].code,'invalid_decimal_hours');
});
test('C07 coverage gaps retain known subtotal with explicit reason',()=>{
 for(const status of ['no_records','permission_denied','request_failed','pagination_incomplete','mapping_unverified']){
  const r=aggregate([snap()],{coverage:[{source:'project-source',status}]});assert.equal(cell(r).hours,'8');assert.equal(cell(r).coverageGaps[0].status,status);assert.match(cell(r).caption,/不代表/);
 }
});
test('C07 partial source pagination is visible even with usable rows',()=>{
 const r=aggregate([snap([row()],{complete:false})]);assert.equal(cell(r).hours,'8');assert.equal(cell(r).coverageGaps[0].status,'pagination_incomplete');
});
test('C07 absent parent field is missing coverage, not a zero',()=>{
 const s=snap();s.response.work_item_fields=s.response.work_item_fields.filter(f=>f.key!==F.parent);const r=aggregate([s]);assert.equal(r.cells.length,0);assert.match(r.errors[0].code,/missing_field/);
});
test('same display names cannot merge distinct stable personnel IDs',()=>{
 const r=aggregate([snap([row(),row({who:'9000000000000000002',name:person.name,hours:'3',rid:'B'})])]);assert.equal(r.cells.length,2);assert.equal(cell(r).hours,'8');
});
test('unsafe numeric personnel identifiers are rejected',()=>{
 const r=aggregate([snap([row({who:9000000000000000001})])]);assert.equal(r.errors[0].code,'invalid_person_id');assert.equal(r.cells.length,0);
});
test('source total and expected schedule are excluded from actual aggregation',()=>{
 const s=snap([row()],{total:'888'});s.response.work_item_current_node=[{estimated_score:1000}];s.response.work_item_fields.push({key:'field_bb4c2c',value:'1000'});
 assert.equal(cell(aggregate([s])).hours,'8');assert.equal(normalize(s).reconciliationOnly,'888');
});
test('non-project source preserves ownership without inventing a formal project',()=>{
 const c=cell(aggregate([snap()]));assert.equal(c.nonProjectItemCount,1);assert.equal(c.projectCount,null);assert.equal(c.rows[0].ownership.projectRef,null);
});
test('duplicate fields and missing identity cannot silently corrupt association',()=>{
 const rr=row();rr.push({key:F.hours,value:'99'});const r=aggregate([snap([rr])]);assert.equal(r.cells.length,0);assert.match(r.errors[0].code,/duplicate_field/);
});
test('source timestamp is authoritative but contradictory ISO date is rejected',()=>{
 const rr=row();rr.find(f=>f.key===F.period).value.start_time.iso_time='2026-09-21T00:00:00+08:00';const r=aggregate([snap([rr])]);assert.equal(r.errors[0].code,'timestamp_iso_mismatch');
});
test('aggregation has no source mutation or claimed component binding',()=>{
 const s=snap(),before=JSON.stringify(s);const r=aggregate([s]);assert.equal(JSON.stringify(s),before);assert.equal(r.componentBinding,'unverified');
});
