import { createHash, randomUUID } from 'node:crypto';

export const assistantError = (message, status = 422) => Object.assign(new Error(message), { status });
export const assistantHash = value => createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex');
export const assistantId = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value);
const objectKinds = ['sources', 'projects', 'cases', 'flowNodes', 'deliverables', 'actions', 'milestones', 'risks', 'decisions'];

export function validateAssistantBundle(bundle, expectedWorkspaceId = bundle?.workspaceId) {
  if (bundle?.schemaVersion !== 1 || bundle.workspaceId !== expectedWorkspaceId || !assistantId(bundle.workspaceId) || !Array.isArray(bundle.sessions) || !Array.isArray(bundle.jobs) || bundle.jobs.length > 10000 || bundle.sessions.length > 10000) throw assistantError('助手备份格式无效');
  const sessions = new Map(), jobs = new Map(), requests = new Set(), latestBySession = new Map();
  for (const session of bundle.sessions) {
    if (session?.schemaVersion !== 1 || session.workspaceId !== bundle.workspaceId || !assistantId(session.id) || sessions.has(session.id) || !['workspace', ...objectKinds].includes(session.contextRef?.kind) || !assistantId(session.contextRef?.id)) throw assistantError('助手备份会话范围无效');
    if (session.contextRef.kind === 'workspace' && session.contextRef.id !== bundle.workspaceId) throw assistantError('助手备份会话指向其他工作区');
    sessions.set(session.id, session);
  }
  for (const entry of bundle.jobs) {
    const j = entry?.job;
    if (!j || j.workspaceId !== bundle.workspaceId || !assistantId(j.id) || jobs.has(j.id) || j.sessionId && !sessions.has(j.sessionId) || typeof j.text !== 'string' || j.text.length > 20000 || !['answer', 'draft'].includes(j.mode) || !['running', 'completed', 'failed', 'cancelled', 'interrupted'].includes(j.status)) throw assistantError('助手备份任务范围无效');
    if (!assistantId(entry.requestId) || requests.has(entry.requestId) || typeof entry.fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(entry.fingerprint) || !Array.isArray(j.events) || !Array.isArray(j.warnings)) throw assistantError('助手备份请求记录或任务历史无效');
    requests.add(entry.requestId);
    if (j.sessionId) {
      const session = sessions.get(j.sessionId);
      if (j.contextRef?.kind !== session.contextRef.kind || j.contextRef?.id !== session.contextRef.id || (j.projectId || '') !== (session.projectId || '') || (j.parentJobId || '') !== (latestBySession.get(j.sessionId) || '')) throw assistantError('助手备份的上下文或会话顺序无效');
      latestBySession.set(j.sessionId, j.id);
    }
    jobs.set(j.id, j);
  }
  for (const job of jobs.values()) if (job.parentJobId && (!jobs.has(job.parentJobId) || jobs.get(job.parentJobId).sessionId !== job.sessionId)) throw assistantError('助手备份存在跨会话或缺失的上轮引用');
  for (const session of sessions.values()) if ((session.lastJobId || '') !== (latestBySession.get(session.id) || '')) throw assistantError('助手备份的会话末轮无效');
  return bundle;
}

export function assistantScope(state, input) {
  const ref = input.contextRef || (input.projectId ? { kind: 'projects', id: input.projectId } : { kind: 'workspace', id: state.workspaceId });
  if (!ref || !assistantId(ref.id) || !['workspace', ...objectKinds].includes(ref.kind)) throw assistantError('对话对象范围无效');
  const row = ref.kind === 'workspace' ? null : state[ref.kind]?.find(row => row.id === ref.id && !row.archived);
  if (ref.kind === 'workspace' ? ref.id !== state.workspaceId : !row || ref.kind === 'sources' && (!row.workItem || row.workItem.mergedIntoId)) throw assistantError('当前工作区没有此对话对象', 404);
  const projects = ref.kind === 'projects' ? [ref.id] : row?.projectIds || [];
  if (input.projectId && (!state.projects.some(p => p.id === input.projectId && !p.archived) || row && !projects.includes(input.projectId))) throw assistantError('项目与对话对象范围不一致', 409);
  return { contextRef: { kind: ref.kind, id: ref.id }, projectId: ref.kind === 'sources' ? '' : input.projectId || (projects.length === 1 ? projects[0] : '') };
}

/** Auxiliary conversation history in the existing SQLite DB; no business ledger. */
export class AssistantSessions {
  constructor(store) {
    this.store = store;
    store.db.exec('CREATE TABLE IF NOT EXISTS assistant_sessions (workspace_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(workspace_id,id))');
  }
  get(workspaceId, id) {
    this.store.load(workspaceId);
    const row = this.store.db.prepare('SELECT payload FROM assistant_sessions WHERE workspace_id=? AND id=?').get(workspaceId, id);
    return row ? JSON.parse(row.payload) : null;
  }
  list(workspaceId) {
    this.store.load(workspaceId);
    return this.store.db.prepare('SELECT payload FROM assistant_sessions WHERE workspace_id=? ORDER BY rowid DESC').all(workspaceId).map(r => JSON.parse(r.payload));
  }
  jobs(workspaceId, sessionId) {
    this.store.load(workspaceId);
    return this.store.db.prepare('SELECT payload FROM assistant_jobs WHERE workspace_id=? ORDER BY rowid').all(workspaceId).map(r => JSON.parse(r.payload)).filter(j => j.sessionId === sessionId);
  }
  assertNext(input, scope) {
    if (!assistantId(input.sessionId) || typeof input.parentJobId !== 'string' || input.parentJobId && !assistantId(input.parentJobId)) throw assistantError('连续对话需要会话标识及上一轮标识');
    const session = this.get(input.workspaceId, input.sessionId);
    if (session && (JSON.stringify(session.contextRef) !== JSON.stringify(scope.contextRef) || session.projectId !== scope.projectId)) throw assistantError('会话已绑定另一项目或事项，请使用新会话', 409);
    if ((session?.lastJobId || '') !== input.parentJobId) throw assistantError('对话已新增一轮，请刷新后继续，避免覆盖并发提问', 409);
    const last = session?.lastJobId ? this.jobs(input.workspaceId, input.sessionId).find(j => j.id === session.lastJobId) : null;
    if (last?.status === 'running') throw assistantError('同一对话仍在处理上一轮，可等待或取消', 409);
    if (input.retryOf && (!last || last.id !== input.retryOf || !['failed', 'cancelled', 'interrupted'].includes(last.status))) throw assistantError('仅可重试当前对话最后一次未完成请求', 409);
  }
  append(job, scope) {
    this.assertNext(job, scope);
    const previous = this.get(job.workspaceId, job.sessionId);
    const session = { schemaVersion: 1, id: job.sessionId, workspaceId: job.workspaceId, ...scope, lastJobId: job.id,
      revision: (previous?.revision || 0) + 1, createdAt: previous?.createdAt || job.createdAt, updatedAt: job.createdAt };
    this.store.db.prepare('INSERT INTO assistant_sessions(workspace_id,id,payload) VALUES (?,?,?) ON CONFLICT(workspace_id,id) DO UPDATE SET payload=excluded.payload').run(job.workspaceId, job.sessionId, JSON.stringify(session));
    return session;
  }
  export(workspaceId) {
    return { schemaVersion: 1, workspaceId, sessions: this.list(workspaceId), jobs: this.store.db.prepare('SELECT request_id,fingerprint,payload FROM assistant_jobs WHERE workspace_id=? ORDER BY rowid').all(workspaceId).map(r => ({ requestId: r.request_id, fingerprint: r.fingerprint, job: JSON.parse(r.payload) })) };
  }
  /** Coordinator calls inside the same restore transaction, after restoring V2State.
   * IDs are remapped; pending model calls are never restarted, approvals never inferred. */
  restore(bundle, workspaceId) {
    validateAssistantBundle(bundle);
    const state = this.store.load(workspaceId);
    const sessionIds = new Map(bundle.sessions.map(s => [s.id, 'restored-session-' + randomUUID()]));
    const jobIds = new Map(bundle.jobs.map(({ job }) => [job.id, randomUUID()]));
    const inserted = [];
    for (const session of bundle.sessions) {
      if (session.workspaceId !== bundle.workspaceId || !assistantId(session.id) || !sessionIds.has(session.id)) throw assistantError('助手备份会话范围无效');
      const ref = session.contextRef.kind === 'workspace' ? { kind: 'workspace', id: workspaceId } : session.contextRef;
      // A restored conversation may reference an archived object. Keep history;
      // assistantScope will require selecting a valid scope before asking again.
      const next = { ...session, id: sessionIds.get(session.id), workspaceId, contextRef: ref, lastJobId: jobIds.get(session.lastJobId) || '', restored: true };
      this.store.db.prepare('INSERT INTO assistant_sessions(workspace_id,id,payload) VALUES (?,?,?)').run(workspaceId, next.id, JSON.stringify(next));
      inserted.push(next);
    }
    for (const { job: original } of bundle.jobs) {
      if (original.workspaceId !== bundle.workspaceId || !assistantId(original.id)) throw assistantError('助手备份任务范围无效');
      const job = structuredClone(original);
      job.id = jobIds.get(original.id); job.jobId = job.id; job.workspaceId = workspaceId;
      job.sessionId = sessionIds.get(original.sessionId); job.parentJobId = jobIds.get(original.parentJobId) || '';
      if (job.retryOf) job.retryOf = jobIds.get(job.retryOf) || '';
      if (job.contextRef?.kind === 'workspace') job.contextRef.id = workspaceId;
      job.requestId = 'restored-' + job.id; job.idempotencyKey = 'codex-' + job.id;
      if (job.status === 'running') { job.status = 'interrupted'; job.error = '备份恢复：上次模型调用结果未知，未自动重放，请核对后重试。'; }
      job.restoredGroupId = job.groupId || ''; delete job.groupId; delete job.preview;
      job.restored = true; job.warnings = [...(job.warnings || []), '恢复的回答仅作历史，需重新检索；原预览不作为执行批准。'];
      job.citations = (job.citations || []).map(c => ({ ...c, workspaceId, availability: 'stale' }));
      job.evidence = []; job.baseRevision = state.revision;
      this.store.db.prepare('INSERT INTO assistant_jobs(id,workspace_id,request_id,fingerprint,payload) VALUES (?,?,?,?,?)').run(job.id, workspaceId, job.requestId, assistantHash(job.requestId), JSON.stringify(job));
    }
    return inserted;
  }
}
