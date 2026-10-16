import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, copyFileSync, readdirSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, delimiter } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const root = fileURLToPath(new URL('../', import.meta.url));
const secret = 'SYNTHETIC-ERROR-CREDENTIAL-SENTINEL';
const fixture = {
  pagination: { has_more: false },
  work_item_attribute: { owned_project: { key: 'S' }, work_item_type: { key: 'E' }, work_item_id: 'T02', update_time: '2026-10-15T12:00:00+08:00' },
  work_item_fields: [{ key: 'field_f34a5f', value: [[
    { key: 'field_4ede40', value: { key: 'PERSON', name: '合成测试人员' } },
    { key: 'field_036afd', value: { start_time: { timestamp: 1789315200000 }, end_time: { timestamp: 1789919999999 } } },
    { key: 'field_3a677c', value: '8' }, { key: 'field_fe8c78', value: 'REG' }, { key: 'group_uuid', value: 'ROW' },
  ]] }],
};
function run(scenario) {
  const dir = mkdtempSync(join(tmpdir(), 'matrix-fix1-'));
  try {
    for (const d of ['src', 'input', 'bin', 'evidence']) mkdirSync(join(dir, d));
    for (const f of ['aggregate.mjs', 'read-live.mjs']) copyFileSync(join(root, 'src', f), join(dir, 'src', f));
    writeFileSync(join(dir, 'input/read-scope.json'), JSON.stringify(scenario === 'bad-config' ? null : { projectKey: 'S', extraItemId: 'T02', extraItemType: 'E', projectItemId: 'P', projectType: 'PROJECT' }));
    writeFileSync(join(dir, 'fixture.json'), JSON.stringify(fixture));
    mkdirSync(join(dir, 'evidence/live-stale'));
    writeFileSync(join(dir, 'evidence/live-stale/aggregate-week.json'), JSON.stringify({ cells: [{ hours: '999' }] }));
    writeFileSync(join(dir, 'bin/meegle'), `#!/usr/bin/env node
const fs=require('node:fs'),path=require('node:path');
const [kind,verb]=process.argv.slice(2),scenario=process.env.FIX1_SCENARIO,base=process.env.FIX1_ROOT;
const calls={kind,verb};
if(kind==='workflow'){
 const current=fs.readdirSync(path.join(base,'evidence')).find(x=>/^live-\\d/.test(x));
 calls.priorReceipts=JSON.parse(fs.readFileSync(path.join(base,'evidence',current,'receipt.json'),'utf8')).map(r=>({name:r.name,status:r.status}));
}
fs.appendFileSync(path.join(base,'calls.jsonl'),JSON.stringify(calls)+'\\n');
if(kind==='auth')console.log(JSON.stringify({authenticated:scenario!=='auth-failed',host:scenario==='wrong-host'?'other.example':'project.feishu.cn'}));
else if(kind==='workitem'){
 if(scenario==='source-failed'){console.error('${secret}');process.exit(2);}
 const d=JSON.parse(fs.readFileSync(path.join(base,'fixture.json'),'utf8'));
 if(scenario==='wrong-scope')d.work_item_attribute.work_item_id='UNAUTHORIZED';
 console.log(JSON.stringify(d));
}else if(kind==='workhour'){
 if(scenario==='structured-denied'){console.log(JSON.stringify({error:{code:'permission_denied',message:'${secret}'}}));console.error('${secret}');process.exit(3);}
 if(scenario==='bad-json'){console.log('${secret}');process.exit(0);}
 if(scenario==='bad-record-schema'){console.log(JSON.stringify({unexpected:'shape'}));process.exit(0);}
 if(scenario==='both-failed'){console.error('${secret}');process.exit(4);}
 console.log(JSON.stringify({Pagination:{page_num:1,page_size:20,total:scenario==='partial-page'?21:scenario==='nonempty-project'?1:0}}));
}else if(kind==='workflow'){
 if(scenario==='both-failed'){console.error('${secret}');process.exit(5);}
 console.log(JSON.stringify({list:[]}));
}else throw new Error('Unexpected command');
`, { mode: 0o755 });
    const p = spawnSync(process.execPath, [join(dir, 'src/read-live.mjs')], { encoding: 'utf8', timeout: 10000,
      env: { ...process.env, PATH: join(dir, 'bin') + delimiter + process.env.PATH, FIX1_SCENARIO: scenario, FIX1_ROOT: dir } });
    const current = readdirSync(join(dir, 'evidence')).find(x => /^live-\d/.test(x));
    const folder = join(dir, 'evidence', current);
    const read = name => existsSync(join(folder, name)) ? JSON.parse(readFileSync(join(folder, name), 'utf8')) : null;
    const receipt = read('receipt.json');
    const calls = existsSync(join(dir, 'calls.jsonl')) ? readFileSync(join(dir, 'calls.jsonl'), 'utf8').trim().split('\n').map(JSON.parse) : [];
    const serialized = readdirSync(folder).map(f => readFileSync(join(folder, f), 'utf8')).join('\n') + p.stdout + p.stderr;
    assert.ok(!serialized.includes(secret), 'Error payload leaked');
    return { status: p.status, receipt, calls, week: read('aggregate-week.json'), month: read('aggregate-month.json'), source: read('t02-all-fields.json') };
  } finally { rmSync(dir, { recursive: true, force: true }); }
}
for (const scenario of ['auth-failed', 'wrong-host']) test(`FIX1 guard: ${scenario} stops business reads with skipped receipts`, () => {
  const r = run(scenario);assert.equal(r.status, 1);assert.equal(r.week, null);assert.equal(r.calls.length, 1);
  assert.equal(r.receipt.filter(x => x.status === 'skipped').length, 3);
});
test('FIX1 guard: invalid scope config makes no CLI call', () => {
  const r = run('bad-config');assert.equal(r.status, 1);assert.equal(r.calls.length, 0);assert.equal(r.week, null);assert.equal(r.receipt[0].reason.code, 'invalid_scope_config');
});
test('FIX1 guard: wrong returned source stops remaining reads and is not saved', () => {
  const r = run('wrong-scope');assert.equal(r.status, 1);assert.equal(r.calls.length, 2);assert.equal(r.source, null);assert.equal(r.week, null);assert.equal(r.receipt.filter(x => x.status === 'skipped').length, 2);
});
test('FIX1 guard: failed primary source never reuses cached subtotal', () => {
  const r = run('source-failed');assert.equal(r.status, 1);assert.deepEqual(r.week.cells, []);assert.deepEqual(r.month.cells, []);assert.ok(r.week.coverageGaps.some(x => x.source === 'known-extra-item' && x.status === 'request_failed'));
});
test('FIX1: only structured permission denial is classified as denied', () => {
  const r = run('structured-denied');assert.equal(r.week.cells[0].hours, '8');assert.equal(r.week.coverageGaps[0].status, 'permission_denied');
});
test('FIX1: malformed independent response preserves 8h and records failure', () => {
  const r = run('bad-json');assert.equal(r.week.cells[0].hours, '8');assert.equal(r.month.cells[0].hours, '8');assert.equal(r.week.coverageGaps[0].reason.code, 'invalid_json_response');
});
test('FIX1: invalid project record schema is a failed receipt, never no-records', () => {
  const r = run('bad-record-schema');assert.equal(r.week.cells[0].hours, '8');
  assert.equal(r.week.coverageGaps[0].status,'request_failed');
  assert.equal(r.receipt.find(x=>x.name==='project-records').reason.code,'invalid_project_record_response');
});
test('FIX1: every completed command receipt exists before the next command', () => {
  const r = run('both-failed');assert.equal(r.week.cells[0].hours, '8');assert.equal(r.week.coverageGaps.length, 2);
  const prior=r.calls.find(x=>x.kind==='workflow').priorReceipts;
  assert.deepEqual(prior.map(x=>x.name),['auth-status','t02-all-fields','project-records']);assert.equal(prior[2].status,'request_failed');
  assert.equal(r.receipt.length,4);assert.ok(r.receipt.every(x=>Number.isFinite(Date.parse(x.startedAt))&&Number.isFinite(Date.parse(x.readAt))));
});
test('FIX1: incomplete project pagination is not represented as no records', () => {
  const r = run('partial-page');assert.equal(r.week.cells[0].hours, '8');assert.equal(r.week.coverageGaps[0].status, 'pagination_incomplete');
});
test('FIX1: nonempty project record count does not claim verified mapping', () => {
  const r = run('nonempty-project');assert.equal(r.week.cells[0].hours, '8');assert.equal(r.week.coverageGaps[0].status, 'mapping_unverified');
});
