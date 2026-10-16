import {resolveMeegleCli} from './cli-runtime.mjs';
import { createHash, randomUUID } from 'node:crypto';
import { MeegleSyncAdapter } from './feishu-sync-cli.mjs';
import {importDiscoveredDeliverables,importDiscoveredNodes} from './feishu-deliverable-adoption.mjs';

const now = () => new Date().toISOString();
const clone = value => structuredClone(value);
const canonical = value => JSON.stringify(value ?? null, (_key, item) => item && typeof item === 'object' && !Array.isArray(item) ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);
const equal = (a, b) => canonical(a) === canonical(b);
const digest = value => createHash('sha256').update(canonical(value)).digest('hex');
const fail = (message, status = 400) => Object.assign(new Error(message), {status});
const safeError = error => ({code: String(error?.code || 'SYNC_ERROR'), message: String(error?.message || error).slice(0, 1500), retryable: error?.retryable === true});
const allowedPairs = new Map([['name', 'title'], ['description', 'description'], ['field_5a13c8', 'projectProgress'], ['field_d014b4', 'deliverableProgress'], ['field_922242', 'resultLink']]);
const identity = object => ({id: object.id, system: object.system, host: object.host, spaceKey: object.spaceKey, tenantKey: object.tenantKey, remoteKind: object.remoteKind, remoteId: object.remoteId, parentRemoteId: object.parentRemoteId, parentNodeRemoteId: object.parentNodeRemoteId,parentDeliverableRemoteId:object.parentDeliverableRemoteId, localObjectId: object.localObjectId});
const kindFor = object => ({project: 'projects', node: 'flowNodes', deliverable: 'deliverables'}[object.remoteKind]);
const localFor = (state, object) => state[kindFor(object)]?.find(row => row.id === object.localObjectId);
const pendingField = (state, objectId, field) => state.changeGroups?.some(group => ['pending', 'partial', 'conflict'].includes(group.status) && group.operations.some(op => op.targetId === objectId && !['accepted', 'rejected'].includes(op.status) && Object.hasOwn(op.after || {}, field)));
const readMatches = (object, read) => !!object && read?.complete === true && !read.error && read.externalObjectId===object.id && ['remoteId','remoteKind','parentRemoteId'].every(key=>String(read[key]??'')===String(object[key]??'')&&typeof read[key]==='string') && ['system','host','spaceKey','tenantKey','parentNodeRemoteId','parentDeliverableRemoteId'].every(key=>read[key]===undefined||read[key]===object[key]) && read.fields && typeof read.fields==='object' && !Array.isArray(read.fields) && read.raw && typeof read.raw==='object' && Number.isFinite(Date.parse(read.collectedAt)) && (!Number.isFinite(Date.parse(object.collectedAt))||Date.parse(read.collectedAt)>=Date.parse(object.collectedAt));

/** Durable orchestration owned by the local service. The model has no mutation
 * route here. All approved writes are constructed from server-held differences. */
export class FeishuSync {
  constructor({store, domain, adapter, adapterFactory, clock = now, intervalMs = 1000}) {
    this.store = store; this.domain = domain; this.clock = clock; this.intervalMs = intervalMs;
    this.adapter = adapter; this.adapterFactory = adapterFactory;
    this.adapters = new Map(); this.jobs = new Map(); this.closed = false;
  }
  key(id) { return 'feishuSync:' + id; }
  control(id) {
    this.store.load(id);
    const prior = this.store.getSetting(this.key(id));
    return prior || {version: 1, workspaceId: id, config: {enabled: false, intervalSeconds: 60}, status: {phase: 'idle', lastStartedAt: '', lastSucceededAt: '', nextRunAt: '', lastError: null, processed: 0, total: 0, consecutiveFailures: 0}, runs: [], conflicts: [], inaccessible: [], discoveries: [], requests: {}};
  }
  save(id, value) { this.store.setSetting(this.key(id), value); }
  assertWorkspace(id) { const state=this.store.load(id); if (['demo','restored'].includes(state.workspaceType)) throw fail('演示或恢复检查工作区不能操作真实飞书同步'); return state; }
  update(id, fn) { return this.store.transaction(() => { const value = this.control(id); fn(value); this.save(id, value); return value; }); }
  objects(state) { return state.externalObjects.filter(row => row.system === 'meegle' && row.host === 'project.feishu.cn' && ['project', 'node', 'deliverable'].includes(row.remoteKind) && row.mappingStatus !== 'quarantined' && localFor(state, row) && !localFor(state, row).archived); }
  client(id) {
    if (this.adapter) return this.adapter;
    if (!this.adapters.has(id)) this.adapters.set(id, this.adapterFactory ? this.adapterFactory(id) : new MeegleSyncAdapter({cli: resolveMeegleCli(), profile: process.env.PM_MEEGLE_PROFILE, host: 'project.feishu.cn',expectedUserKey:this.control(id).identity?.userKey}));
    return this.adapters.get(id);
  }
  status(id) {
    const state = this.store.load(id), value = this.control(id), objects = this.objects(state);
    const byId = new Map(objects.map(row => [row.id, row]));
    const imported=state.deliverables.filter(row=>!row.archived&&/^deliverable:\d+$/.test(row.importedFrom?.sourceId||'')&&!objects.some(o=>o.localObjectId===row.id)).flatMap(row=>{const parents=objects.filter(o=>o.remoteKind==='project'&&row.projectIds.includes(o.localObjectId));return parents.length===1?[{remoteId:row.importedFrom.sourceId.slice(12),remoteKind:'deliverable',spaceKey:parents[0].spaceKey,title:row.title}]:[];});
    const discoveries=[...new Map([...(value.discoveries||[]),...imported].map(item=>[[item.spaceKey,item.remoteKind,item.remoteId].join(':'),item])).values()];
    return {...clone(value),conflicts:value.conflicts.map(row=>({...row,fingerprint:digest(row)})), config: {...value.config, spaceKey: [...new Set(objects.map(row => row.spaceKey))].join(', '), profile: process.env.PM_MEEGLE_PROFILE || '', scopeCount: objects.length}, status: {...value.status, phase:this.jobs.has(id)&&value.status.phase==='error'?'polling':value.status.phase, conflicts: value.conflicts.length, inaccessible: value.inaccessible.length+(value.readWarnings||[]).length}, capabilities: {read: true, writeFields: ['名称', '描述', '项目进度', '交付物进度', '成果链接'], unsupportedWrites: ['负责人和权限', '状态与节点流转', '验收和审核字段', '附件上传', '对象创建与删除']},
      mirrors: [...byId.values()].map(object => ({externalObjectId: object.id, objectTitle: localFor(state, object)?.title || object.remoteId, remoteId: object.remoteId, remoteKind: object.remoteKind, collectedAt: object.collectedAt, verificationStatus: object.verificationStatus, fields: state.remoteFieldValues.filter(row => row.externalObjectId === object.id).map(row => ({key: row.remoteFieldKey, name: row.remoteFieldName, value: row.rawValue, localField: row.localField}))})),
      discoveries:discoveries.filter(item=>!objects.some(o=>o.remoteId===item.remoteId&&o.spaceKey===item.spaceKey&&o.remoteKind===item.remoteKind)).map(item=>({...item,canAdopt:item.remoteKind==='deliverable'&&state.deliverables.some(d=>!d.archived&&d.importedFrom?.sourceId==='deliverable:'+item.remoteId)})),
      runs: clone(value.runs).reverse(), requests: undefined};
  }
  async adopt(id,{remoteId,spaceKey,wait=false}={}) {
    const initial=this.assertWorkspace(id);
    const candidate=initial.deliverables.find(row=>!row.archived&&row.importedFrom?.sourceId==='deliverable:'+remoteId);
    if(!candidate||!/^\d+$/.test(remoteId||''))throw fail('请先核对并导入这个交付物的稳定身份',409);
    if(initial.externalObjects.some(o=>o.localObjectId===candidate.id||o.remoteId===remoteId&&o.spaceKey===spaceKey))throw fail('交付物已有映射，请沿用现有关联',409);
    const active=o=>o.verificationStatus==='verified'&&!['conflict','quarantined','unmapped'].includes(o.mappingStatus)&&o.system==='meegle'&&o.host==='project.feishu.cn'&&o.spaceKey===spaceKey;
    const parents=initial.externalObjects.filter(o=>active(o)&&o.remoteKind==='project'&&candidate.projectIds.includes(o.localObjectId));
    const nodes=(candidate.flowNodeIds||[]).map(nodeId=>initial.externalObjects.filter(o=>active(o)&&o.remoteKind==='node'&&o.localObjectId===nodeId));
    if(parents.length!==1||!nodes.length||nodes.some(rows=>rows.length!==1||rows[0].parentRemoteId!==parents[0].remoteId))throw fail('需要唯一、已核对的所属项目与节点身份',409);
    const parent=parents[0],proof=initial.sources.find(s=>candidate.sourceIds.includes(s.id)&&s.importedFrom?.sourceId===candidate.importedFrom.sourceId&&!s.archived);
    if(!proof)throw fail('缺少已导入的原始回读依据',409);
    let workItemType;try{workItemType=JSON.parse(proof.excerpt).raw.work_item_attribute.work_item_type.key;}catch{throw fail('原始回读缺少工作项类型',409);}
    const object={id:'external-adopt-'+digest([parent.system,parent.host,parent.tenantKey,spaceKey,remoteId]).slice(0,32),workspaceId:id,system:'meegle',host:parent.host,tenantKey:parent.tenantKey,spaceKey,remoteKind:'deliverable',remoteId,parentRemoteId:parent.remoteId,parentNodeRemoteId:nodes[0][0].remoteId,parentDeliverableRemoteId:'',localObjectId:candidate.id,sourceId:proof.id,collectedAt:proof.collectedAt,sourceHash:proof.importedFrom.contentSha256,verificationStatus:'verified',mappingStatus:'mapped',raw:{title:candidate.title,workItemType},url:candidate.importedFrom.url};
    const basis=digest([candidate,proof,nodes.map(rows=>identity(rows[0])),identity(parent)]);
    const promise=this.queue(id,'polling',async signal=>{
      const client=this.client(id);await client.auth({signal});const read=await client.readObject(object,{signal});
      if(!readMatches(object,read))throw fail('交付物当前回读身份不一致',409);
      const related=[read.fields.field_f7b70e,read.fields.field_69751f].map(v=>String(v?.id??v??''));
      if(!related.includes(parent.remoteId)||related.some(v=>v&&v!==parent.remoteId))throw fail('远端所属项目与本地关联不一致',409);
      for(const rows of nodes){const node=rows[0],r=await client.readObject(node,{signal});if(!readMatches(node,r)||!r.raw.sub_workitems?.some(group=>group.workitems?.map(String).includes(remoteId)))throw fail('尚未回读到节点子工作项挂接，未登记同步',409);}
      this.store.transaction(()=>{
        const before=this.store.load(id),local=before.deliverables.find(row=>row.id===candidate.id),source=before.sources.find(s=>s.id===proof.id);
        if(digest([local,source,nodes.map(rows=>{const n=before.externalObjects.find(o=>o.id===rows[0].id);return n&&identity(n);}),identity(before.externalObjects.find(o=>o.id===parent.id)||{})])!==basis)throw fail('核对期间本地归属或来源已有变化',409);
        if(before.externalObjects.some(o=>o.localObjectId===candidate.id||o.spaceKey===spaceKey&&o.remoteId===remoteId&&o.remoteKind==='deliverable'))throw fail('另一操作已接入此对象，请刷新',409);
        const next=clone(before);next.externalObjects.push(object);
        const rules=before.mappingRules.filter(r=>r.system==='meegle'&&r.remoteKind==='deliverable'&&r.status==='active'&&r.localField);
        next.syncBaselines.push({id:'baseline-adopt-'+digest(object.id).slice(0,32),workspaceId:id,externalObjectId:object.id,capturedAt:read.collectedAt,sourceHash:object.sourceHash,remoteValues:clone(read.fields),localValues:Object.fromEntries(rules.map(r=>[r.localField,clone(local[r.localField]??'')])),localRevision:before.revision,sourceId:proof.id});
        const merged=this.domain.mergeFeishuRead(next,[read],{now:this.clock()}).state;
        for(const kind of ['projects','flowNodes','deliverables','actions','risks','decisions'])if(!equal(merged[kind],before[kind]))throw fail('接入同步不应改写已有业务字段，请重新核对',409);
        if(merged.revision===before.revision)merged.revision++;
        merged.audit.push({id:'registry-adopt-'+randomUUID(),time:this.clock(),operation:'registry.adopt',objectId:candidate.id,kind:'deliverables',before:null,after:{remoteId,spaceKey,nodeIds:nodes.map(rows=>rows[0].remoteId)}});
        const errors=this.domain.validateState(merged);if(errors.length)throw fail(errors.map(e=>e.message).join('；'));
        this.store.save(merged,before.revision);
      });
      this.update(id,value=>{value.status.lastSucceededAt=this.clock();value.status.consecutiveFailures=0;});
    });
    if(wait)await promise;return this.status(id);
  }
  start() {
    for (const workspace of this.store.list()) {
      if (!this.store.getSetting(this.key(workspace.id))) continue;
      if(workspace.type==='official'&&this.control(workspace.id).config.enabled){
        const state=this.store.load(workspace.id),mirrors=this.objects(state).filter(o=>o.verificationStatus==='verified').flatMap(o=>{
          const keys=o.remoteKind==='deliverable'?['work_item_status','field_b462b3']:o.remoteKind==='node'?['status']:[];
          const fields=Object.fromEntries(state.remoteFieldValues.filter(f=>f.externalObjectId===o.id&&keys.includes(f.remoteFieldKey)).map(f=>[f.remoteFieldKey,f.rawValue]));
          return Object.keys(fields).length?[{...identity(o),externalObjectId:o.id,fields,raw:o.raw||{},complete:true,collectedAt:o.collectedAt}]:[];
        });
        if(mirrors.length)try{const result=this.merge(workspace.id,mirrors);this.update(workspace.id,c=>{c.status.bootstrapFactsApplied=result.changes;});}catch(error){this.update(workspace.id,c=>{c.status.bootstrapError=safeError(error);});}
      }
      this.update(workspace.id, value => {
        for (const run of value.runs) if (['sending', 'approved'].includes(run.status)) { run.status = run.status === 'sending' ? 'needs_reconcile' : 'stale'; run.error = '服务重启：请先核对远端结果或重新审核，系统不会自动重发。'; }
        value.status.phase = 'idle';
        if (value.config.enabled) value.status.nextRunAt = this.clock();
      });
    }
    this.timer = setInterval(() => void this.tick(), this.intervalMs); this.timer.unref();
  }
  async tick() {
    if (this.closed || this.suspended) return;
    for (const workspace of this.store.list()) {
      const value = this.control(workspace.id);
      if (value.config.enabled && !this.jobs.has(workspace.id) && (!value.status.nextRunAt || Date.parse(value.status.nextRunAt) <= Date.parse(this.clock()))) this.poll(workspace.id).catch(() => {});
    }
  }
  configure(id, config) {
    const state = this.store.load(id);
    if (state.workspaceType === 'demo' || state.workspaceType === 'restored') throw fail('演示或恢复检查工作区不能启用真实同步');
    if (typeof config.enabled !== 'boolean' || !Number.isInteger(config.intervalSeconds) || config.intervalSeconds < 30 || config.intervalSeconds > 3600) throw fail('同步间隔须为 30–3600 秒');
    if (config.enabled && !this.objects(state).length) throw fail('尚无已关联的飞书对象，请先完成只读导入和对象映射');
    this.update(id, value => { value.config = {enabled: config.enabled, intervalSeconds: config.intervalSeconds}; value.status.nextRunAt = config.enabled ? this.clock() : ''; });
    return this.status(id);
  }
  queue(id, phase, task) {
    if (this.closed || this.suspended) throw fail('同步服务正在退出或恢复数据', 503);
    if (this.jobs.has(id)) throw fail('此工作区已有同步任务进行中，请等待完成', 409);
    const controller = new AbortController();
    const promise = Promise.resolve().then(async () => {
      this.update(id, value => { value.status.phase = phase; value.status.lastStartedAt = this.clock(); value.status.lastError = null; value.status.processed = 0; });
      try { await task(controller.signal); }
      catch (error) { this.update(id, value => { value.status.phase = 'error'; value.status.lastError = safeError(error); value.status.consecutiveFailures = (value.status.consecutiveFailures || 0) + 1; }); }
      finally {
        this.update(id, value => { if (value.status.phase !== 'error') value.status.phase = 'idle'; const delay = Math.min(3600, value.config.intervalSeconds * 2 ** Math.min(value.status.consecutiveFailures || 0, 6)); value.status.nextRunAt = value.config.enabled ? new Date(Date.parse(this.clock()) + delay * 1000).toISOString() : ''; });
        this.jobs.delete(id);
      }
    });
    this.jobs.set(id, {promise, controller});
    return promise;
  }
  async read(id, objects, signal) {
    const client = this.client(id);
    const auth=await client.auth({signal});
    if(auth?.userKey)this.update(id,value=>{if(value.identity?.userKey&&value.identity.userKey!==auth.userKey)throw fail('飞书登录身份已改变，请重新核实配置',403);value.identity={host:auth.host,userKey:auth.userKey,profile:auth.profile||''};});
    this.update(id, value => { value.status.total = objects.length; });
    if (client.readObjects) {
      const result = await client.readObjects(objects, {signal,includeComments:true, onProgress: progress => { const processed = typeof progress === 'number' ? progress : progress?.processed??progress?.completed; if (Number.isFinite(processed)) this.update(id, value => { value.status.processed = processed; }); }});
      if(result.discoveries?.length)this.update(id,value=>{value.discoveries=[...new Map([...value.discoveries,...result.discoveries].map(row=>[`${row.spaceKey}:${row.remoteKind}:${row.parentRemoteId||''}:${row.remoteId}`,row])).values()];});
      this.update(id,value=>{value.readWarnings=(result.errors||[]).filter(row=>row.scope==='comments').map(row=>({externalObjectId:row.externalObjectId,scope:'comments',reason:safeError(row.error||row.reason).message}));});
      const rows=Array.isArray(result) ? result : [...(result.reads || []), ...(result.errors || []).filter(row=>row.scope!=='comments').map(row => ({...row, complete: false, error: row.error || row.reason}))];
      return objects.map(object=>{const matches=rows.filter(row=>row.externalObjectId===object.id);if(matches.length!==1||!readMatches(object,matches[0]))return {externalObjectId:object.id,remoteId:object.remoteId,remoteKind:object.remoteKind,parentRemoteId:object.parentRemoteId,complete:false,error:matches.length===1&&matches[0].error?matches[0].error:{code:'INCOMPLETE_READ',message:'远端响应缺失、重复或身份不匹配'}};return matches[0];});
    }
    const result = [];
    for (const object of objects) {
      try { const read=await client.readObject(object, {signal});if(!readMatches(object,read))throw fail('远端响应身份不匹配');result.push(read); }
      catch (error) { result.push({externalObjectId: object.id,remoteId:object.remoteId,remoteKind:object.remoteKind,parentRemoteId:object.parentRemoteId, complete: false, error: safeError(error)}); }
      this.update(id, value => { value.status.processed = result.length; });
    }
    return result;
  }
  async refreshTargets(id,targetIds){
    const state=this.assertWorkspace(id),requested=new Set(targetIds.filter(Boolean));
    if(!requested.size)return {read:0};
    for(const row of state.deliverables.filter(r=>requested.has(r.id)))for(const nodeId of row.flowNodeIds||[])requested.add(nodeId);
    const objects=this.objects(state).filter(object=>requested.has(object.localObjectId));
    if(!objects.length)throw fail('执行前尚未核实目标的飞书读取映射',409);
    if(this.jobs.has(id))await this.jobs.get(id).promise;
    let failure;
    await this.queue(id,'checking',async signal=>{
      try{const reads=await this.read(id,objects,signal);if(reads.some(read=>read.complete===false||read.error))throw fail('执行前目标字段或节点关系尚未完整读回',409);const merged=this.merge(id,reads);if(merged.inaccessible?.length)throw fail('执行前仍有目标读取缺口',409);}
      catch(error){failure=error;throw error;}
    });
    if(failure)throw failure;return {read:objects.length};
  }
  merge(id, reads) {
    return this.store.transaction(() => {
      const state = this.store.load(id), result = this.domain.mergeFeishuRead(state, reads, {now: this.clock()});
      const errors = this.domain.validateState(result.state);
      if (errors.length) throw fail('入站更新未通过工作台数据校验：' + errors.slice(0, 3).map(row => row.message).join('；'));
      this.store.validateAttachments(result.state);
      if (result.state.revision !== state.revision) this.store.save(result.state, state.revision);
      const value = this.control(id), ids = new Set(reads.map(row => row.externalObjectId)),successful=new Set(reads.filter(read=>readMatches(state.externalObjects.find(row=>row.id===read.externalObjectId),read)).map(row=>row.externalObjectId));
      value.conflicts = [...new Map([...value.conflicts.filter(row => !successful.has(row.externalObjectId)), ...result.conflicts].map(row=>[row.id,row])).values()];
      value.inaccessible = [...value.inaccessible.filter(row => !ids.has(row.externalObjectId)), ...result.inaccessible];
      this.save(id, value);
      return result;
    });
  }
  async poll(id, {wait = false} = {}) {
    const state = this.assertWorkspace(id), objects = this.objects(state);
    if (!objects.length) throw fail('没有可读取的已关联飞书对象');
    const promise = this.queue(id, 'polling', async signal => {
      const control=this.control(id),client=this.client(id);let selected=objects,index=[];
      const historicalMissing=issue=>{const object=objects.find(o=>o.id===issue.externalObjectId),project=object&&objects.find(o=>o.remoteKind==='project'&&o.remoteId===object.parentRemoteId&&o.spaceKey===object.spaceKey);return object?.remoteKind==='node'&&state.riskPolicy?.historicalProjectIds?.includes(project?.localObjectId)&&String(issue.reason||'').includes('未找到已登记的飞书节点');};
      const deferredIds=new Set(control.inaccessible.filter(historicalMissing).map(i=>i.externalObjectId));
      this.update(id,v=>{v.status.lastImported=0;});
      const full=control.status.readPolicyVersion!==2||!control.status.lastFullReadAt||Date.parse(this.clock())-Date.parse(control.status.lastFullReadAt)>15*60*1000;
      if(client.discover)try{
        for(const spaceKey of [...new Set(objects.map(o=>o.spaceKey))]){
          const workItemTypes=[...new Map(objects.filter(o=>o.spaceKey===spaceKey&&o.remoteKind!=='node'&&o.raw?.workItemType).map(o=>[o.raw.workItemType,{key:o.raw.workItemType,remoteKind:o.remoteKind}])).values()];
          const result=await client.discover({spaceKey,workItemTypes,includeUpdated:true},{signal});
          if(result.complete===false)throw fail('增量索引读取不完整');index.push(...(Array.isArray(result)?result:result.objects||[]));
        }
        const stamp=o=>String(o.updatedAt??''),key=o=>[o.spaceKey,o.remoteKind,o.remoteId].join(':');
        const changed=new Set(index.filter(o=>!stamp(o)||control.indexHeads?.[key(o)]!==stamp(o)).map(key));
        if(!full){const changedProjects=new Set(objects.filter(o=>o.remoteKind==='project'&&changed.has(key(o))).map(o=>o.spaceKey+':'+o.remoteId));selected=objects.filter(o=>o.remoteKind==='node'?(changedProjects.has(o.spaceKey+':'+o.parentRemoteId)||o.verificationStatus!=='verified'&&!deferredIds.has(o.id)):o.verificationStatus==='inaccessible'||changed.has(key(o))||!index.some(i=>key(i)===key(o)));}
        this.update(id,v=>{v.discoveries=index.filter(o=>!objects.some(e=>key(e)===key(o)));v.status.lastDiscoveryAt=this.clock();v.status.discoveryError=null;});
      }catch(error){selected=objects;this.update(id,v=>{v.status.discoveryError=safeError(error);});}
      const reads = selected.length?await this.read(id, selected, signal):[];
      if (signal.aborted) throw fail('同步已中止');
      const merged = this.merge(id, reads);
      this.update(id, value => {
        value.status.processed = reads.length; value.status.total = selected.length; value.status.registeredCount=objects.length;value.status.skippedUnchanged=objects.length-selected.length;value.status.lastChanges = merged.changes;value.status.lastCompletedAt=this.clock();value.status.readableCount=reads.filter(row=>row.complete===true).length;
        value.status.lastReadAt=this.clock();if(merged.changes)value.status.lastAppliedAt=this.clock();if(full){value.status.lastFullReadAt=this.clock();value.status.readPolicyVersion=2;}
        value.indexHeads||={};for(const row of index){const original=objects.find(o=>o.spaceKey===row.spaceKey&&o.remoteKind===row.remoteKind&&o.remoteId===row.remoteId);if(original&&reads.some(r=>readMatches(original,r))&&row.updatedAt)value.indexHeads[[row.spaceKey,row.remoteKind,row.remoteId].join(':')]=String(row.updatedAt);}
        const currentIssues=merged.inaccessible.filter(issue=>!historicalMissing(issue));value.status.historicalNodeGaps=value.inaccessible.filter(historicalMissing).length;
        if (currentIssues.length||(value.readWarnings||[]).length) { value.status.phase = 'error'; value.status.lastError = {code: 'PARTIAL_READ', message: `${currentIssues.length+(value.readWarnings||[]).length} 项读取不完整，已保留旧值；其余可读对象已更新`, retryable: true}; value.status.consecutiveFailures=value.status.readableCount||value.status.skippedUnchanged&&index.length?0:(value.status.consecutiveFailures||0)+1; }
        else { value.status.lastSucceededAt = this.clock(); value.status.consecutiveFailures = 0; }
      });
      await this.importNewDeliverables(id,signal);
      if (this.client(id).discover && !signal.aborted && !index.length) {
        const current = this.store.load(id), latest = this.control(id);
        if (!latest.status.lastDiscoveryAt || Date.parse(this.clock()) - Date.parse(latest.status.lastDiscoveryAt) > 15 * 60 * 1000) {
          const found = [];
          for (const spaceKey of [...new Set(objects.map(row => row.spaceKey))]) {
            const typeRows = objects.filter(row => row.spaceKey === spaceKey && row.remoteKind !== 'node');
            const workItemTypes = [...new Map(typeRows.filter(row=>row.raw?.workItemType).map(row=>[row.raw.workItemType,{key:row.raw.workItemType,remoteKind:row.remoteKind}])).values()];
            if (!workItemTypes.length) continue;
            try { const result = await this.client(id).discover({spaceKey, workItemTypes}, {signal}); found.push(...(Array.isArray(result) ? result : result.objects || result.items || [])); }
            catch (error) { this.update(id, value => { value.status.discoveryError = safeError(error); }); }
          }
          const known = new Set(current.externalObjects.map(row => `${row.spaceKey}:${row.remoteId}`));
          this.update(id, value => { value.discoveries = [...value.discoveries.filter(row=>row.remoteKind==='node'),...found.filter(row => !known.has(`${row.spaceKey}:${row.remoteId}`))]; value.status.lastDiscoveryAt = this.clock(); });
        }
      }
    });
    if (wait) await promise;
    return this.status(id);
  }
  async importNewDeliverables(id,signal){
    this.store.transaction(()=>{const before=this.store.load(id),next=importDiscoveredNodes(before,this.control(id).discoveries,this.domain,this.clock());if(next.count){const errors=this.domain.validateState(next.state);if(errors.length)throw fail('新节点接入校验失败：'+errors[0].message);this.store.save(next.state,before.revision);}});
    const state=this.store.load(id),c=this.control(id),projects=this.objects(state).filter(o=>o.remoteKind==='project');
    const candidates=c.discoveries.filter(o=>o.remoteKind==='deliverable'&&o.projectRemoteIds?.length===1&&projects.some(p=>p.spaceKey===o.spaceKey&&p.remoteId===o.projectRemoteIds[0])).slice(0,60);
    if(!candidates.length)return;
    const objects=candidates.map(o=>{const parent=projects.find(p=>p.spaceKey===o.spaceKey&&p.remoteId===o.projectRemoteIds[0]);return {...o,id:'candidate-'+digest([o.spaceKey,o.remoteId]).slice(0,32),parentRemoteId:parent.remoteId,parentNodeRemoteId:'',parentDeliverableRemoteId:'',collectedAt:'',raw:o.raw};});
    const client=this.client(id);if(!client.readObjects)return;const result=await client.readObjects(objects,{signal,includeComments:false});
    const reads=Array.isArray(result)?result:result.reads||[];
    this.store.transaction(()=>{const before=this.store.load(id),next=importDiscoveredDeliverables(before,reads.filter(r=>{const o=objects.find(o=>o.id===r.externalObjectId);return o&&readMatches(o,r);}),this.domain,this.clock());const errors=this.domain.validateState(next.state);if(errors.length)throw fail('新交付物接入校验失败：'+errors.slice(0,3).map(e=>e.message).join('；'));if(next.imported.length)this.store.save(next.state,before.revision);const v=this.control(id);v.status.lastImported=next.imported.length;v.status.totalImported=(v.status.totalImported||0)+next.imported.length;v.status.importIssues=next.skipped;v.discoveries=v.discoveries.filter(d=>!next.imported.some(i=>i.remoteId===d.remoteId));this.save(id,v);});
  }
  candidates(state) {
    const results = [];
    for (const object of this.objects(state)) {
      if (object.remoteKind === 'node') continue;
      const local = localFor(state, object), baseline = state.syncBaselines.find(row => row.externalObjectId === object.id);
      if (!baseline) continue;
      for (const rule of state.mappingRules.filter(row => row.system === object.system && row.remoteKind === object.remoteKind && row.status === 'active')) {
        if (!rule.writable || allowedPairs.get(rule.remoteFieldKey) !== rule.localField || !Object.hasOwn(baseline.localValues, rule.localField)) continue;
        const proposed = local[rule.localField] ?? '';
        if (typeof proposed !== 'string' || equal(proposed, baseline.localValues[rule.localField] ?? '')) continue;
        if (pendingField(state, local.id, rule.localField)) continue;
        results.push({externalObjectId: object.id, localObjectId: local.id, localKind: kindFor(object), localField: rule.localField, objectTitle: local.title, remoteId: object.remoteId, remoteKind: object.remoteKind, spaceKey: object.spaceKey, remoteFieldKey: rule.remoteFieldKey, fieldName: rule.remoteFieldName || rule.localField, baselineRemote: clone(baseline.remoteValues[rule.remoteFieldKey] ?? null), proposed, target: identity(object), ruleId: rule.id});
      }
    }
    return results;
  }
  async prepare(id, {requestId, wait = false} = {}) {
    this.assertWorkspace(id);
    if (typeof requestId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(requestId)) throw fail('需要有效的请求标识');
    if (Object.hasOwn(this.control(id).requests,requestId)) return this.status(id);
    const candidates = this.candidates(this.store.load(id));
    if (!candidates.length) throw fail('没有可写回的文本差异；请先保存本地修改。未接受草稿、状态、验收、人员和附件不在自动写回范围。');
    const objects = this.objects(this.store.load(id)).filter(row => candidates.some(patch => patch.externalObjectId === row.id));
    const promise = this.queue(id, 'preparing', async signal => {
      const reads = await this.read(id, objects, signal);
      const byId = new Map(reads.filter(row => row.complete === true).map(row => [row.externalObjectId, row]));
      const state = this.store.load(id), patches = [], problems = [];
      for (const patch of this.candidates(state).filter(row => objects.some(object => object.id === row.externalObjectId))) {
        const read = byId.get(patch.externalObjectId);
        if (!read || !Object.hasOwn(read.fields, patch.remoteFieldKey)) { problems.push(`${patch.objectTitle}：字段未完整读取`); continue; }
        const before = read.fields[patch.remoteFieldKey];
        if (before !== null && typeof before !== 'string') { problems.push(`${patch.objectTitle}：字段不是可直接写回的文本`); continue; }
        if (equal(before ?? '', patch.proposed)) continue;
        if (!equal(before ?? '', patch.baselineRemote ?? '')) { problems.push(`${patch.objectTitle}：飞书字段已变化，请解决冲突后重新生成差异`); continue; }
        patches.push({...patch, before: clone(before)});
      }
      this.merge(id, reads);
      if (!patches.length && !problems.length) throw fail('飞书已包含当前文本，无需重复写回');
      const run = {id: 'feishu-' + randomUUID(), workspaceId: id, status: problems.length ? 'conflict' : 'pending_review', createdAt: this.clock(), patches, fingerprint: digest({workspaceId: id, patches}), error: problems.join('；'), approvedBy: '', approvedAt: '', receipts: []};
      this.update(id, value => { value.runs.push(run); value.requests[requestId] = run.id; });
    });
    if (wait) await promise;
    return this.status(id);
  }
  verifyLocal(state, run) {
    if (run.fingerprint !== digest({workspaceId: state.workspaceId, patches: run.patches})) throw fail('待审内容校验失败，请重新生成差异', 409);
    for (const patch of run.patches) {
      const object = state.externalObjects.find(row => row.id === patch.externalObjectId);
      const rule = state.mappingRules.find(row => row.id === patch.ruleId);
      if (!object || !equal(identity(object), patch.target) || !localFor(state, object) || localFor(state, object).archived) throw fail('对象关联已变化，请重新生成差异', 409);
      if (!rule || rule.status !== 'active' || !rule.writable || rule.remoteFieldKey !== patch.remoteFieldKey || rule.localField !== patch.localField || allowedPairs.get(patch.remoteFieldKey) !== patch.localField) throw fail('字段映射已变化或不允许写回', 409);
      if (!equal(localFor(state, object)[patch.localField] ?? '', patch.proposed) || pendingField(state, patch.localObjectId, patch.localField)) throw fail('本地内容已改变或存在待审草稿，请重新生成差异', 409);
    }
  }
  async approve(id, {runId, fingerprint, confirmed, approvedBy = '本人', requestId, wait = false}) {
    this.assertWorkspace(id);
    if (typeof requestId!=='string'||!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(requestId)) throw fail('批准请求缺少有效标识');
    if (confirmed !== true || typeof approvedBy !== 'string' || !approvedBy.trim() || approvedBy.length > 100) throw fail('请先逐项核对差异，并确认批准本次飞书写入');
    const value = this.control(id), run = value.runs.find(row => row.id === runId);
    if (!run || run.workspaceId !== id || run.fingerprint !== fingerprint) throw fail('审核内容已变化或不属于此工作区', 409);
    if (run.status !== 'pending_review') { if (run.approvalRequestId === requestId && run.approvedAt) return this.status(id); throw fail('当前变更不能批准，请重新生成差异', 409); }
    if (this.jobs.has(id)) throw fail('请等待当前同步任务完成后再批准', 409);
    this.verifyLocal(this.store.load(id), run);
    this.update(id, control => { const target = control.runs.find(row => row.id === runId); target.status = 'approved'; target.approvedBy = approvedBy.trim(); target.approvedAt = this.clock(); target.approvalRequestId = requestId; });
    return this.execute(id, runId, {wait});
  }
  reject(id, runId) {
    if (this.jobs.has(id)) throw fail('请等待当前同步任务完成', 409);
    this.update(id, value => { const run = value.runs.find(row => row.id === runId); if (!run || !['pending_review', 'conflict', 'stale', 'failed'].includes(run.status)) throw fail('当前记录不能退回', 409); run.status = 'rejected'; run.rejectedAt = this.clock(); });
    return this.status(id);
  }
  async execute(id, runId, {wait = false} = {}) {
    const initial = this.control(id).runs.find(row => row.id === runId);
    if (!initial || initial.status !== 'approved' || !initial.approvedAt || !initial.approvedBy) throw fail('当前差异尚未获批，禁止写入', 403);
    const promise = this.queue(id, 'writing', async signal => {
      let attempted = false;
      try {
        const run = clone(this.control(id).runs.find(row => row.id === runId));
        this.verifyLocal(this.store.load(id), run);
        const objects = this.objects(this.store.load(id)).filter(row => run.patches.some(patch => patch.externalObjectId === row.id));
        const reads = await this.read(id, objects, signal), byId = new Map(reads.filter(row => row.complete === true).map(row => [row.externalObjectId, row]));
        for (const patch of run.patches) {
          const read = byId.get(patch.externalObjectId);
          if (!read || !Object.hasOwn(read.fields, patch.remoteFieldKey) || !equal(read.fields[patch.remoteFieldKey], patch.before)) throw fail('审核后飞书数据已变化或无法完整读取，已停止写回，请重新核对', 409);
        }
        this.update(id, value => { value.runs.find(row => row.id === runId).status = 'sending'; });
        for (const object of objects) {
          if (signal.aborted) throw fail('执行中断，需核对远端结果');
          this.verifyLocal(this.store.load(id), run);
          const patches = run.patches.filter(patch => patch.externalObjectId === object.id);
          const receipt = {externalObjectId: object.id, remoteId: object.remoteId, startedAt: this.clock(), status: 'sending', readback: null};
          this.update(id, value => { value.runs.find(row => row.id === runId).receipts.push(receipt); });
          attempted = true;
          let writeError;
          try { await this.client(id).writeFields(object, patches, {signal,beforeWrite:()=>{if(signal.aborted)throw fail('执行已中止');const current=this.control(id).runs.find(row=>row.id===runId);if(!current||current.status!=='sending'||current.fingerprint!==run.fingerprint)throw fail('批准记录已失效',409);this.verifyLocal(this.store.load(id),run);}}); }
          catch (error) { writeError = safeError(error); }
          let readback;
          try { readback = await this.client(id).readObject(object, {signal}); }
          catch (error) { if (!writeError) writeError = safeError(error); }
          const verified = readMatches(object,readback) && patches.every(patch => Object.hasOwn(readback.fields, patch.remoteFieldKey) && equal(readback.fields[patch.remoteFieldKey] ?? '', patch.proposed));
          if (readback) this.merge(id, [readback]);
          this.update(id, value => { const target = value.runs.find(row => row.id === runId).receipts.find(row => row.externalObjectId === object.id); Object.assign(target, {status: verified ? 'readback_verified' : 'needs_reconcile', verifiedAt: verified ? this.clock() : '', readback: readback ? Object.fromEntries(patches.map(patch => [patch.remoteFieldKey, readback.fields?.[patch.remoteFieldKey] ?? null])) : null, error: writeError}); });
          if (!verified) throw fail('远端执行结果尚未核实；已停止后续写入，请先核对结果');
        }
        this.update(id, value => { const run = value.runs.find(row => row.id === runId); run.status = 'readback_verified'; run.verifiedAt = this.clock(); run.error = ''; value.status.consecutiveFailures = 0; });
      } catch (error) {
        this.update(id, value => { const run = value.runs.find(row => row.id === runId); run.status = attempted ? (run.receipts.some(row => row.status === 'readback_verified') ? 'partial' : 'needs_reconcile') : 'conflict'; run.error = safeError(error).message; });
        throw error;
      }
    });
    if (wait) await promise;
    return this.status(id);
  }
  async reconcile(id, runId, {wait = false} = {}) {
    this.assertWorkspace(id);
    const run = this.control(id).runs.find(row => row.id === runId);
    if (!run || !['needs_reconcile', 'partial', 'failed'].includes(run.status)) throw fail('当前记录无需核对');
    const promise = this.queue(id, 'reconciling', async signal => {
      const objects = this.objects(this.store.load(id)).filter(row => run.patches.some(patch => patch.externalObjectId === row.id));
      if(run.patches.some(patch=>!objects.some(object=>object.id===patch.externalObjectId&&equal(identity(object),patch.target))))throw fail('对象关联在执行后已改变，不能用新对象确认原写回；请核对原飞书目标',409);
      const reads = await this.read(id, objects, signal), byId = new Map(reads.filter(row => row.complete === true).map(row => [row.externalObjectId, row]));
      const verified = run.patches.every(patch => byId.has(patch.externalObjectId) && Object.hasOwn(byId.get(patch.externalObjectId).fields, patch.remoteFieldKey) && equal(byId.get(patch.externalObjectId).fields[patch.remoteFieldKey] ?? '', patch.proposed));
      this.merge(id, reads);
      this.update(id, value => { const target = value.runs.find(row => row.id === runId); target.status = verified ? 'readback_verified' : 'needs_reconcile'; target.verifiedAt = verified ? this.clock() : ''; target.lastReconciledAt = this.clock(); target.error = verified ? '' : '远端尚未与获批内容一致；没有重发，请查看飞书并重新生成差异。';
        for(const object of objects){const patches=run.patches.filter(row=>row.externalObjectId===object.id),read=byId.get(object.id),ok=readMatches(object,read)&&patches.every(patch=>Object.hasOwn(read.fields,patch.remoteFieldKey)&&equal(read.fields[patch.remoteFieldKey]??'',patch.proposed));let receipt=target.receipts.find(row=>row.externalObjectId===object.id);if(!receipt){receipt={externalObjectId:object.id,remoteId:object.remoteId};target.receipts.push(receipt);}Object.assign(receipt,{status:ok?'readback_verified':'needs_reconcile',verifiedAt:ok?this.clock():'',reconciledAt:this.clock(),readback:read?Object.fromEntries(patches.map(patch=>[patch.remoteFieldKey,read.fields?.[patch.remoteFieldKey]??null])):null});}
      });
    });
    if (wait) await promise;
    return this.status(id);
  }
  async resolve(id,{conflictId,choice,fingerprint,wait=false}) {
    this.assertWorkspace(id);
    if(!['remote','local'].includes(choice))throw fail('请选择采用飞书值或保留本地值');
    const conflict=this.control(id).conflicts.find(row=>row.id===conflictId);
    if(!conflict||digest(conflict)!==fingerprint)throw fail('冲突内容已变化，请刷新后再选择',409);
    const object=this.objects(this.store.load(id)).find(row=>row.id===conflict.externalObjectId);
    if(!object)throw fail('对象关联已变化',409);
    const promise=this.queue(id,'preparing',async signal=>{
      const reads=await this.read(id,[object],signal);
      if(reads.length!==1||!readMatches(object,reads[0])||!Object.hasOwn(reads[0].fields,conflict.remoteFieldKey)||!equal(reads[0].fields[conflict.remoteFieldKey],conflict.remoteValue)){this.merge(id,reads);throw fail('飞书值已变化或无法读取，已刷新冲突，请重新核对',409);}
      this.merge(id,reads);
      this.store.transaction(()=>{const current=this.store.load(id),next=this.domain.resolveFeishuConflict(current,conflict,choice,{now:this.clock()});const errors=this.domain.validateState(next);if(errors.length)throw fail('冲突解决未通过数据校验');this.store.validateAttachments(next);this.store.save(next,current.revision);const value=this.control(id);value.conflicts=value.conflicts.filter(row=>row.id!==conflictId);this.save(id,value);});
    });
    if(wait)await promise;
    return this.status(id);
  }
  async withSuspended(task) { this.suspended=true; try { for(const job of this.jobs.values())job.controller.abort(); await Promise.allSettled([...this.jobs.values()].map(job=>job.promise)); return await task(); } finally { this.suspended=false; } }
  async close() { this.closed = true; clearInterval(this.timer); for (const job of this.jobs.values()) job.controller.abort(); await Promise.allSettled([...this.jobs.values()].map(job => job.promise)); }
}
