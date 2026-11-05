import { normalizeAmSnapshot, buildBootstrap, buildProjectSummary } from '../core/index.mjs';
import { digest } from './canonical.mjs';
import { LedgerError } from './errors.mjs';

const TRANSIENT=new Set(['offline','AM_OFFLINE','source_unavailable','snapshot_unavailable','rpc_pending','rpc_expired',
  'ETIMEDOUT','ECONNRESET','ECONNREFUSED','EHOSTUNREACH','ENETUNREACH']);
function retained(entry) {
  const snapshot=structuredClone(entry.snapshot);
  snapshot.coverage={...snapshot.coverage,status:'stale',reasons:[...new Set([
    ...snapshot.coverage.reasons,'最新资料暂时未能读取，当前保留上次有效信息'
  ])]};
  delete snapshot.projectCoverage;
  return {snapshot,bootstrap:buildBootstrap(snapshot),summaryCache:new Map(snapshot.projects.map(p=>[
    p.id,{summary:buildProjectSummary(snapshot,p.id),fingerprint:''}
  ])),expiresAt:0};
}

export function authorizationKey(session) {
  return digest({sessionId:session.id,tenantId:session.tenantId,userId:session.userId,workspaceId:session.workspaceId,
    projectIds:[...session.projectIds].sort(),scopes:[...session.scopes].sort()});
}

export function scopeSnapshot(raw, session) {
  if ((raw.viewerId && raw.viewerId !== session.userId) || (raw.workspaceId && raw.workspaceId !== session.workspaceId)) {
    throw new LedgerError('snapshot_identity_mismatch', '项目资料与当前工作区不一致。', 403);
  }
  const normalized = normalizeAmSnapshot({...raw, workspaceId:session.workspaceId,viewerId:session.userId});
  const allowed = new Set(session.projectIds);
  const projects = normalized.projects.filter(p => allowed.has('*') || allowed.has(p.id));
  const projectIds = new Set(projects.map(p=>p.id));
  const items = normalized.items.filter(i=>i.projectId && projectIds.has(i.projectId));
  const itemIds = new Set(items.map(i=>i.id));
  const facts = normalized.facts.filter(f=>projectIds.has(f.projectId) && (!f.itemId || itemIds.has(f.itemId)));
  const factIds = new Set(facts.map(f=>f.id));
  const reviews = normalized.reviews.filter(r=>!r.projectId || projectIds.has(r.projectId)).map(r=>({...r,
    choices:(r.choices||[]).filter(c=>!c.value?.projectId || projectIds.has(c.value.projectId)),
    factIds:(r.factIds||[]).filter(id=>factIds.has(id)),
  }));
  const coverage={...normalized.coverage,...(normalized.coverage?.processingGaps?{
    processingGaps:normalized.coverage.processingGaps.filter(g=>g.projectIds?.some(id=>projectIds.has(id)))}:{})};
  return {...normalized,projects,items,facts,reviews,coverage,
    ...(normalized.projectCoverage?{projectCoverage:Object.fromEntries(Object.entries(normalized.projectCoverage).filter(([id])=>projectIds.has(id)))}:{}),
    reminders:normalized.reminders.filter(r=>projectIds.has(r.projectId) && itemIds.has(r.itemId))};
}

/** Cached read model only. The AM/WB stores remain the business authority. */
export class ProjectionCache {
  constructor(bridge, {clock=Date.now, ttlMs=10000} = {}) {
    this.bridge=bridge;this.clock=clock;this.ttlMs=ttlMs;
    this.entries=new Map();this.inflight=new Map();this.generations=new Map();this.pendingSnapshots=new Map();this.sequences=new Map();
  }
  invalidate(session) {
    const key=authorizationKey(session);
    this.generations.set(key,(this.generations.get(key)||0)+1);
    this.pendingSnapshots.delete(key);
    if(this.entries.has(key))this.entries.get(key).expiresAt=0;
  }
  accept(raw,session,context={}) {
    const key=authorizationKey(session),snapshot=scopeSnapshot(raw,session),previous=this.entries.get(key);
    const generation=this.generations.get(key)||0;
    const capturedAt=Number.isSafeInteger(raw.capturedAtMs)?raw.capturedAtMs:Date.parse(raw.generatedAt||snapshot.generatedAt);
    if((context.cacheGeneration!==undefined&&context.cacheGeneration!==generation) ||
       (context.cacheSequence!==undefined&&previous?.cacheSequence>context.cacheSequence) ||
       (Number.isFinite(capturedAt)&&Number.isFinite(previous?.capturedAt)&&capturedAt<previous.capturedAt)) {
      throw new LedgerError('stale_snapshot_result','这次资料读取已被更新的结果替代，请读取当前项目。',409);
    }
    const summaryCache=new Map();
    for(const project of snapshot.projects) {
      const fingerprint=digest({project,items:snapshot.items.filter(i=>i.projectId===project.id),
        facts:snapshot.facts.filter(f=>f.projectId===project.id),reviews:snapshot.reviews.filter(r=>r.projectId===project.id),
        reminders:snapshot.reminders.filter(r=>r.projectId===project.id),coverage:snapshot.projectCoverage?.[project.id]??snapshot.coverage});
      const old=previous?.summaryCache.get(project.id);
      const summary=old?.fingerprint===fingerprint ? {...old.summary,generatedAt:snapshot.generatedAt} : buildProjectSummary(snapshot,project.id);
      summaryCache.set(project.id,{fingerprint,summary});
    }
    const entry={snapshot,summaryCache,bootstrap:buildBootstrap(snapshot),capturedAt,cacheSequence:context.cacheSequence??previous?.cacheSequence??0,
      expiresAt:Math.min(this.clock()+this.ttlMs,
      Number.isSafeInteger(raw.expiresAtMs)?raw.expiresAtMs:Number.MAX_SAFE_INTEGER)};
    this.entries.set(key,entry);return entry;
  }
  async get(session, {fresh=false, context={route:'bootstrap'}, allowStale=true}={}) {
    const key=authorizationKey(session),old=this.entries.get(key);
    if(!fresh && old && old.expiresAt>this.clock())return old;
    const saved=this.pendingSnapshots.get(key);
    if(saved) {
      let outcome;
      try{outcome=await this.bridge.peek(saved.requestId,session);}catch(error){
        if(['snapshot_expired','WEB_SNAPSHOT_EXPIRED','unknown_request'].includes(error.code))this.pendingSnapshots.delete(key);
        else {if(!TRANSIENT.has(error.code)){this.entries.delete(key);this.pendingSnapshots.delete(key);}throw error;}
      }
      if(outcome){
      if(outcome.state==='complete') {this.pendingSnapshots.delete(key);return this.accept(outcome.data,session,outcome.context??saved.context);}
      if(outcome.expired)this.pendingSnapshots.delete(key);
      else {
        if(allowStale&&old)return retained(old);
        if(context.route!=='internal-read')throw new LedgerError('rpc_pending','最新资料正在读取。',202,
          {requestId:saved.requestId,pollUrl:'/api/v2/ledger/operations/'+saved.requestId});
        throw new LedgerError('source_refresh_pending','最新项目资料仍在读取；本次操作尚未提交，请稍后刷新后继续。',409,
          {snapshotRequestId:saved.requestId});
      }
      }
    }
    // Keep an operation's response projection bound to its original route.
    const operationKey=key+':'+digest(context);
    if(this.inflight.has(operationKey))return this.inflight.get(operationKey);
    const generation=this.generations.get(key)||0;
    const sequence=(this.sequences.get(key)||0)+1;this.sequences.set(key,sequence);
    const rpcContext={...context,cacheGeneration:generation,cacheSequence:sequence};
    const pending=(async()=>{
      try {
        const raw=await this.bridge.call('snapshot',{},session,{context:rpcContext});
        if((this.generations.get(key)||0)!==generation) {
          throw new LedgerError('snapshot_changed', '处理期间项目资料已有更新，请重新读取。',409);
        }
        return this.accept(raw,session,rpcContext);
      }catch(error) {
        if(error.code==='rpc_pending')this.pendingSnapshots.set(key,{requestId:error.details.requestId,context:rpcContext});
        if(allowStale && old && TRANSIENT.has(error.code))return retained(old);
        if(!TRANSIENT.has(error.code)&&!['stale_snapshot_result','snapshot_changed'].includes(error.code)){
          this.entries.delete(key);this.pendingSnapshots.delete(key);
        }
        if(error.code==='rpc_pending'&&context.route==='internal-read')throw new LedgerError('source_refresh_pending',
          '最新项目资料仍在读取；本次操作尚未提交，请稍后刷新后继续。',409,{snapshotRequestId:error.details.requestId});
        throw error;
      }
    })();
    this.inflight.set(operationKey,pending);
    try{return await pending;}finally{this.inflight.delete(operationKey);}
  }
}
