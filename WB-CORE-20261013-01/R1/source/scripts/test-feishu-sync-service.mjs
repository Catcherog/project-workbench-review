#!/usr/bin/env node
// All stores live under one temporary directory. The adapter below has no network.
import assert from 'node:assert/strict';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
import {LocalStore} from './local-store.mjs';
import {FeishuSync} from './feishu-sync.mjs';

const root = fileURLToPath(new URL('..', import.meta.url));
const temp = mkdtempSync(path.join(tmpdir(), 'pm-feishu-sync-service-'));
const {build} = createRequire(path.join(root, 'package.json'))('esbuild');
const timestamp = '2026-09-23T12:00:00.000Z';
let domain, counter = 0;
const results = [];
class FakeAdapter {
  constructor() { this.fields = {description: 'base'}; this.writes = []; this.reads = 0; this.auths = 0; this.failReadback = false; }
  async auth() { this.auths++; return {authenticated: true}; }
  value(object) { return {externalObjectId: object.id, remoteId: object.remoteId, remoteKind: object.remoteKind, parentRemoteId: object.parentRemoteId, parentNodeRemoteId: object.parentNodeRemoteId, system: object.system, host: object.host, tenantKey: object.tenantKey, spaceKey: object.spaceKey, fields: structuredClone(this.fields), raw: {fields: structuredClone(this.fields)}, collectedAt: this.collectedAt || timestamp, complete: true}; }
  async readObjects(objects) {
    this.reads++;
    if (this.block) await this.block;
    if (this.missing) return [];
    const rows = objects.map(object => this.value(object));
    if (this.incomplete) for (const row of rows) { row.complete = false; row.error = 'isolated permission failure'; row.fields = {description: 'must not overwrite'}; }
    if (this.mismatch) for (const row of rows) row.remoteId = 'wrong-remote';
    return rows;
  }
  async readObject(object) {
    if (this.failReadback) throw new Error('isolated network read failure');
    const row = this.value(object);
    if (this.readbackMismatch) row.remoteId = 'wrong-remote';
    return row;
  }
  async writeFields(object, patches) {
    this.writes.push({object: structuredClone(object), patches: structuredClone(patches)});
    for (const patch of patches) this.fields[patch.remoteFieldKey] = patch.proposed;
    if (this.uncertainWrite) { this.failReadback = true; throw Object.assign(new Error('isolated uncertain transport failure'), {uncertain: true}); }
  }
}
async function fixture() {
  const store = new LocalStore(path.join(temp, `store-${++counter}`), {testMode: true});
  await store.initialize(null);
  let state = domain.emptyState('official', '隔离同步测试', 'official');
  state = domain.manualEdit(state, {kind: 'projects', targetId: 'p1', action: 'create', before: {}, after: {title: '隔离项目', description: 'base', projectIds: [], sourceIds: []}, requestId: randomUUID()});
  state.externalObjects = [{id: 'ext-p', workspaceId: 'official', system: 'meegle', host: 'project.feishu.cn', tenantKey: 'tenant', spaceKey: 'test-space', remoteKind: 'project', remoteId: 'rp1', parentRemoteId: '', parentNodeRemoteId: '', parentDeliverableRemoteId: '', localObjectId: 'p1', sourceId: '', collectedAt: '2026-09-20T00:00:00.000Z', sourceHash: 'base', verificationStatus: 'verified', mappingStatus: 'mapped', raw: {workItemType: 'test-type'}}];
  state.mappingRules = [{id: 'rule-description', workspaceId: 'official', system: 'meegle', remoteKind: 'project', remoteFieldKey: 'description', remoteFieldName: '描述', remoteValueType: 'text', localKind: 'projects', localField: 'description', conversionRule: 'identity', writable: true, requiresReview: true, bidirectional: false, status: 'active'}];
  state.syncBaselines = [{id: 'base-p', workspaceId: 'official', externalObjectId: 'ext-p', capturedAt: '2026-09-20T00:00:00.000Z', sourceHash: 'base', remoteValues: {description: 'base'}, localValues: {description: 'base'}, localRevision: state.revision, sourceId: ''}];
  assert.deepEqual(domain.validateState(state), []);
  store.transaction(() => store.save(state, store.load('official').revision));
  const adapter = new FakeAdapter(), service = new FeishuSync({store, domain, adapter, clock: () => timestamp, intervalMs: 60000});
  const edit = text => {
    const current = store.load('official');
    const next = domain.manualEdit(current, {kind: 'projects', targetId: 'p1', action: 'update', before: {description: current.projects[0].description}, after: {description: text}, requestId: randomUUID()});
    store.transaction(() => store.save(next, current.revision));
  };
  const prepare = async () => { edit('经理获批文本'); await service.prepare('official', {requestId: randomUUID(), wait: true}); const run = service.status('official').runs[0]; assert.equal(run?.status, 'pending_review'); return run; };
  const approve = (run, extra = {}) => service.approve('official', {runId: run.id, fingerprint: run.fingerprint, confirmed: true, approvedBy: '本人', requestId: randomUUID(), wait: true, ...extra});
  return {store, adapter, service, edit, prepare, approve, async close() { await service.close(); store.close(); }};
}
async function test(name, callback) {
  const env = await fixture();
  try { await callback(env); results.push({name, ok: true}); console.log(`PASS ${name}`); }
  catch (error) { results.push({name, ok: false}); console.error(`FAIL ${name}\n${error.stack}`); }
  finally { await env.close(); }
}

try {
  await build({absWorkingDir: root, entryPoints: ['lib/local-runtime.ts'], outfile: path.join(temp, 'domain.mjs'), bundle: true, platform: 'node', format: 'esm', target: 'node22', logLevel: 'silent'});
  domain = await import(pathToFileURL(path.join(temp, 'domain.mjs')).href);
  await test('core preflight refresh reads only registered targets and propagates incomplete-read failure', async ({service,store,adapter}) => {
    adapter.fields.description='fresh external fact';const result=await service.refreshTargets('official',['p1']);assert.equal(result.read,1);assert.equal(adapter.writes.length,0);assert.equal(store.load('official').projects[0].description,'fresh external fact');
    adapter.incomplete=true;await assert.rejects(()=>service.refreshTargets('official',['p1']),/尚未完整读回/);assert.equal(store.load('official').projects[0].description,'fresh external fact');
    await assert.rejects(()=>service.refreshTargets('official',['unmapped-target']),/读取映射/);
  });
  await test('legacy missing nodes stay visible without backing off unchanged incremental reads', async ({service,store,adapter}) => {
    const state=store.load('official');
    state.flowNodes.push({id:'n1',title:'历史节点',projectIds:['p1'],sourceIds:[],version:1,nodeType:'里程碑节点',nodeStatus:'已完成'});
    state.riskPolicy={version:1,historicalProjectIds:['p1'],adoptedAt:timestamp};
    const node={...state.externalObjects[0],id:'ext-n',remoteKind:'node',remoteId:'old-node',parentRemoteId:'rp1',localObjectId:'n1'};
    state.externalObjects.push(node);state.revision++;store.save(state,state.revision-1);
    let projectVersion='v1';const batches=[];
    adapter.discover=async()=>({complete:true,objects:[{spaceKey:'test-space',remoteKind:'project',remoteId:'rp1',updatedAt:projectVersion}]});
    adapter.readObjects=async objects=>{batches.push(objects.map(o=>o.id));return objects.map(o=>o.remoteKind==='node'?{...adapter.value(o),complete:false,error:'未找到已登记的飞书节点'}:adapter.value(o));};
    service.configure('official',{enabled:true,intervalSeconds:60});
    let result=await service.poll('official',{wait:true});
    assert.equal(result.status.historicalNodeGaps,1);assert.equal(result.inaccessible.length,1);assert.equal(result.status.phase,'idle');
    assert.equal(Date.parse(result.status.nextRunAt)-Date.parse(timestamp),60000);
    const before=batches.length;result=await service.poll('official',{wait:true});
    assert.equal(batches.length,before);assert.equal(result.status.skippedUnchanged,2);assert.equal(result.status.historicalNodeGaps,1);
    projectVersion='v2';await service.poll('official',{wait:true});assert.ok(batches.at(-1).includes('ext-n'),'changed parent causes node recheck');
    service.update('official',c=>{c.status.readPolicyVersion=1;});await service.poll('official',{wait:true});assert.equal(batches.at(-1).length,2,'new conversion policy forces one complete read');
    const upgraded=batches.length;await service.poll('official',{wait:true});assert.equal(batches.length,upgraded,'upgrade scan runs once');assert.equal(adapter.writes.length,0);
  });
  await test('unapproved writes blocked; approved exact payload writes once and readback persists', async ({service, store, adapter, prepare, approve}) => {
    const run = await prepare();
    assert.equal(adapter.writes.length, 0);
    await assert.rejects(service.execute('official', run.id, {wait: true}), /尚未获批/);
    await assert.rejects(approve(run, {confirmed: false}), /批准/);
    await assert.rejects(approve(run, {fingerprint: 'wrong'}), /变化/);
    assert.equal(adapter.writes.length, 0);
    const requestId = randomUUID();
    const result = await approve(run, {requestId});
    assert.equal(result.runs[0].status, 'readback_verified', JSON.stringify(result.runs[0]));
    assert.equal(result.runs[0].receipts[0].status, 'readback_verified');
    assert.equal(adapter.writes.length, 1);
    assert.equal(adapter.writes[0].patches[0].proposed, '经理获批文本');
    assert.equal(store.load('official').syncBaselines[0].remoteValues.description, '经理获批文本');
    await approve(run, {requestId});
    assert.equal(adapter.writes.length, 1, 'approval retry cannot replay a write');
    assert.deepEqual(domain.validateState(store.load('official')), []);
  });
  await test('local edits after preparation invalidate exact approval', async ({adapter, prepare, approve, edit}) => {
    const run = await prepare(); edit('审核页面打开后又编辑');
    await assert.rejects(approve(run), /本地内容已改变/);
    assert.equal(adapter.writes.length, 0);
  });
  await test('server-held patch tampering invalidates fingerprint', async ({adapter, service, prepare, approve}) => {
    const run = await prepare();
    service.update('official', value => { value.runs[0].patches[0].proposed = 'tampered'; });
    await assert.rejects(approve(run), /校验失败/);
    assert.equal(adapter.writes.length, 0);
  });
  await test('remote drift after preparation stops all writes', async ({adapter, prepare, approve}) => {
    const run = await prepare(); adapter.fields.description = '飞书另有人更新';
    const result = await approve(run);
    assert.equal(result.runs[0].status, 'conflict');
    assert.equal(adapter.writes.length, 0);
  });
  await test('mismatched preflight identity cannot authorize write', async ({adapter, prepare, approve}) => {
    const run = await prepare(); adapter.mismatch = true;
    const result = await approve(run);
    assert.notEqual(result.runs[0].status, 'readback_verified');
    assert.equal(adapter.writes.length, 0);
  });
  await test('mismatched readback identity cannot claim success', async ({adapter, prepare, approve}) => {
    const run = await prepare(); adapter.readbackMismatch = true;
    const result = await approve(run);
    assert.equal(adapter.writes.length, 1);
    assert.equal(result.runs[0].status, 'needs_reconcile');
  });
  await test('older preflight snapshot cannot authorize write', async ({adapter, prepare, approve}) => {
    const run = await prepare(); adapter.collectedAt = '2026-09-21T00:00:00.000Z';
    const result = await approve(run);
    assert.equal(result.runs[0].status, 'conflict');
    assert.equal(adapter.writes.length, 0);
  });
  await test('uncertain transport result reconciles by read only without duplicate writes', async ({adapter, service, prepare, approve}) => {
    const run = await prepare(); adapter.uncertainWrite = true;
    const result = await approve(run);
    assert.equal(result.runs[0].status, 'needs_reconcile');
    assert.equal(adapter.writes.length, 1);
    adapter.failReadback = false;
    const reconciled = await service.reconcile('official', run.id, {wait: true});
    assert.equal(reconciled.runs[0].status, 'readback_verified');
    assert.equal(reconciled.runs[0].receipts[0].status, 'readback_verified');
    assert.equal(adapter.writes.length, 1);
    await assert.rejects(service.execute('official', run.id, {wait: true}), /尚未获批/);
  });
  await test('reconciliation verifies the originally approved target, not a changed binding', async ({adapter, service, store, prepare, approve}) => {
    const run = await prepare(); adapter.uncertainWrite = true;
    await approve(run);
    const before = store.load('official'), changed = structuredClone(before);
    changed.externalObjects[0].remoteId = 'different-remote'; changed.revision++;
    store.transaction(() => store.save(changed, before.revision));
    adapter.failReadback = false;
    const result = await service.reconcile('official', run.id, {wait: true});
    assert.equal(result.runs[0].status, 'needs_reconcile');
    assert.match(result.status.lastError.message, /原飞书目标/);
    assert.equal(adapter.writes.length, 1);
  });
  await test('restart recovers sending to needs_reconcile and expires approved runs', async ({service, store, adapter, prepare}) => {
    const run = await prepare();
    service.update('official', value => { value.runs[0].status = 'sending'; value.runs[0].approvedAt = timestamp; value.runs[0].approvedBy = '本人'; value.runs.push({...structuredClone(value.runs[0]), id: 'old-approved', status: 'approved'}); });
    await service.close();
    const restarted = new FeishuSync({store, domain, adapter, clock: () => timestamp, intervalMs: 60000});
    try {
      restarted.start();
      const status = restarted.status('official');
      assert.equal(status.runs.find(row => row.id === run.id).status, 'needs_reconcile');
      assert.equal(status.runs.find(row => row.id === 'old-approved').status, 'stale');
      assert.equal(adapter.writes.length, 0);
    } finally { await restarted.close(); }
  });
  await test('one outstanding job per workspace', async ({service, adapter}) => {
    let release;
    adapter.block = new Promise(resolve => { release = resolve; });
    const running = service.poll('official', {wait: true});
    await Promise.resolve();
    try { await assert.rejects(service.poll('official', {wait: true}), /已有同步任务/); }
    finally { release(); await running; }
    assert.equal(adapter.reads, 1);
    assert.equal(service.jobs.size, 0);
  });
  await test('incomplete reads preserve data and outstanding conflict records', async ({service, store, adapter, edit}) => {
    edit('本地变更'); adapter.fields.description = '远端变更';
    await service.poll('official', {wait: true});
    assert.equal(service.status('official').conflicts.length, 1);
    const before = store.load('official'); adapter.incomplete = true;
    const result = await service.poll('official', {wait: true});
    assert.equal(store.load('official').projects[0].description, '本地变更');
    assert.deepEqual(store.load('official').syncBaselines, before.syncBaselines);
    assert.equal(result.conflicts.length, 1, 'failed read must not erase unresolved conflict');
    assert.equal(result.inaccessible.length, 1);
    assert.equal(result.status.lastError.code, 'PARTIAL_READ');
  });
  await test('missing object responses are failures rather than successful empty polls', async ({service, adapter}) => {
    adapter.missing = true;
    const result = await service.poll('official', {wait: true});
    assert.equal(result.inaccessible.length, 1);
    assert.equal(result.status.lastSucceededAt, '');
    assert.equal(result.status.lastError.code, 'PARTIAL_READ');
  });
  await test('keeping local conflict value still needs a separate exact write approval', async ({service, store, adapter, edit, approve}) => {
    edit('经理保留的文本'); adapter.fields.description = '飞书另一版';
    const poll = await service.poll('official', {wait: true});
    const conflict = poll.conflicts[0];
    const resolved = await service.resolve('official', {conflictId: conflict.id, fingerprint: conflict.fingerprint, choice: 'local', wait: true});
    assert.equal(resolved.conflicts.length, 0, JSON.stringify(resolved.status.lastError));
    assert.equal(store.load('official').projects[0].description, '经理保留的文本');
    assert.equal(store.load('official').syncBaselines[0].remoteValues.description, '飞书另一版');
    assert.equal(store.load('official').syncBaselines[0].localValues.description, 'base');
    assert.equal(adapter.writes.length, 0);
    const prepared = await service.prepare('official', {requestId: randomUUID(), wait: true});
    assert.equal(prepared.runs[0].status, 'pending_review');
    assert.equal(prepared.runs[0].patches[0].before, '飞书另一版');
    assert.equal(adapter.writes.length, 0);
    assert.equal((await approve(prepared.runs[0])).runs[0].status, 'readback_verified');
    assert.equal(adapter.writes.length, 1);
  });
  await test('adopting remote conflict value changes local mirror only', async ({service, store, adapter, edit}) => {
    edit('本地编辑'); adapter.fields.description = '采用飞书';
    const conflict = (await service.poll('official', {wait: true})).conflicts[0];
    const result = await service.resolve('official', {conflictId: conflict.id, fingerprint: conflict.fingerprint, choice: 'remote', wait: true});
    assert.equal(result.conflicts.length, 0);
    assert.equal(store.load('official').projects[0].description, '采用飞书');
    assert.equal(service.candidates(store.load('official')).length, 0);
    assert.equal(adapter.writes.length, 0);
  });
  await test('conflict resolution rereads source and refuses a stale displayed value', async ({service, store, adapter, edit}) => {
    edit('本地编辑'); adapter.fields.description = '第一次飞书更新';
    const conflict = (await service.poll('official', {wait: true})).conflicts[0];
    adapter.fields.description = '审核时飞书再次更新';
    const result = await service.resolve('official', {conflictId: conflict.id, fingerprint: conflict.fingerprint, choice: 'remote', wait: true});
    assert.equal(store.load('official').projects[0].description, '本地编辑');
    assert.equal(result.conflicts[0].remoteValue, '审核时飞书再次更新');
    assert.equal(adapter.writes.length, 0);
    assert.match(result.status.lastError.message, /飞书值已变化/);
  });
  await test('backup retains sync evidence; restore disables polling and expires approvals', async ({service, store, adapter, prepare}) => {
    const run = await prepare();
    service.configure('official', {enabled: true, intervalSeconds: 60});
    service.update('official', value => { value.runs.push({...structuredClone(value.runs[0]), id: 'sending-backup', status: 'sending', approvedBy: '本人', approvedAt: timestamp}); });
    const bundle = store.bundle('official');
    assert.equal(bundle.feishuSync.official.runs.length, 2);
    const preview = store.preview(bundle);
    const restored = await service.withSuspended(() => store.restore({token: preview.token, mode: 'new', confirmed: true}));
    const restoredId = restored.workspaces[0].id;
    const control = service.control(restoredId);
    assert.equal(control.config.enabled, false);
    assert.equal(control.runs.find(row => row.id === run.id).status, 'stale');
    assert.equal(control.runs.find(row => row.id === 'sending-backup').status, 'needs_reconcile');
    assert.deepEqual(control.requests, {});
    assert.deepEqual(domain.validateState(store.load(restoredId)), []);
    await assert.rejects(service.poll(restoredId, {wait: true}), /恢复检查/);
    assert.throws(() => service.configure(restoredId, {enabled: true, intervalSeconds: 60}), /恢复检查/);
    assert.equal(adapter.writes.length, 0);
  });
  const failed = results.filter(row => !row.ok);
  if (failed.length) throw new Error(`${failed.length}/${results.length} isolated sync service checks failed: ${failed.map(row => row.name).join('; ')}`);
  console.log(`PASS ${results.length} isolated Feishu service checks; no production store or real CLI accessed`);
} finally {
  rmSync(temp, {recursive: true, force: true});
}
