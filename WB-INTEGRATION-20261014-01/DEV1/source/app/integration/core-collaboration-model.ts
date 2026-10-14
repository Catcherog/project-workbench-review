/** WB-INTEGRATION-20261014-01 / PLAN1. UI projection only; the core service owns business state. */
export type CoreRequest = <T = unknown>(url: string, body?: unknown) => Promise<T>;
export type CoreCommand = Record<string, unknown> & { action: string };
export type Proof = { sourceId: string; quote?: string; kind?: string; attachmentId?: string; fingerprint?: string };
export type Recipient = { id: string; localId?: string; name: string; channel: 'private' | 'group' };
export type Approval = { at?: string; fingerprint?: string; recipient?: Recipient; text?: string; proof?: Proof[] };
export type Message = {
  id: string; workItemId: string; title: string; text: string; fingerprint: string;
  stage: string; executionOwner: string; recipient: Recipient; approvedHash?: string;
  nodeName?: string; purpose?: string; dependsOnAdmission?: boolean; proof?: Proof[];
  approvalHistory?: Approval[]; error?: string; messageId?: string;
  previewChanges?: { previous?: { target?: Record<string, unknown> }; current?: { target?: Record<string, unknown> } };
};
export type DraftMessage = {
  id: string; workItemId: string; title: string; text: string; recipientId: string;
  channel: 'private' | 'group'; purpose?: string; proof?: Proof[]; [key: string]: unknown;
};
export type CoreItem = {
  id: string; title: string; version: number; projectNames: string[];
  core: { admission?: string; delivery?: { messages?: DraftMessage[]; proof?: Proof[] }; messageDrafts?: DraftMessage[] };
};
export type Batch = { id: string; version: number; projectNames: string[]; items: Message[] };
export type Person = { id: string; title: string; identityVerified?: boolean };
export type Notice = {
  id: string; title: string; createdAt?: string;
  channels: Record<string, { stage?: string; error?: string; readback?: { delivery?: string } }>;
};
export type InputEnvelope = { id: string; version: number; status: string; excerpt?: string; error?: string };
export type CoreView = { people: Person[]; groups: Person[]; items: CoreItem[]; runs: Batch[]; notices: Notice[]; inputs: InputEnvelope[] };
export type EditDraft = { fingerprint: string; text: string; recipientId: string };
export type Tone = 'neutral' | 'blue' | 'green' | 'amber' | 'red';
export const STAGES: Readonly<Record<string, { label: string; tone: Tone }>> = {
  pending_review: { label: '待完整预览', tone: 'amber' },
  approved: { label: '已批准，尚未发送', tone: 'blue' },
  sending: { label: '执行中，等待结果', tone: 'blue' },
  sent: { label: '已发送，待回读发送事实', tone: 'blue' },
  readback_verified: { label: '发送事实已回读', tone: 'green' },
  failed_not_sent: { label: '已核实未发出', tone: 'red' },
  unknown: { label: '结果未知，先查询', tone: 'amber' },
  needs_preview: { label: '前提变化，须保存新预览', tone: 'amber' },
  blocked: { label: '前提尚未核实', tone: 'amber' },
  stopped: { label: '已无必要，停止执行', tone: 'neutral' },
  cancelled: { label: '已取消此消息', tone: 'neutral' },
};
const record = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);
const text = (x: unknown): x is string => typeof x === 'string';
const nonempty = (x: unknown): x is string => text(x) && x.length > 0;
const unique = (values: string[]) => new Set(values).size === values.length;
const strings = (x: unknown): x is string[] => Array.isArray(x) && x.every(text);
function isRecipient(x: unknown): x is Recipient {
  return record(x) && nonempty(x.id) && text(x.name) && ['private', 'group'].includes(String(x.channel)) && (x.localId === undefined || text(x.localId));
}
function isProofs(x: unknown): x is Proof[] {
  return Array.isArray(x) && x.every(p => record(p) && nonempty(p.sourceId) && ['quote','kind','attachmentId','fingerprint'].every(k => p[k] === undefined || text(p[k])));
}
function isDraft(x: unknown): x is DraftMessage {
  return record(x) && ['id','workItemId','title','text','recipientId'].every(k => text(x[k])) && ['private','group'].includes(String(x.channel)) && (x.proof === undefined || isProofs(x.proof));
}
function isMessage(x: unknown): x is Message {
  if (!record(x) || !['id','workItemId','fingerprint'].every(k => nonempty(x[k])) || !['title','text','stage','executionOwner'].every(k => text(x[k])) || !isRecipient(x.recipient)) return false;
  if (['approvedHash','nodeName','purpose','error','messageId'].some(k => x[k] !== undefined && !text(x[k]))) return false;
  if (x.dependsOnAdmission !== undefined && typeof x.dependsOnAdmission !== 'boolean') return false;
  if (x.proof !== undefined && !isProofs(x.proof)) return false;
  if (x.approvalHistory !== undefined && (!Array.isArray(x.approvalHistory) || !x.approvalHistory.every(a => record(a) && ['text','at','fingerprint'].every(k => a[k] === undefined || text(a[k])) && (a.recipient === undefined || isRecipient(a.recipient)) && (a.proof === undefined || isProofs(a.proof))))) return false;
  return x.previewChanges === undefined || record(x.previewChanges);
}
/** Invalid/partial snapshots are NOT turned into an empty successful result. Unknown stages remain read-only. */
export function parseCoreView(value: unknown): CoreView {
  if (!record(value) || !['people','groups','items','runs','notices','inputs'].every(k => Array.isArray(value[k]))) throw new Error('协作返回结构不完整；未启用操作，请重新读取。');
  const people = value.people as unknown[], groups = value.groups as unknown[], items = value.items as unknown[], runs = value.runs as unknown[], notices = value.notices as unknown[], inputs = value.inputs as unknown[];
  const person = (p: unknown) => record(p) && nonempty(p.id) && text(p.title) && (p.identityVerified === undefined || typeof p.identityVerified === 'boolean');
  if (![...people, ...groups].every(person)) throw new Error('收件人投影不可用；未启用操作。');
  if (!items.every(i => record(i) && nonempty(i.id) && text(i.title) && Number.isInteger(i.version) && strings(i.projectNames) && record(i.core) && (i.core.admission === undefined || text(i.core.admission)) &&
      (i.core.messageDrafts === undefined || Array.isArray(i.core.messageDrafts) && i.core.messageDrafts.every(isDraft)) &&
      (i.core.delivery === undefined || record(i.core.delivery) && (i.core.delivery.messages === undefined || Array.isArray(i.core.delivery.messages) && i.core.delivery.messages.every(isDraft)) && (i.core.delivery.proof === undefined || isProofs(i.core.delivery.proof))))) throw new Error('事项投影不可用；未启用操作。');
  if (!runs.every(b => record(b) && nonempty(b.id) && Number.isInteger(b.version) && strings(b.projectNames) && Array.isArray(b.items) && b.items.every(isMessage) && unique((b.items as Message[]).map(m => m.id)))) throw new Error('消息批次投影不可用；未启用操作。');
  if (!notices.every(n => record(n) && nonempty(n.id) && text(n.title) && (n.createdAt === undefined || text(n.createdAt)) && record(n.channels) && Object.values(n.channels).every(c => record(c) && ['stage','error'].every(k => c[k] === undefined || text(c[k])) && (c.readback === undefined || record(c.readback) && (c.readback.delivery === undefined || text(c.readback.delivery)))))) throw new Error('提醒回执投影不可用；请重新读取。');
  if (!inputs.every(i => record(i) && nonempty(i.id) && Number.isInteger(i.version) && text(i.status) && ['excerpt','error'].every(k => i[k] === undefined || text(i[k])))) throw new Error('输入投影不可用；请重新读取。');
  for (const collection of [people, groups, items, runs, notices, inputs]) {
    if (!unique(collection.map(x => (x as {id: string}).id))) throw new Error('投影身份重复；未启用操作。');
  }
  return value as unknown as CoreView;
}
export const messageKey = (batchId: string, messageId: string) => JSON.stringify([batchId, messageId]);
export const approvalKey = (batchId: string, m: Pick<Message, 'id' | 'fingerprint'>) => JSON.stringify([batchId, m.id, m.fingerprint]);
export const admissionKey = (item: Pick<CoreItem, 'id' | 'version'>) => JSON.stringify([item.id, item.version]);
export const recipientId = (m: Message) => m.recipient.localId || m.recipient.id;
export const stagePresentation = (m: Pick<Message, 'stage'>) => STAGES[m.stage] || { label: '未识别状态（' + m.stage + '），仅供查阅', tone: 'amber' as Tone };
export const ownerLabel = (m: Pick<Message, 'executionOwner'>) => m.executionOwner === 'human' ? '本人接手执行' : m.executionOwner === 'ai' ? '由系统执行' : '执行权未识别';
export const canEdit = (m: Message) => ['pending_review','needs_preview','approved','failed_not_sent'].includes(m.stage);
export const canApprove = (m: Message) => m.stage === 'pending_review';
export const canChangeAuthority = (m: Message) => !!STAGES[m.stage] && ['ai','human'].includes(m.executionOwner) && !['cancelled','stopped','readback_verified'].includes(m.stage);
export const needsReconcile = (m: Message) => ['unknown','sending','sent'].includes(m.stage);
export const isExecutionCandidate = (m: Message) => m.executionOwner === 'ai' && ['approved','failed_not_sent'].includes(m.stage);
export const draftChanged = (m: Message, edit?: EditDraft) => !!edit && (edit.text !== m.text || edit.recipientId !== recipientId(m));
export const draftStale = (m: Message, edit?: EditDraft) => !!edit && edit.fingerprint !== m.fingerprint;
export const draftsFromView = (view: CoreView): DraftMessage[] => view.items.flatMap(i => [
  ...(i.core.delivery?.messages || []).map(m => ({...m, proof: i.core.delivery?.proof || m.proof})),
  ...(i.core.messageDrafts || []),
]);
export function viewUrl(workspaceId: string, sourceId?: string): string {
  if (!workspaceId) throw new Error('缺少工作区身份。');
  return '/api/v2/core?workspaceId=' + encodeURIComponent(workspaceId) + (sourceId ? '&sourceId=' + encodeURIComponent(sourceId) : '');
}
function requireRequestId(requestId: string) { if (!requestId) throw new Error('缺少原请求身份。'); }
export function prepareCommand(drafts: DraftMessage[], selected: ReadonlySet<string>, requestId: string): CoreCommand {
  requireRequestId(requestId);
  const messages = drafts.filter(m => selected.has(m.id));
  if (!messages.length || messages.length > 20 || !unique(messages.map(m => m.id)) || messages.length !== selected.size) throw new Error('请明确选择 1–20 条不同的完整草稿。');
  return { action: 'prepare-messages', requestId, messages };
}
/** Admissions and approvals use independent selection sets and remain separate arrays on the wire. */
export function decisionCommand(batch: Batch, view: CoreView, selected: ReadonlySet<string>, admissions: ReadonlySet<string>, edits: Readonly<Record<string, EditDraft>>, requestId: string): CoreCommand {
  requireRequestId(requestId);
  const inBatch = batch.items.filter(m => selected.has(approvalKey(batch.id, m)));
  const batchSelections = [...selected].filter(key => { try { return JSON.parse(key)[0] === batch.id; } catch { return false; } });
  if (batchSelections.length !== inBatch.length) throw new Error('所选预览指纹已变化，请重新核对后勾选。');
  for (const m of inBatch) {
    const edit = edits[messageKey(batch.id,m.id)];
    if (!canApprove(m)) throw new Error('所选消息状态已变化；旧批准不重复保存。');
    if (draftStale(m, edit) || draftChanged(m, edit)) throw new Error('先保存修改并回读新指纹，再批准实际正文。');
  }
  const related = new Set(batch.items.map(m => m.workItemId));
  const chosen = view.items.filter(i => related.has(i.id) && admissions.has(admissionKey(i)));
  const relatedSelections = [...admissions].filter(key => { try { return related.has(JSON.parse(key)[0]); } catch { return false; } });
  if (chosen.length !== relatedSelections.length || chosen.some(i => i.core.admission !== 'candidate')) throw new Error('候选版本或纳入状态已变化，请重新核对。');
  for (const m of inBatch) {
    if (!m.dependsOnAdmission) continue;
    const item = view.items.find(i => i.id === m.workItemId);
    if (!item || item.core.admission !== 'managed' && !chosen.some(i => i.id === item.id)) throw new Error('这条消息依赖独立纳入决定；未替你勾选纳入。');
  }
  if (!inBatch.length && !chosen.length) throw new Error('尚未选择本批需要保存的决定。');
  return { action: 'decide-messages', sourceId: batch.id, requestId,
    decisions: inBatch.map(m => ({ id: m.id, fingerprint: m.fingerprint, action: 'approve' })),
    admissions: chosen.map(i => ({ id: i.id, expectedVersion: i.version })) };
}
export function editCommand(batch: Batch, m: Message, edit: EditDraft, requestId: string): CoreCommand {
  requireRequestId(requestId);
  if (!canEdit(m) || draftStale(m, edit)) throw new Error('预览或消息状态已变化，草稿保留；先核对最新版本。');
  if (!edit.text.trim() || edit.text.trim().length > 4000 || !edit.recipientId) throw new Error('请保留 1–4000 字完整正文和明确收件人。');
  return { action: 'decide-messages', sourceId: batch.id, requestId, decisions: [{ id: m.id, fingerprint: m.fingerprint, action: 'edit', text: edit.text, recipientId: edit.recipientId }] };
}
export function cancelCommand(batch: Batch, m: Message, requestId: string): CoreCommand {
  requireRequestId(requestId); if (!canEdit(m)) throw new Error('已有发送记录或状态不支持取消；请先核对结果。');
  return { action: 'decide-messages', sourceId: batch.id, requestId, decisions: [{ id: m.id, fingerprint: m.fingerprint, action: 'cancel' }] };
}
export function authorityCommand(batch: Batch, m: Message): CoreCommand {
  if (!canChangeAuthority(m)) throw new Error('这条消息不支持改变执行权。');
  return { action: 'message-authority', sourceId: batch.id, messageId: m.id, expectedFingerprint: m.fingerprint, authorityAction: m.executionOwner === 'human' ? 'release' : 'takeover' };
}
export function executionPlan(batch: Batch, edits: Readonly<Record<string, EditDraft>>) {
  const messages = batch.items.filter(isExecutionCandidate);
  const unresolved = batch.items.filter(needsReconcile);
  const dirty = batch.items.some(m => draftChanged(m, edits[messageKey(batch.id,m.id)]) || draftStale(m, edits[messageKey(batch.id,m.id)]));
  const unbound = messages.some(m => m.approvedHash !== m.fingerprint);
  const reason = unresolved.length ? '本批存在待核实发送结果，先查询；不会自动重发。' : dirty ? '本批有未保存或过期草稿；先保存或明确放弃草稿。' : unbound ? '批准指纹尚未匹配当前预览；先核对。' : !messages.length ? '本批没有可由系统执行的已批准消息。' : '';
  return { messages, reason, allowed: !reason, retryCount: messages.filter(m => m.stage === 'failed_not_sent').length };
}
export function executeCommand(batch: Batch, edits: Readonly<Record<string, EditDraft>>): CoreCommand {
  const plan = executionPlan(batch, edits); if (!plan.allowed) throw new Error(plan.reason);
  // The current API executes a batch. Do not invent messageIds or claim per-message scope.
  return { action: 'execute-messages', sourceId: batch.id };
}
export function reconcileCommand(batch: Batch): CoreCommand { return { action: 'reconcile-messages', sourceId: batch.id }; }
export function noticeLabel(channel: string, value: Notice['channels'][string]) {
  const delivery = value.readback?.delivery;
  if (channel === 'desktop' && delivery === 'queued') return '已排队，尚未展示';
  if (channel === 'desktop' && delivery === 'submitted') return '已提交电脑通知';
  return STAGES[value.stage || '']?.label || value.stage || '尚无可核实结果';
}
