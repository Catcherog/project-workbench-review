"use client";

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type {
  AMActionRequest, AMChannel, AMPresentation, AMPreview, AMReceipt, AMRecommendation,
  Bootstrap, Entry, Evidence, LedgerRequest, ProjectSummary, Reminder, Review, RowKey,
} from './types';
import './ledger-workbench.css';
import { withLedgerOperations } from './request';
import { isLedgerAccessError, LedgerRequestError } from './request-error';

const API = '/api/v2/ledger';
const ROWS: RowKey[] = ['plan', 'progress', 'blocker', 'todo'];
const LABELS: Record<RowKey, string> = { plan: '计划', progress: '进展', blocker: '卡点', todo: '我的待办' };
const PROJECT_STATUS: Record<string, string> = { active: '进行中', paused: '已暂停', closed: '已结束', unknown: '状态待核对' };
const ITEM_STATUS: Record<string, string> = { open: '待推进', waiting: '等待反馈', paused: '已暂停' };
const RECEIPT_STATUS: Record<string, string> = {
  queued: '已进入执行队列', already_reserved: '原请求已登记', blocked: '执行受阻',
  approved: '已确认，等待执行', sending: '正在发送', sent: '已发送，等待核对',
  readback_verified: '发送回执已核对', failed_not_sent: '本次未发出', unknown: '发送结果待核对',
  running: '执行中', waiting: '等待反馈', cancelled: '已取消', stopped: '已停止',
  sent_unverified: '消息已发送，回执待核对', sent_confirmed: '消息发送已核实',
  confirmed: '确认已记录，等待执行安排', expired: '本次执行安排已过期', failed: '本次执行未完成',
};
const READBACK_STATUS: Record<string, string> = {
  verified: '已核实', not_sent: '尚未发送', pending: '待核对', unknown: '待确认',
  unverified: '未核实', not_started: '尚未开始核对', failed: '核对未完成',
};

type Pane =
  | { kind: 'am' }
  | { kind: 'reviews' }
  | { kind: 'reminders' }
  | { kind: 'evidence'; row?: RowKey; itemId?: string }
  | null;
interface AMState {
  itemId: string;
  result?: AMRecommendation;
  preview?: AMPreview;
  presentation?: AMPresentation;
  body: string;
  channel: AMChannel;
  recipientId: string;
  busy?: 'prepare' | 'revise' | 'present' | 'approve' | 'receipt';
  error?: string;
  requestId?: string;
  prepareRequestId?: string;
  prepareKey?: string;
  receipt?: AMReceipt;
}
interface PendingTicket { projectId: string; itemId: string; requestId: string }
const emptyAM = (): AMState => ({ itemId: '', body: '', channel: 'group', recipientId: '' });

export interface LedgerWorkbenchProps {
  request: LedgerRequest;
  initialProjectId?: string;
  className?: string;
}

function humanTime(value: string | number | null | undefined): string {
  if (value == null || value === '') return '尚无时间记录';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
    hour12: false, timeZone: 'Asia/Shanghai',
  }).format(date);
}
function errorText(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return '本次请求未得到可核对的结果，请保留当前内容后重试。';
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function parseBootstrap(value: unknown): Bootstrap {
  if (!isRecord(value) || value.schemaVersion !== 1 || !Array.isArray(value.projects)
      || !Array.isArray(value.reviews) || !Array.isArray(value.reminders)
      || typeof value.workspaceId !== 'string') throw new Error('台账概览数据不完整，请刷新后核对。');
  return value as unknown as Bootstrap;
}
function parseSummary(value: unknown, projectId: string): ProjectSummary {
  if (!isRecord(value) || !isRecord(value.project) || value.project.id !== projectId
      || !Array.isArray(value.rows) || !isRecord(value.details) || !Array.isArray(value.details.items)
      || !ROWS.every(key => (value.rows as { key: string }[]).some(row => row.key === key))) {
    throw new Error('此项目的四项摘要尚未完整返回，请刷新后核对。');
  }
  return value as unknown as ProjectSummary;
}
function parsePreview(value: unknown): AMPreview {
  if (!isRecord(value) || typeof value.previewId !== 'string' || typeof value.body !== 'string'
      || typeof value.displayHash !== 'string' || !isRecord(value.target)
      || typeof value.target.name !== 'string' || !isRecord(value.sendWindow)
      || typeof value.expiresAtMs !== 'number' || value.count !== 1) {
    throw new Error('AM 未返回完整的对象、正文和发送范围，暂时不能确认执行。');
  }
  return value as unknown as AMPreview;
}
function parseRecommendation(value: unknown): AMRecommendation {
  if (isRecord(value) && value.kind === 'choose_route' && typeof value.reason === 'string'
      && Array.isArray(value.allowedChannels) && Array.isArray(value.assigneeIds)) {
    return { ...value, recommendation: typeof value.recommendation === 'string' ? value.recommendation : '先核实本次跟进对象' } as unknown as AMRecommendation;
  }
  if (!isRecord(value) || typeof value.recommendation !== 'string') {
    throw new Error('AM 建议尚未完整返回，请重新获取。');
  }
  if (value.kind === 'choose' && Array.isArray(value.items)) {
    return { ...value, reason: typeof value.reason === 'string' ? value.reason : '请从上方选择要跟进的原事项。' } as unknown as AMRecommendation;
  }
  if (typeof value.reason !== 'string') throw new Error('AM 建议缺少依据说明，请重新获取。');
  if (value.kind === 'wait') return value as unknown as AMRecommendation;
  if (value.kind !== 'action' || typeof value.itemId !== 'string') throw new Error('AM 返回的建议类型暂不支持。');
  return { ...value, preview: parsePreview(value.preview) } as unknown as AMRecommendation;
}
function changed(state: AMState): boolean {
  const p = state.preview;
  return !!p && (state.body !== p.body || state.channel !== p.target.channel
    || (state.channel === 'recipient_p2p' && state.recipientId !== p.target.id));
}
function ticketKey(workspaceId: string) { return 'ledger-workbench:pending:v1:' + workspaceId; }
function readTickets(workspaceId: string): PendingTicket[] {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem(ticketKey(workspaceId)) || '[]');
    if (!Array.isArray(raw)) return [];
    return raw.filter((t): t is PendingTicket => isRecord(t) && typeof t.projectId === 'string'
      && typeof t.itemId === 'string' && typeof t.requestId === 'string').slice(-30);
  } catch { return []; }
}
function saveTicket(workspaceId: string, ticket: PendingTicket) {
  try {
    const tickets = readTickets(workspaceId).filter(t => t.requestId !== ticket.requestId);
    sessionStorage.setItem(ticketKey(workspaceId), JSON.stringify([...tickets, ticket].slice(-30)));
  } catch { /* Memory state still retains the request id if browser storage is unavailable. */ }
}

function useEvidenceClock(evidence: Evidence[]) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const expiry = evidence.map(source => source.rawExpiresAt ? Date.parse(source.rawExpiresAt) : NaN)
      .filter(value => Number.isFinite(value) && value > now);
    if (!expiry.length) return;
    const timer = window.setTimeout(() => setNow(Date.now()), Math.min(2_147_483_647, Math.max(1, Math.min(...expiry) - Date.now() + 10)));
    return () => window.clearTimeout(timer);
  }, [evidence, now]);
  return Math.max(now, Date.now());
}
function rawExpired(source: Evidence, now: number) {
  if (!source.rawExpiresAt) return false;
  const expiry = Date.parse(source.rawExpiresAt);
  return !Number.isFinite(expiry) || expiry <= now;
}
function readableEntryText(entry: Pick<Entry, 'text' | 'sourceRefs' | 'retentionBoundExcerpt' | 'rawExcerptUnavailable'>, now: number) {
  if (!entry.retentionBoundExcerpt) return entry.text;
  const hasReadableSource = entry.sourceRefs.some(source =>
    source.rawAvailable && typeof source.quote === 'string' && !rawExpired(source, now));
  return entry.rawExcerptUnavailable || !hasReadableSource ? '原文暂不可用，待刷新' : entry.text;
}
function receiptReason(reason: string) {
  if (reason === 'admission_not_recorded') return '原确认尚未查到登记结果，请继续核对原请求回执。';
  if (reason === 'native_admission_not_completed') return '执行安排尚未完成，请核对原请求状态。';
  return /^[A-Za-z0-9_:-]+$/.test(reason) ? '当前执行条件需要重新核对，请查询原请求回执。' : reason;
}
function reviewReason(reason: string) {
  if (reason === 'project_unresolved') return '尚不能确定这条反馈对应的项目，请核对归属。';
  return /^[A-Za-z0-9_:-]+$/.test(reason) ? '这条资料存在影响判断的疑点，请结合来源核对。' : reason;
}
function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  const now = useEvidenceClock(evidence);
  if (!evidence.length) return <p className="lw-muted">这条信息尚未附可展开的原文。</p>;
  return <ul className="lw-evidence-list">{evidence.map((source, index) => {
    const expired = rawExpired(source, now);
    const available = source.rawAvailable && !expired;
    return <li key={source.sourceId + ':' + source.objectId + ':' + index}>
      <div className="lw-meta"><span>来源 {index + 1}</span>
        {source.occurredAt ? <time dateTime={source.occurredAt}>{humanTime(source.occurredAt)}</time> : null}
        {source.stale ? <span className="lw-attention">来源需要更新</span> : null}
      </div>
      {available && source.quote ? <blockquote>{source.quote}</blockquote>
        : <p className="lw-muted">{expired ? '原文已超出可读期限，请刷新来源后核对。' : available ? '来源已关联，当前投影未提供原文。' : '当前没有可读原文，保留待核对状态。'}</p>}
    </li>;
  })}</ul>;
}
function SourceEntries({ entries }: { entries: Entry[] }) {
  const now = useEvidenceClock(entries.flatMap(entry => entry.sourceRefs));
  if (!entries.length) return <p className="lw-muted">本项尚无已归集内容。</p>;
  return <div className="lw-source-entries">{entries.map(entry =>
    <article key={entry.id} className="lw-source-entry">
      <p className={entry.critical ? 'lw-attention' : ''}>{readableEntryText(entry, now)}</p>
      <details><summary>查看依据{entry.sourceRefs.length ? ' · ' + entry.sourceRefs.length : ''}</summary>
        <EvidenceList evidence={entry.sourceRefs} />
      </details>
    </article>)}</div>;
}
function Busy({ children }: { children: string }) {
  return <span role="status" className="lw-muted lw-busy">{children}</span>;
}

/** A host-owned, same-page ledger view. No business state is inferred in the browser. */
export function LedgerWorkbench({ request, initialProjectId, className = '' }: LedgerWorkbenchProps) {
  const id = useId();
  const requestRef = useRef(request);
  useEffect(() => { requestRef.current = request; }, [request]);
  const [transport] = useState(() => withLedgerOperations((path, body) => requestRef.current(path, body)));
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [selectedId, setSelectedId] = useState(initialProjectId || '');
  const [query, setQuery] = useState('');
  const [pane, setPane] = useState<Pane>(null);
  const [indexLoading, setIndexLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [error, setError] = useState('');
  const [accessIssue, setAccessIssue] = useState('');
  const [indexIssue, setIndexIssue] = useState('');
  const [summaryIssue, setSummaryIssue] = useState('');
  const [notice, setNotice] = useState('');
  const [reviewAll, setReviewAll] = useState(false);
  const [reviewChoices, setReviewChoices] = useState<Record<string, string>>({});
  const [mutating, setMutating] = useState<Record<string, boolean>>({});
  const [sessions, setSessions] = useState<Record<string, AMState>>({});
  const [tickets, setTickets] = useState<PendingTicket[]>([]);
  const [focusItemId, setFocusItemId] = useState<string | null>(null);
  const processingGaps = summary?.details.processingGaps || summary?.coverage.processingGaps || [];
  const reviewTime = useEvidenceClock([
    ...(bootstrap?.reviews || []).flatMap(review => review.evidence),
    ...(summary?.rows || []).flatMap(row => [...row.entries, ...row.moreEntries].flatMap(entry => entry.sourceRefs)),
    ...processingGaps.flatMap(gap => gap.sourceRefs),
  ]);
  const selectedRef = useRef(selectedId);
  const indexGeneration = useRef(0);
  const summaryGeneration = useRef(0);
  const accessGeneration = useRef(0);
  const presentationInFlight = useRef(new Set<string>());
  const prepareInFlight = useRef(new Set<string>());
  const approvalRequests = useRef(new Map<string, string>());
  const mutationIds = useRef(new Map<string, string>());
  const pendingReminderOperations = useRef(new Map<string, { requestId: string; until?: string }>());
  const reminderInFlight = useRef(new Set<string>());
  const refreshInFlight = useRef<Promise<void> | null>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const paneHeadingRef = useRef<HTMLHeadingElement>(null);
  const messageRef = useRef<HTMLTextAreaElement>(null);
  selectedRef.current = selectedId;

  const clearInaccessibleData = useCallback((problem: unknown) => {
    accessGeneration.current++;
    indexGeneration.current++;
    summaryGeneration.current++;
    setBootstrap(null);
    setSummary(null);
    setSessions({});
    setTickets([]);
    setPane(null);
    setQuery('');
    setReviewChoices({});
    setMutating({});
    setFocusItemId(null);
    setIndexLoading(false);
    setSummaryLoading(false);
    setIndexIssue('');
    setSummaryIssue('');
    setError('');
    setNotice('');
    mutationIds.current.clear();
    pendingReminderOperations.current.clear();
    setAccessIssue(errorText(problem));
  }, []);
  const call = useCallback(async (path: string, body?: Record<string, unknown>) => {
    const generation = accessGeneration.current;
    try {
      const result = await transport(path, body);
      if (generation !== accessGeneration.current) {
        throw new LedgerRequestError('访问范围已经变化，请重新核对后读取。', {
          status: 403, code: 'WEB_SOURCE_ACCESS_CHANGED',
        });
      }
      return result;
    } catch (problem) {
      if (isLedgerAccessError(problem) && generation === accessGeneration.current) clearInaccessibleData(problem);
      throw problem;
    }
  }, [transport, clearInaccessibleData]);

  const loadBootstrap = useCallback(async () => {
    const generation = ++indexGeneration.current;
    setIndexLoading(true);
    try {
      const result = parseBootstrap(await call(API + '/bootstrap'));
      if (generation !== indexGeneration.current) return;
      setAccessIssue('');
      setIndexIssue('');
      setBootstrap(result);
      setSelectedId(current => result.projects.some(project => project.id === current) ? current
        : result.projects.some(project => project.id === initialProjectId) ? initialProjectId! : result.projects[0]?.id || '');
    } catch (problem) {
      if (generation === indexGeneration.current) setIndexIssue(errorText(problem));
    } finally {
      if (generation === indexGeneration.current) setIndexLoading(false);
    }
  }, [call, initialProjectId]);

  const loadSummary = useCallback(async (projectId: string) => {
    if (!projectId) return;
    const generation = ++summaryGeneration.current;
    setSummaryLoading(true);
    try {
      const result = parseSummary(await call(API + '/projects/' + encodeURIComponent(projectId)), projectId);
      if (generation === summaryGeneration.current && selectedRef.current === projectId) {
        setSummary(result);
        setSummaryIssue('');
      }
    } catch (problem) {
      if (generation === summaryGeneration.current) setSummaryIssue(errorText(problem));
    } finally {
      if (generation === summaryGeneration.current) setSummaryLoading(false);
    }
  }, [call]);

  useEffect(() => { void loadBootstrap(); return () => { indexGeneration.current++; }; }, [loadBootstrap]);
  useEffect(() => {
    setSummary(null);
    setError('');
    setSummaryIssue('');
    if (selectedId) void loadSummary(selectedId);
    return () => { summaryGeneration.current++; };
  }, [selectedId, loadSummary]);
  useEffect(() => {
    if (!bootstrap?.workspaceId) return;
    const savedTickets = readTickets(bootstrap.workspaceId);
    setTickets(savedTickets);
    setSessions(current => {
      const next = { ...current };
      const latest = new Map(savedTickets.map(ticket => [ticket.projectId, ticket]));
      for (const ticket of latest.values()) if (!next[ticket.projectId]?.requestId) {
        next[ticket.projectId] = { ...emptyAM(), itemId: ticket.itemId, requestId: ticket.requestId };
      }
      return next;
    });
  }, [bootstrap?.workspaceId]);
  useEffect(() => {
    if (pane) paneHeadingRef.current?.focus({ preventScroll: true });
  }, [pane?.kind]);

  const updateAM = useCallback((projectId: string, update: (state: AMState) => AMState) => {
    setSessions(current => ({ ...current, [projectId]: update(current[projectId] || emptyAM()) }));
  }, []);
  const am = sessions[selectedId] || emptyAM();
  useEffect(() => {
    const previews = Object.values(sessions).flatMap(state => state.preview ? [state.preview] : []);
    if (!previews.length) return;
    const expires = Math.min(...previews.map(preview => preview.expiresAtMs));
    const timer = window.setTimeout(() => {
      const now = Date.now();
      setSessions(current => Object.fromEntries(Object.entries(current).map(([key, state]) =>
        state.preview && state.preview.expiresAtMs <= now
          ? [key, { ...state, preview: undefined, presentation: undefined, result: undefined, body: '',
              error: state.requestId ? state.error : '本次预览已到期，请重新获取建议并核对来源。' }]
          : [key, state])));
    }, Math.min(2_147_483_647, Math.max(1, expires - Date.now() + 10)));
    return () => window.clearTimeout(timer);
  }, [sessions]);
  const dirty = changed(am);
  const previewId = am.preview?.previewId;
  const paneKind = pane?.kind;
  useEffect(() => {
    const field = messageRef.current;
    if (field && paneKind === 'am') {
      field.style.height = 'auto';
      field.style.height = field.scrollHeight + 'px';
    }
  }, [am.body, paneKind, previewId]);
  const presentPreview = useCallback(async (projectId: string, preview: AMPreview) => {
    if (presentationInFlight.current.has(preview.previewId)) return;
    presentationInFlight.current.add(preview.previewId);
    updateAM(projectId, current => ({ ...current, busy: 'present', error: undefined }));
    try {
      const raw = await call(API + '/am/present', {
        previewId: preview.previewId, displayHash: preview.displayHash,
        requestId: requestIdentity('present:' + preview.previewId + ':' + preview.displayHash),
      });
      if (!isRecord(raw) || typeof raw.presentationId !== 'string' || typeof raw.expiresAtMs !== 'number') {
        throw new Error('预览展示尚未登记成功，请重新登记后再确认。');
      }
      updateAM(projectId, current => current.preview?.previewId === preview.previewId && !changed(current)
        ? { ...current, presentation: raw as unknown as AMPresentation, busy: undefined }
        : { ...current, busy: undefined });
    } catch (problem) {
      updateAM(projectId, current => ({ ...current, busy: undefined, error: errorText(problem) }));
    } finally { presentationInFlight.current.delete(preview.previewId); }
  }, [call, updateAM]);

  useEffect(() => {
    if (paneKind === 'am' && am.preview && !dirty && !am.presentation && !am.busy && !am.error && !am.requestId) {
      void presentPreview(selectedId, am.preview);
    }
  }, [paneKind, previewId, dirty, am.presentation?.presentationId, am.busy, am.error, am.requestId, selectedId, presentPreview]);

  const refresh = useCallback((manual = true): Promise<void> => {
    if (manual) setError('');
    if (refreshInFlight.current) return refreshInFlight.current;
    const projectId = selectedRef.current;
    const work = Promise.allSettled([loadBootstrap(), projectId ? loadSummary(projectId) : Promise.resolve()])
      .then(() => undefined).finally(() => { refreshInFlight.current = null; });
    refreshInFlight.current = work;
    return work;
  }, [loadBootstrap, loadSummary]);
  useEffect(() => {
    let timer: number | undefined;
    const start = (refreshNow: boolean) => {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
      if (document.visibilityState !== 'visible') return;
      if (refreshNow) void refresh(false);
      timer = window.setInterval(() => {
        if (document.visibilityState === 'visible') void refresh(false);
      }, 30_000);
    };
    const onVisibility = () => start(true);
    const onFocus = () => {
      if (document.visibilityState === 'visible') void refresh(false);
    };
    start(false);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('focus', onFocus);
    return () => {
      if (timer !== undefined) window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('focus', onFocus);
    };
  }, [refresh]);
  function openPane(next: Exclude<Pane, null>) {
    setPane(current => current?.kind === next.kind && next.kind !== 'evidence' ? null : next);
    setNotice('');
  }
  function chooseProject(projectId: string) {
    setSelectedId(projectId);
    setPane(null);
    setFocusItemId(null);
    setNotice('');
  }
  function requestIdentity(key: string) {
    let value = mutationIds.current.get(key);
    if (!value) { value = crypto.randomUUID(); mutationIds.current.set(key, value); }
    return value;
  }
  async function resolveReview(review: Review) {
    if (review.evidence.some(source => rawExpired(source, Date.now()))) {
      setError('这条判断依据的原文已到期，请刷新来源后再处理。');
      return;
    }
    const choiceId = reviewChoices[review.id];
    if (!choiceId) return;
    const requestId = requestIdentity('review:' + review.id + ':' + review.basis + ':' + choiceId);
    setMutating(current => ({ ...current, [review.id]: true }));
    setError('');
    try {
      await call(API + '/reviews/resolve', { reviewId: review.id, choiceId, expectedBasis: review.basis, requestId });
      setNotice('已保存这条判断，正在刷新归集结果。');
      await Promise.allSettled([loadBootstrap(), loadSummary(selectedId)]);
    } catch (problem) { setError(errorText(problem)); }
    finally { setMutating(current => ({ ...current, [review.id]: false })); }
  }
  async function changeReminder(reminder: Reminder, action: 'ack' | 'snooze') {
    const key = reminder.id + ':' + action + ':' + reminder.basis;
    if (reminderInFlight.current.has(key)) return;
    reminderInFlight.current.add(key);
    const operation = pendingReminderOperations.current.get(key) || {
      requestId: crypto.randomUUID(),
      ...(action === 'snooze' ? { until: new Date(Date.now() + 60 * 60 * 1000).toISOString() } : {}),
    };
    pendingReminderOperations.current.set(key, operation);
    setMutating(current => ({ ...current, [reminder.id]: true }));
    setError('');
    try {
      await call(API + '/reminders/' + action, {
        reminderId: reminder.id, expectedBasis: reminder.basis || bootstrap?.basis,
        requestId: operation.requestId,
        ...(operation.until ? { until: operation.until } : {}),
      });
      pendingReminderOperations.current.delete(key);
      setNotice(action === 'ack' ? '已标记读过，事项继续保留原进展。' : '此提醒暂缓显示 1 小时；原期限保留。');
      await Promise.allSettled([loadBootstrap(), loadSummary(selectedId)]);
    } catch (problem) { setError(errorText(problem)); }
    finally {
      reminderInFlight.current.delete(key);
      setMutating(current => ({ ...current, [reminder.id]: false }));
    }
  }
  function locate(reminder: Reminder) {
    if (reminder.projectId !== selectedId) setSelectedId(reminder.projectId);
    setFocusItemId(reminder.itemId);
    setPane({ kind: 'evidence', itemId: reminder.itemId });
    setQuery('');
    sectionRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function chooseAMItem(itemId: string) {
    updateAM(selectedId, () => ({ ...emptyAM(), itemId }));
  }
  async function prepareAM(route?: { channel: AMChannel; recipientId?: string }) {
    const projectId = selectedId;
    const itemId = am.itemId;
    if ((!itemId && actionableItems.length > 0) || am.busy || prepareInFlight.current.has(projectId)) return;
    prepareInFlight.current.add(projectId);
    const selectedRoute = route || (am.result?.kind === 'choose_route' ? {
      channel: am.channel,
      ...(am.channel === 'recipient_p2p' ? { recipientId: am.recipientId } : {}),
    } : {});
    const prepareKey = JSON.stringify({ projectId, itemId, ...selectedRoute });
    const prepareRequestId = am.prepareKey === prepareKey && am.prepareRequestId ? am.prepareRequestId : crypto.randomUUID();
    updateAM(projectId, current => ({ ...current, prepareKey, prepareRequestId, busy: 'prepare', error: undefined, preview: undefined, presentation: undefined }));
    try {
      const result = parseRecommendation(await call(API + '/am/prepare', { projectId, itemId, ...selectedRoute, requestId: prepareRequestId }));
      updateAM(projectId, current => result.kind === 'action'
        ? { ...current, result, preview: result.preview, body: result.preview.body,
          channel: result.preview.target.channel, recipientId: result.preview.target.id, busy: undefined, prepareRequestId: undefined, prepareKey: undefined }
        : { ...current, result, busy: undefined, prepareRequestId: undefined, prepareKey: undefined,
          channel: result.kind === 'choose_route' && result.allowedChannels.length === 1 ? result.allowedChannels[0] : current.channel });
    } catch (problem) { updateAM(projectId, current => ({ ...current, busy: undefined, error: errorText(problem) })); }
    finally { prepareInFlight.current.delete(projectId); }
  }
  function editDraft(patch: Partial<Pick<AMState, 'body' | 'channel' | 'recipientId'>>) {
    updateAM(selectedId, current => ({ ...current, ...patch, presentation: undefined, error: undefined }));
  }
  async function reviseAM() {
    const projectId = selectedId;
    if (!am.preview || am.result?.kind !== 'action' || am.busy || !dirty) return;
    const payload: AMActionRequest = {
      projectId,
      requestId: requestIdentity('revise:' + am.preview.previewId + ':' + am.channel + ':' + am.recipientId + ':' + am.body),
      itemId: am.result.itemId, expectedItemVersion: am.result.expectedItemVersion,
      expectedSemanticVersion: am.result.expectedSemanticVersion, channel: am.channel,
      ...(am.channel === 'recipient_p2p' ? { recipientId: am.recipientId } : {}),
      body: am.body, purpose: 'request_progress', previousPreviewId: am.preview.previewId,
    };
    updateAM(projectId, current => ({ ...current, busy: 'revise', error: undefined, presentation: undefined }));
    try {
      const raw = await call(API + '/am/revise', payload as unknown as Record<string, unknown>);
      const preview = parsePreview(isRecord(raw) && 'preview' in raw ? raw.preview : raw);
      updateAM(projectId, current => ({ ...current, preview, body: preview.body, channel: preview.target.channel,
        recipientId: preview.target.id, busy: undefined }));
    } catch (problem) { updateAM(projectId, current => ({ ...current, busy: undefined, error: errorText(problem) })); }
  }
  async function checkReceipt(projectId = selectedId, originalRequestId?: string) {
    const state = sessions[projectId];
    const requestId = originalRequestId || state?.requestId;
    if (!requestId || state?.busy) return;
    updateAM(projectId, current => ({ ...current, busy: 'receipt', error: undefined }));
    try {
      const raw = await call(API + '/am/receipts/' + encodeURIComponent(requestId));
      if (!isRecord(raw) || typeof raw.state !== 'string') throw new Error('原请求尚未返回可核对的回执。');
      updateAM(projectId, current => ({ ...current, receipt: raw as unknown as AMReceipt, busy: undefined }));
    } catch (problem) { updateAM(projectId, current => ({ ...current, busy: undefined, error: errorText(problem) })); }
  }
  async function approveAM() {
    const projectId = selectedId;
    if (!am.preview || !am.presentation || dirty || am.busy || am.requestId || !bootstrap
        || approvalRequests.current.has(am.preview.previewId)) return;
    if (Date.now() >= Math.min(am.preview.expiresAtMs, am.presentation.expiresAtMs)) {
      updateAM(projectId, current => ({ ...current, presentation: undefined, error: '预览已到期，请重新获取建议后确认。' }));
      return;
    }
    const requestId = crypto.randomUUID();
    approvalRequests.current.set(am.preview.previewId, requestId);
    const payload = { previewId: am.preview.previewId, presentationId: am.presentation.presentationId, displayHash: am.preview.displayHash, requestId };
    saveTicket(bootstrap.workspaceId, { projectId, itemId: am.itemId, requestId });
    setTickets(current => [...current.filter(ticket => ticket.requestId !== requestId),
      { projectId, itemId: am.itemId, requestId }].slice(-30));
    updateAM(projectId, current => ({ ...current, requestId, busy: 'approve', error: undefined }));
    try {
      const raw = await call(API + '/am/approve', payload);
      if (!isRecord(raw) || typeof raw.state !== 'string') throw new Error('确认结果尚未完整返回，请查询原请求回执。');
      updateAM(projectId, current => ({ ...current, receipt: raw as unknown as AMReceipt, busy: undefined }));
    } catch (problem) {
      updateAM(projectId, current => ({ ...current, busy: undefined,
        error: errorText(problem) + ' 已保留原请求，请查询回执后再处理。' }));
    }
  }

  const projects = bootstrap?.projects || [];
  const filteredProjects = projects.filter(project => project.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const currentProject = projects.find(project => project.id === selectedId);
  const allPending = (bootstrap?.reviews || []).filter(review => review.status === 'pending');
  const projectPending = allPending.filter(review => !review.projectId || review.projectId === selectedId);
  const shownReviews = reviewAll ? allPending : projectPending;
  const reminders = bootstrap?.reminders || [];
  const unreadReminders = reminders.filter(reminder => reminder.displayState === 'unread');
  const items = summary?.details.items || [];
  const actionableItems = items.filter(item => !['closed', 'cancelled', 'paused'].includes(item.businessState));
  const amItem = items.find(item => item.id === am.itemId);
  const people = (amItem?.assignees || []).map(person => typeof person === 'string'
    ? { id: person, name: am.preview?.target.attention?.find(candidate => candidate.id === person)?.name }
    : person);
  const recipientOptions = people.filter(person => person.name || person.displayName);
  if (am.result?.kind === 'choose_route') {
    for (const person of am.result.assignees || []) {
      if (person.name && !recipientOptions.some(candidate => candidate.id === person.id)) recipientOptions.push(person);
    }
  }
  if (am.preview?.target.channel === 'recipient_p2p' && !recipientOptions.some(person => person.id === am.preview!.target.id)) {
    recipientOptions.push({ id: am.preview.target.id, name: am.preview.target.name });
  }
  const summaryRows = (ROWS.map(key => summary?.rows.find(row => row.key === key)).filter(Boolean) as ProjectSummary['rows'])
    .map(row => {
      const entries = row.entries.map(entry => ({ ...entry, text: readableEntryText(entry, reviewTime) }));
      const moreEntries = row.moreEntries.map(entry => ({ ...entry, text: readableEntryText(entry, reviewTime) }));
      const hiddenExcerpt = entries.some((entry, index) => entry.text !== row.entries[index].text);
      return { ...row, entries, moreEntries, text: hiddenExcerpt ? entries.map(entry => entry.text).join('；') : row.text };
    });
  const sourceRows = pane?.kind === 'evidence'
    ? summaryRows.filter(row => !pane.row || row.key === pane.row)
    : [];
  const sourceItem = pane?.kind === 'evidence' && pane.itemId ? items.find(item => item.id === pane.itemId) : undefined;
  const paneTitle = pane?.kind === 'am' ? 'AM 建议与跟进'
    : pane?.kind === 'reviews' ? '待我判断'
    : pane?.kind === 'reminders' ? '需要关注'
    : pane?.kind === 'evidence' ? (sourceItem?.title || (pane.row ? LABELS[pane.row] + ' · 内容与依据' : '内容与依据')) : '';
  const coverage = summary?.coverage || bootstrap?.coverage;
  const continuity = bootstrap?.continuity;
  const continuationEntries = continuity?.attention || [];
  const visibleContinuation = continuationEntries.filter((entry, index) => entry.priority === 'P0' || index < 4);
  const moreContinuation = continuationEntries.filter(entry => !visibleContinuation.includes(entry));
  function openRegisteredItem(projectId: string, itemId: string) {
    setSelectedId(projectId);
    setFocusItemId(itemId);
    setPane({kind: 'evidence', itemId});
  }
  const continuityEntry = (entry: NonNullable<Bootstrap['continuity']>['attention'][number]) =>
    <li key={entry.id}>
      <div><button className="lw-link" type="button" onClick={() => openRegisteredItem(entry.projectId, entry.itemId)}>{entry.title}</button>
        <p>{entry.reason}</p><span className="lw-muted">{projects.find(project => project.id === entry.projectId)?.title} · {ITEM_STATUS[entry.businessState] || '状态待核对'}</span></div>
      <span className={entry.priority === 'P0' ? 'lw-attention' : 'lw-muted'}>{entry.priority}</span>
    </li>;

  return <section ref={sectionRef} className={'ledger-workbench ' + className} aria-label="项目台账工作台">
    <header className="lw-header">
      <div className="lw-heading"><h1>项目台账</h1></div>
      <div className="lw-header-actions">
        <button className="v2-button lw-quiet" type="button" onClick={() => openPane({ kind: 'reminders' })}
          aria-expanded={pane?.kind === 'reminders'} aria-controls={id + '-panel'}>
          需关注{unreadReminders.length ? ' ' + unreadReminders.length : ''}
        </button>
        <button className="v2-button lw-quiet" type="button" onClick={() => void refresh()}
          disabled={indexLoading || summaryLoading} aria-label="刷新台账">刷新</button>
      </div>
    </header>

    {continuity && !accessIssue ? <aside className="lw-continuity" aria-label="持续跟进概览">
      <div className="lw-continuity-heading"><h2>接着推进</h2>
        <span className="lw-muted">已登记未关闭 {continuity.openCount} · 等待反馈 {continuity.waitingCount}
          {continuity.uncertainDeliveryCount ? ' · 回执待核对 ' + continuity.uncertainDeliveryCount : ''}
          {continuity.needsReviewCount ? ' · 依据待重审 ' + continuity.needsReviewCount : ''}</span></div>
      {continuity.outside.length ? <section aria-label="项目外事项" className="lw-outside">
        <h3>项目外事项</h3>
        {continuity.outside.map(topic => <div key={topic.projectId} className="lw-outside-topic">
          <button className="lw-link" type="button" onClick={() => chooseProject(topic.projectId)}>{topic.title}</button>
          {topic.items.length ? <ul>{topic.items.map(item => <li key={item.id}>
            <button className="lw-link" type="button" onClick={() => openRegisteredItem(topic.projectId, item.id)}>{item.title}</button>
            <span className="lw-muted">{ITEM_STATUS[item.businessState] || '状态待核对'}{item.nextCheckAt ? ' · 下次核对 ' + humanTime(item.nextCheckAt) : ''}</span>
          </li>)}</ul> : <p className="lw-muted">当前没有已登记且未关闭的事项，可展开查看主题资料。</p>}
        </div>)}
      </section> : null}
      {visibleContinuation.length ? <section aria-label="跨项目关注"><h3>需要推进或核对</h3>
        <ul className="lw-continuation-list">{visibleContinuation.map(continuityEntry)}</ul>
        {moreContinuation.length ? <details><summary>其余 {moreContinuation.length} 条关注事项</summary>
          <ul className="lw-continuation-list">{moreContinuation.map(continuityEntry)}</ul></details> : null}
      </section> : <p className="lw-muted">当前可见的已登记事项中，没有新增需要你处理的动作。</p>}
      <p className="lw-continuity-time">读取于 {humanTime(continuity.generatedAt)}{indexIssue ? ' · 最新读取未完成，保留上次结果' : ''}</p>
    </aside> : null}

    <div className="lw-picker">
      <label className="lw-search"><span className="lw-sr-only">搜索项目或项目外主题</span>
        <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4" /></svg>
        <input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索项目或项目外主题" type="search" />
      </label>
      <label className="lw-project-select"><span className="lw-sr-only">选择项目或项目外主题</span>
        <select value={selectedId} onChange={event => chooseProject(event.target.value)} disabled={!projects.length}>
          {!projects.length ? <option value="">暂无可查看的项目</option> : null}
          {currentProject && !filteredProjects.some(project => project.id === selectedId)
            ? <option value={currentProject.id}>{currentProject.title}（当前）</option> : null}
          {filteredProjects.filter(project => project.kind === 'project').length ? <optgroup label="项目">
            {filteredProjects.filter(project => project.kind === 'project').map(project =>
              <option key={project.id} value={project.id}>{project.title}</option>)}
          </optgroup> : null}
          {filteredProjects.filter(project => project.kind === 'outside').length ? <optgroup label="项目外 · 按主题">
            {filteredProjects.filter(project => project.kind === 'outside').map(project =>
              <option key={project.id} value={project.id}>{project.title}</option>)}
          </optgroup> : null}
        </select>
      </label>
      {query && !filteredProjects.length ? <span className="lw-search-empty" role="status">没有匹配的项目或主题</span> : null}
    </div>

    {accessIssue ? <div className="lw-error" role="alert"><p>访问权限或来源范围已变化，请重新核对。{accessIssue}</p>
      <button className="v2-button" type="button" onClick={() => void refresh()}>重新核对访问</button></div> : null}
    {error && !accessIssue ? <div className="lw-error" role="alert"><p>{error}</p><button className="v2-button" type="button" onClick={() => void refresh()}>重新读取</button></div> : null}
    {indexIssue || summaryIssue ? <div className="lw-error" role="status">
      <div><p>{summary ? '最新资料暂未读到，以下保留上次读取结果。' : '资料尚未读取完整。'}</p>
        <details><summary>查看读取缺口</summary><p>{[indexIssue, summaryIssue].filter(Boolean).join('；')}</p></details></div>
      <button className="v2-button" type="button" onClick={() => void refresh()}>重新读取</button>
    </div> : null}
    {notice ? <p className="lw-notice" role="status">{notice}</p> : null}

    {summary ? <>
      <div className="lw-project-heading">
        <div><h2>{summary.project.title}</h2><span className="lw-muted">{summary.project.kind === 'outside' ? '项目外主题' : PROJECT_STATUS[summary.project.status] || '状态待核对'}</span></div>
        <div className="lw-update">{summaryLoading ? <Busy>正在更新…</Busy>
          : <span>{coverage?.checkedAt ? '资料核对于 ' + humanTime(coverage.checkedAt) : '摘要生成于 ' + humanTime(summary.generatedAt)}</span>}
          {coverage?.reasons?.length ? <button className="lw-link" type="button" onClick={() => setPane({ kind: 'evidence' })}>有资料需核对</button> : null}
        </div>
      </div>
      <dl className="lw-summary" aria-label="三十秒项目摘要" aria-busy={summaryLoading}>
        {summaryRows.map(row => {
          const hasFocusedItem = !!focusItemId && [...row.entries, ...row.moreEntries].some(entry => entry.itemId === focusItemId);
          return <div key={row.key} className={'lw-summary-row lw-severity-' + row.severity + (hasFocusedItem ? ' lw-located' : '')}
            data-row={row.key}>
            <dt><span className="lw-row-marker" aria-hidden="true" />{LABELS[row.key]}</dt>
            <dd><p>{row.text}</p></dd>
            <dd className="lw-row-action"><button className="lw-link lw-row-more" type="button" onClick={() => setPane({ kind: 'evidence', row: row.key })}
              aria-label={'展开' + LABELS[row.key] + '的完整内容和依据'}>
              {row.moreEntries.length ? '另 ' + row.moreEntries.length + ' 条' : '依据'}
            </button></dd>
          </div>;
        })}
      </dl>
      <div className="lw-main-actions">
        <button className="v2-button primary" type="button" onClick={() => openPane({ kind: 'am' })}
          aria-expanded={pane?.kind === 'am'} aria-controls={id + '-panel'}>请 AM 建议下一步</button>
        <button className="v2-button" type="button" onClick={() => openPane({ kind: 'reviews' })}
          aria-expanded={pane?.kind === 'reviews'} aria-controls={id + '-panel'}>
          待我判断{allPending.length ? ' ' + allPending.length : ''}
        </button>
        <span className="lw-muted lw-auto-note">明确的信息自动归集；有疑点才请你判断</span>
      </div>
    </> : indexLoading || summaryLoading ? <div className="lw-loading"><Busy>正在读取项目台账…</Busy></div>
      : <div className="lw-empty"><h2>{accessIssue ? '访问范围需要重新核对' : '选择项目后，在这里查看四项摘要'}</h2>
        {!accessIssue ? <p>已归集的项目外信息会按主题放在同一个选择器中。</p> : null}</div>}

    {pane ? <section id={id + '-panel'} className="lw-panel" aria-labelledby={id + '-panel-title'}>
      <header className="lw-panel-header"><h3 id={id + '-panel-title'} ref={paneHeadingRef} tabIndex={-1}>{paneTitle}</h3>
        <button className="lw-close" type="button" aria-label="收起展开区" onClick={() => setPane(null)}>收起 <span aria-hidden="true">×</span></button>
      </header>

      {pane.kind === 'evidence' ? <div>
        {coverage?.reasons?.length ? <aside className="lw-coverage"><p>资料覆盖情况</p><ul>{coverage.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul></aside> : null}
        {sourceRows.map(row => {
          const entries = [...row.entries, ...row.moreEntries].filter(entry => !pane.itemId || entry.itemId === pane.itemId);
          return entries.length || !pane.itemId ? <section key={row.key} className="lw-evidence-section">
            <h4>{LABELS[row.key]}</h4><SourceEntries entries={entries} />
          </section> : null;
        })}
        {processingGaps.length ? <section className="lw-evidence-section">
          <h4>待整理信息</h4><p className="lw-muted">这些反馈尚未形成可用结论，原文保留在这里供查看。</p>
          <div className="lw-source-entries">{processingGaps.map(gap => <article className="lw-source-entry" key={gap.id}>
            <p>{readableEntryText(gap, reviewTime)}</p>
            <details><summary>查看原始依据</summary><EvidenceList evidence={gap.sourceRefs} /></details>
          </article>)}</div>
        </section> : null}
        {pane.itemId && !sourceRows.some(row => [...row.entries, ...row.moreEntries].some(entry => entry.itemId === pane.itemId))
          ? <p className="lw-muted">该事项尚未关联到四行摘要，已保留原事项供核对。</p> : null}
        {sourceItem && !['closed', 'cancelled', 'paused'].includes(sourceItem.businessState)
          ? <button className="v2-button" type="button" onClick={() => { chooseAMItem(sourceItem.id); setPane({ kind: 'am' }); }}>请 AM 分析这件事</button> : null}
      </div> : null}

      {pane.kind === 'reviews' ? <div>
        <div className="lw-pane-toolbar"><p className="lw-muted">每条只判断当前疑点，原文保留在下方。</p>
          <label className="lw-checkbox"><input type="checkbox" checked={reviewAll} onChange={event => setReviewAll(event.target.checked)} />查看全部待审</label></div>
        {!shownReviews.length ? <p className="lw-empty-copy">{allPending.length ? '当前项目没有待审；可勾选“查看全部待审”。' : '暂时没有需要你判断的疑点。'}</p>
          : <div className="lw-review-list">{shownReviews.map(review => {
            const expired = review.evidence.some(source => rawExpired(source, reviewTime));
            return <article key={review.id} className="lw-review">
            <h4>{review.question}</h4><p className="lw-muted">{reviewReason(review.reason)}</p>
            {review.excerpt && review.evidence.length > 0 && !expired && review.evidence.every(source => source.rawAvailable) ? <blockquote>{review.excerpt}</blockquote> : null}
            {expired ? <p className="lw-attention">原文已到期，请刷新来源后再判断。</p> : null}
            <details><summary>展开来源</summary><EvidenceList evidence={review.evidence} /></details>
            <div className="lw-review-action"><label><span className="lw-sr-only">选择这条疑点的处理方式</span>
              <select value={reviewChoices[review.id] || ''} onChange={event => setReviewChoices(current => ({ ...current, [review.id]: event.target.value }))} disabled={mutating[review.id] || expired}>
                <option value="">请选择你的判断</option>{review.choices.map(choice => <option key={choice.id} value={choice.id}>{choice.label}</option>)}
              </select></label>
              <button className="v2-button" type="button" disabled={!reviewChoices[review.id] || mutating[review.id] || expired} onClick={() => void resolveReview(review)}>
                {mutating[review.id] ? '保存中…' : '确认这条判断'}</button>
            </div>
          </article>;
          })}</div>}
      </div> : null}

      {pane.kind === 'reminders' ? <div>
        <p className="lw-muted">提醒关联原事项；可以查看、标记读过或安排稍后提醒。</p>
        {!reminders.length ? <p className="lw-empty-copy">当前没有需要显示的提醒。</p>
          : <ul className="lw-reminder-list">{reminders.map(reminder => <li key={reminder.id} className={'lw-reminder lw-reminder-' + reminder.displayState}>
            <div className="lw-reminder-copy"><h4>{reminder.title}{reminder.displayState === 'unread' ? <span className="lw-unread" aria-label="未读" /> : null}</h4>
              <p>{reminder.body}</p><p className="lw-meta">{projects.find(project => project.id === reminder.projectId)?.title || '关联事项'}
                {reminder.dueAt ? ' · ' + humanTime(reminder.dueAt) : ''}
                {reminder.displayState === 'snoozed' ? ' · 稍后至 ' + humanTime(reminder.snoozedUntil) : reminder.displayState === 'read' ? ' · 已读' : ''}
              </p></div>
            <div className="lw-reminder-actions"><button className="v2-button" type="button" onClick={() => locate(reminder)}>定位</button>
              <button className="lw-link" type="button" disabled={reminder.displayState === 'read' || mutating[reminder.id]} onClick={() => void changeReminder(reminder, 'ack')}>已读</button>
              <button className="lw-link" type="button" disabled={mutating[reminder.id]} onClick={() => void changeReminder(reminder, 'snooze')}>稍后 1 小时</button>
            </div>
          </li>)}</ul>}
      </div> : null}

      {pane.kind === 'am' ? <div className="lw-am">
        <div className="lw-am-select"><label htmlFor={id + '-am-item'}>要跟进哪件事</label>
          <select id={id + '-am-item'} value={am.itemId} onChange={event => chooseAMItem(event.target.value)} disabled={!!am.busy || !!am.requestId}>
            <option value="">请选择已存在的事项</option>
            {items.map(item => <option value={item.id} key={item.id} disabled={['closed', 'cancelled', 'paused'].includes(item.businessState)}>
              {item.title}{item.businessState === 'closed' ? '（已结束）' : item.businessState === 'cancelled' ? '（已取消）' : item.businessState === 'paused' ? '（已暂停）' : ''}</option>)}
          </select>
          {!am.requestId && am.result?.kind !== 'choose_route' ? <button className="v2-button" type="button" onClick={() => void prepareAM()} disabled={(!am.itemId && actionableItems.length > 0) || !!am.busy}>
            {am.busy === 'prepare' ? '分析中…' : am.result ? '重新获取建议' : '获取建议'}</button> : null}
        </div>
        {!items.length ? <p className="lw-muted">当前摘要还没有绑定可跟进的原事项。请先通过待审明确关联。</p> : null}
        {am.result ? <div className="lw-am-advice"><h4>{am.result.recommendation}</h4><p>{am.result.reason}</p>
          {am.result.kind === 'wait' && am.result.nextCheckAt ? <p className="lw-meta">下次检查：{humanTime(am.result.nextCheckAt)}</p> : null}
        </div> : null}
        {am.result?.kind === 'choose_route' ? <div className="lw-route-choice">
          <div className="lw-target-edit"><label>跟进方式<select value={am.channel} disabled={!!am.busy}
            onChange={event => editDraft({ channel: event.target.value as AMChannel, recipientId: '' })}>
            {am.result.allowedChannels.map(channel => <option key={channel} value={channel}>{channel === 'group' ? '项目群' : '个人私聊'}</option>)}
          </select></label>
          {am.channel === 'recipient_p2p' && recipientOptions.length ? <label>收件人<select value={am.recipientId} disabled={!!am.busy}
            onChange={event => editDraft({ recipientId: event.target.value })}>
            <option value="">选择已核实的责任人</option>{recipientOptions.filter(person => am.result?.kind === 'choose_route' && am.result.assigneeIds.includes(person.id))
              .map(person => <option key={person.id} value={person.id}>{person.name || person.displayName}</option>)}
          </select></label> : null}</div>
          {am.channel === 'recipient_p2p' && !recipientOptions.length
            ? am.result.assigneeIds.length === 1
              ? <button className="v2-button" type="button" disabled={!!am.busy} onClick={() => {
                if (am.result?.kind === 'choose_route') void prepareAM({ channel: 'recipient_p2p', recipientId: am.result.assigneeIds[0] });
              }}>核实台账唯一责任人的私聊对象</button>
              : <p className="lw-muted">当前还没有可确认姓名的跟进对象，请先核实责任人和消息渠道映射。</p>
            : <button className="v2-button" type="button" disabled={!!am.busy || (am.channel === 'recipient_p2p' && !am.recipientId)}
              onClick={() => void prepareAM()}>{am.busy === 'prepare' ? '核实中…' : '按此对象生成预览'}</button>}
        </div> : null}
        {am.error ? <p role="alert" className="lw-error-text">{am.error}</p> : null}

        {am.preview && !am.requestId ? <div className="lw-preview">
          <div className="lw-preview-top"><h4>本次跟进预览</h4><span className="lw-muted">共 {am.preview.count} 条消息</span></div>
          <dl className="lw-preview-meta"><div><dt>发送给</dt><dd>{am.preview.target.name}
            {am.preview.target.attention?.length ? <span className="lw-muted"> · 提醒 {am.preview.target.attention.map(person => person.name).join('、')}</span> : null}
          </dd></div><div><dt>发送安排</dt><dd>{am.preview.sendWindow.immediate ? '你确认后执行' : humanTime(am.preview.sendWindow.notBeforeMs)}
            <span className="lw-muted"> · 本预览有效至 {humanTime(am.preview.expiresAtMs)}</span></dd></div></dl>
          <div className="lw-target-edit"><label>发送方式<select value={am.channel} onChange={event => editDraft({ channel: event.target.value as AMChannel, recipientId: '' })} disabled={!!am.busy}>
            <option value="group">项目群</option><option value="recipient_p2p">个人私聊</option></select></label>
            {am.channel === 'recipient_p2p' ? <label>收件人<select value={am.recipientId} onChange={event => editDraft({ recipientId: event.target.value })} disabled={!!am.busy}>
              <option value="">{recipientOptions.length ? '选择责任人' : '尚无可选的已核实责任人'}</option>{recipientOptions.map(person => <option key={person.id} value={person.id}>{person.name || person.displayName}</option>)}
            </select></label> : null}
          </div>
          <label className="lw-message-label" htmlFor={id + '-am-body'}>消息正文</label>
          <textarea ref={messageRef} id={id + '-am-body'} value={am.body} onChange={event => editDraft({ body: event.target.value })} rows={5} maxLength={4000} disabled={!!am.busy} />
          <p className="lw-meta">发送后：{am.preview.followup}</p>
          <div className="lw-preview-actions">
            {dirty ? <><button className="v2-button primary" type="button" onClick={() => void reviseAM()}
              disabled={!!am.busy || !am.body.trim() || (am.channel === 'recipient_p2p' && !am.recipientId)}>
              {am.busy === 'revise' ? '更新中…' : '更新预览'}</button><span className="lw-muted">改动后重新预览，再确认执行。</span></>
              : <><button className="v2-button primary" type="button" onClick={() => void approveAM()}
                disabled={!am.presentation || !!am.busy || !!am.error}>确认并执行本次跟进</button>
                {am.busy === 'present' ? <Busy>登记当前预览…</Busy> : am.presentation ? <span className="lw-muted">对象与正文已完整展示</span>
                  : <button className="lw-link" type="button" onClick={() => void presentPreview(selectedId, am.preview!)} disabled={!!am.busy}>重新登记预览</button>}
              </>}
          </div>
        </div> : null}

        {am.requestId ? <div className="lw-receipt" role="status"><h4>{am.busy === 'approve' ? '正在登记你的确认…' : am.receipt ? RECEIPT_STATUS[am.receipt.state] || '正在核对执行状态' : '需要核对原请求回执'}</h4>
          {am.receipt?.reason ? <p>{receiptReason(am.receipt.reason)}</p> : null}
          {am.receipt?.readbackState ? <p className="lw-meta">回执核对：{
            am.receipt.readbackState === 'verified' && !['sent_confirmed', 'readback_verified'].includes(am.receipt.state)
              ? '已有核对记录，原发送依据仍待确认'
              : READBACK_STATUS[am.receipt.readbackState] || RECEIPT_STATUS[am.receipt.readbackState] || '待核对'
          }</p> : null}
          <p className="lw-muted">项目进展与完成状态继续依据台账事实更新。</p>
          <button className="v2-button" type="button" onClick={() => void checkReceipt()} disabled={!!am.busy}>
            {am.busy === 'receipt' ? '查询中…' : '查询原请求回执'}</button>
          {am.receipt && !['unknown', 'sending', 'running'].includes(am.receipt.state)
            ? <button className="lw-link" type="button" onClick={() => updateAM(selectedId, () => emptyAM())}>保留本次回执，跟进另一件事</button> : null}
        </div> : null}
        {tickets.some(ticket => ticket.projectId === selectedId) ? <details className="lw-recent-requests">
          <summary>已登记的跟进 · {tickets.filter(ticket => ticket.projectId === selectedId).length}</summary>
          <ul>{tickets.filter(ticket => ticket.projectId === selectedId).slice().reverse().map(ticket =>
            <li key={ticket.requestId}><span>{items.find(item => item.id === ticket.itemId)?.title || '原跟进事项'}</span>
              <button className="lw-link" type="button" disabled={!!am.busy} onClick={() => {
                updateAM(selectedId, () => ({ ...emptyAM(), itemId: ticket.itemId, requestId: ticket.requestId }));
                void checkReceipt(selectedId, ticket.requestId);
              }}>查看原回执</button></li>)}</ul>
        </details> : null}
      </div> : null}
    </section> : null}
  </section>;
}

export default LedgerWorkbench;

