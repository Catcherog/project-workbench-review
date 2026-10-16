// Independent review: synthetic inputs and fake CLI only. No network or live account use.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, copyFileSync, readdirSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, delimiter } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { aggregate, F } from '../src/aggregate.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const at=s=>Date.parse(s+'+08:00');
function row(rid='rA',hours='8') {
  return [{key:F.person,value:{key:'REVIEW-PERSON',name:'离线合成人员'}},
    {key:F.period,value:{start_time:{timestamp:at('2026-09-14T00:00:00')},end_time:{timestamp:at('2026-09-20T23:59:59.999')}}},
    {key:F.hours,value:hours},{key:F.registration,value:'REVIEW-REG-'+rid},{key:'group_uuid',value:rid}];
}
function snap(rows=[row()]) {
  return {readAt:'2026-10-16T11:00:00+08:00',complete:true,response:{
    pagination:{has_more:false},work_item_attribute:{owned_project:{key:'REVIEW-SPACE'},work_item_type:{key:'REVIEW-TYPE'},work_item_id:'REVIEW-T02',work_item_name:'离线合成事项',update_time:'2026-10-15T09:00:00+08:00'},
    work_item_fields:[{key:F.parent,value:rows},{key:F.ownership,value:{label:'非项目',value:'REVIEW-NONPROJECT'}}]}};
}
function summary(result){return {hours:result.cells.map(c=>c.hours),errors:result.errors.map(e=>e.code)};}
for(const reverse of [false,true]) test(`B01 duplicate multiplicity must not create snapshot version conflict, reverse=${reverse}`,()=>{
  const one=snap([row()]),dup=snap([row(),row()]);
  const result=aggregate(reverse?[dup,one]:[one,dup]);
  assert.deepEqual(summary(result),{hours:['8'],errors:[]});
});
test('CONTROL same logical rows in different order remain 10 hours',()=>{
  assert.deepEqual(summary(aggregate([snap([row(),row('rB','2')]),snap([row('rB','2'),row()])])),{hours:['10'],errors:[]});
});
test('CONTROL genuine same-version hour conflict remains rejected',()=>{
  assert.deepEqual(summary(aggregate([snap([row()]),snap([row('rA','9')])])),{hours:[],errors:['same_version_conflict']});
});
function runReader(scenario){
  const dir=mkdtempSync(join(tmpdir(),'matrix-independent-'));
  for(const d of ['src','input','bin','evidence'])mkdirSync(join(dir,d));
  for(const f of ['aggregate.mjs','read-live.mjs'])copyFileSync(join(root,'src',f),join(dir,'src',f));
  writeFileSync(join(dir,'input','read-scope.json'),JSON.stringify({projectKey:'REVIEW-SPACE',extraItemId:'REVIEW-T02',projectItemId:'REVIEW-PROJECT',projectType:'REVIEW-TYPE'}));
  writeFileSync(join(dir,'fixture.json'),JSON.stringify(snap().response));
  writeFileSync(join(dir,'bin','meegle'),`#!/usr/bin/env node
const {readFileSync,appendFileSync}=require('node:fs');
const [kind,verb]=process.argv.slice(2);
appendFileSync(process.env.REVIEW_CALLS,JSON.stringify({kind,verb})+'\\n');
if(kind==='auth'&&verb==='status')console.log(JSON.stringify({authenticated:true,host:'project.feishu.cn'}));
else if(kind==='workitem'&&verb==='get')console.log(readFileSync(process.env.REVIEW_FIXTURE,'utf8'));
else if(kind==='workhour'&&verb==='list-records'){
  if(process.env.REVIEW_SCENARIO==='records-denied'){console.error('synthetic permission_denied');process.exit(3);}
  console.log(JSON.stringify({Pagination:{page_num:1,page_size:20,total:0}}));
}else if(kind==='workflow'&&verb==='get-node'){
  if(process.env.REVIEW_SCENARIO==='node-failed'){console.error('synthetic request_failed');process.exit(4);}
  console.log(JSON.stringify({schedule:{actual_work_time:null}}));
}else{throw new Error('Forbidden fake CLI command');}
`,{mode:0o755});
  const p=spawnSync(process.execPath,[join(dir,'src','read-live.mjs')],{encoding:'utf8',timeout:10000,env:{...process.env,PATH:join(dir,'bin')+delimiter+process.env.PATH,REVIEW_FIXTURE:join(dir,'fixture.json'),REVIEW_SCENARIO:scenario,REVIEW_CALLS:join(dir,'calls.jsonl')}});
  const live=readdirSync(join(dir,'evidence')).filter(x=>x.startsWith('live-')).sort().at(-1);
  const liveDir=live?join(dir,'evidence',live):null;
  const out=liveDir&&existsSync(join(liveDir,'aggregate-week.json'))?JSON.parse(readFileSync(join(liveDir,'aggregate-week.json'),'utf8')):null;
  const report={scenario,exitCode:p.status,sourceSaved:!!(liveDir&&existsSync(join(liveDir,'t02-all-fields.json'))),receiptSaved:!!(liveDir&&existsSync(join(liveDir,'receipt.json'))),aggregateSaved:!!out,output:out?{hours:out.cells.map(c=>c.hours),coverageGaps:out.coverageGaps}:null,stderr:p.stderr.replaceAll(dir,'[isolated-test-dir]'),calls:readFileSync(join(dir,'calls.jsonl'),'utf8').trim().split('\n').map(JSON.parse)};
  writeFileSync(join(root,'review',`reader-${scenario}.json`),JSON.stringify(report,null,2));
  rmSync(dir,{recursive:true,force:true});
  return report;
}
test('CONTROL reader success reaches the real adapter using a fake CLI',()=>{
  const r=runReader('all-ok');assert.equal(r.exitCode,0);assert.equal(r.aggregateSaved,true);assert.deepEqual(r.output.hours,['8']);assert.equal(r.output.coverageGaps[0].status,'no_records');
});
for(const scenario of ['records-denied','node-failed'])test(`B02 available T02 subtotal must survive independent project failure: ${scenario}`,()=>{
  const r=runReader(scenario);assert.equal(r.sourceSaved,true,'T02 was read successfully');
  assert.equal(r.aggregateSaved,true,JSON.stringify({exitCode:r.exitCode,sourceSaved:r.sourceSaved,receiptSaved:r.receiptSaved,aggregateSaved:r.aggregateSaved}));
  assert.deepEqual(r.output.hours,['8']);assert.ok(r.output.coverageGaps.some(g=>['permission_denied','request_failed'].includes(g.status)));
});
