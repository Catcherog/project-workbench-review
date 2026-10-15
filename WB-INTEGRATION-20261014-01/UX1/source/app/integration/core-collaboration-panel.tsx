"use client";
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  admissionKey, approvalKey, authorityCommand, canApprove, canChangeAuthority, canEdit,
  cancelCommand, decisionCommand, draftChanged, draftStale, draftsFromView, editCommand,
  executeCommand, executionPlan, messageKey, needsReconcile, noticeLabel, ownerLabel,
  prepareCommand, recipientId, reconcileCommand, stagePresentation,
  type Approval, type Batch, type CoreCommand, type CoreRequest, type CoreView, type EditDraft,
  type Message, type Proof,
} from './core-collaboration-model';
import { explainError, performCoreCommand, readCoreView, ScopeEpoch } from './core-collaboration-client';
import { receiptTimestamp } from './receipt-presentation';
import { ActionFeedback } from './action-feedback';

type Props = {
  workspaceId: string; sourceId?: string; revision?: number; request: CoreRequest;
  onChanged?: () => Promise<unknown>;
  /** Q01 accepted in DEV1: separate decision/save and batch execution. No external-send authorization. */
  executionUiConfirmed?: boolean;
};
type EditState = { workspaceId: string; values: Record<string, EditDraft> };
const storageKey = (workspaceId: string) => 'wb-integration:message-drafts:v1:' + workspaceId;
function readEdits(workspaceId: string): EditState {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem(storageKey(workspaceId)) || '{}');
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {workspaceId, values: {}};
    const values: Record<string, EditDraft> = {};
    for (const [key, value] of Object.entries(raw)) {
      if (value && typeof value === 'object' && ['fingerprint','text','recipientId'].every(k => typeof (value as Record<string, unknown>)[k] === 'string')) values[key] = value as EditDraft;
    }
    return {workspaceId, values};
  } catch { return {workspaceId, values: {}}; }
}
function ProofList({proof}: {proof?: Proof[]}) {
  return proof?.length ? <ul className="wb-int-proof-list">{proof.map((p, i) => <li key={JSON.stringify([p.sourceId,p.attachmentId,i])}>
    <code>{p.sourceId}</code>{p.attachmentId && <span> · 原图身份 {p.attachmentId}</span>}
    {p.quote && <blockquote>{p.quote}</blockquote>}
  </li>)}</ul> : <p className="wb-int-muted">未返回该记录的依据原文；不补造历史。</p>;
}
function ApprovalHistory({history}: {history?: Approval[]}) {
  return <details className="wb-int-history"><summary>批准历史 · {history?.length || 0} 条</summary>
    {!history?.length && <p className="wb-int-muted">当前没有可读取的批准历史；不据此推断已发送。</p>}
    {history?.map((h, i) => <article key={JSON.stringify([h.at,h.fingerprint,i])}>
      <h4>{receiptTimestamp(h.at)}</h4>
      <p>当时收件人：{h.recipient ? h.recipient.name + ' · ' + (h.recipient.channel === 'group' ? '群聊' : '私聊') : '历史收件人未提供'}</p>
      <p className="wb-int-full-text">{typeof h.text === 'string' ? h.text : '历史完整正文未提供；不能用当前正文冒充。'}</p>
      <p className="wb-int-muted">批准指纹：<code>{h.fingerprint || '未提供'}</code></p>
      <ProofList proof={h.proof}/>
    </article>)}
  </details>;
}
function resultCopy(action: string): string {
  switch (action) {
    case 'prepare-messages': return '完整预览已保存；尚未批准或发送。';
    case 'decide-messages': return '所选决定已保存；本次没有发送消息。';
    case 'execute-messages': return '执行请求已返回；请逐条查看发送与回读结果，不代表业务完成。';
    case 'reconcile-messages': return '已查询原发送结果；结果未知的消息没有自动重发。';
    case 'message-authority': return '执行权请求已处理；接手或交回不表示发送成功。';
    default: return '操作请求已返回；请查看当前记录。';
  }
}

/** Replacement for the original export, keeping every existing caller and transport contract. */
export function CoreCollaborationPanel({workspaceId, sourceId, revision, request, onChanged, executionUiConfirmed = true}: Props) {
  const [view, setView] = useState<CoreView | null>(null);
  const [loading, setLoading] = useState(true), [fresh, setFresh] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [feedback, setFeedback] = useState('');
  const [feedbackTarget, setFeedbackTarget] = useState('panel');
  const [selected, setSelected] = useState<Set<string>>(new Set()), [admissions, setAdmissions] = useState<Set<string>>(new Set());
  const [draftsSelected, setDraftsSelected] = useState<Set<string>>(new Set());
  const [editState, setEditState] = useState<EditState>(() => readEdits(workspaceId));
  const [fields, setFields] = useState<Record<string,string>>({});
  const [filter, setFilter] = useState<'all' | 'review' | 'results'>('all');
  const [pending, setPending] = useState<CoreCommand | null>(null);
  const [focusTarget,setFocusTarget]=useState<string|null>(null);
  const messageNodes=useRef(new Map<string,HTMLElement>());
  const epoch = useRef(new ScopeEpoch()), busyTicket = useRef<number | null>(null), refreshQueued = useRef(false);
  const callback = useRef(onChanged); callback.current = onChanged;
  const edits = editState.workspaceId === workspaceId ? editState.values : {};
  const scope = JSON.stringify([workspaceId, sourceId || '']);
  const previousScope = useRef(scope);
  useEffect(() => {
    // Local storage is a draft cache, never a message/save/send ledger.
    try { sessionStorage.setItem(storageKey(editState.workspaceId), JSON.stringify(editState.values)); } catch { /* Keep the draft in this mounted UI. */ }
  }, [editState]);
  const load = useCallback(async () => {
    if (busyTicket.current !== null) { refreshQueued.current = true; return; }
    refreshQueued.current = false;
    const ticket = epoch.current.advance(); setLoading(true); setFresh(false);
    try { const next = await readCoreView(request, workspaceId, sourceId); if (epoch.current.isCurrent(ticket)) { setView(next); setFresh(true); } }
    catch (cause) { if (epoch.current.isCurrent(ticket)) setError('无法读取最新协作记录：' + explainError(cause)); }
    finally { if (epoch.current.isCurrent(ticket)) setLoading(false); }
  }, [request, workspaceId, sourceId]);
  useEffect(() => {
    if (previousScope.current !== scope) {
      previousScope.current = scope; busyTicket.current = null; setBusy(false); setView(null);
      setSelected(new Set()); setAdmissions(new Set()); setDraftsSelected(new Set());
      setFields({}); setFeedback(''); setError(''); setFeedbackTarget('panel'); setPending(null); setEditState(readEdits(workspaceId)); setFilter('all');
    }
    void load();
  }, [scope, workspaceId, revision, load]);
  useEffect(() => () => { epoch.current.advance(); }, [scope]);
  useEffect(()=>{
    if(!focusTarget)return;
    const node=messageNodes.current.get(focusTarget);if(!node)return;
    const draft=node.querySelector<HTMLDetailsElement>('.wb-int-local-draft');if(draft)draft.open=true;
    node.scrollIntoView({block:'center'});
    (node.querySelector<HTMLElement>('textarea:not(:disabled),.wb-int-local-draft button')||node).focus({preventScroll:true});
    setFocusTarget(null);
  },[focusTarget,filter,view]);
  function locateMessage(batch:Batch,m:Message){setFilter('all');setFocusTarget(messageKey(batch.id,m.id));}
  useEffect(() => {
    if (!view) return;
    // Keep only choices still bound to a current version/state. Never select a replacement automatically.
    const approvalKeys = new Set(view.runs.flatMap(batch => batch.items.filter(canApprove).map(m => approvalKey(batch.id,m))));
    const admissionKeys = new Set(view.items.filter(item => item.core.admission === 'candidate').map(admissionKey));
    const draftKeys = new Set(draftsFromView(view).map(draft => draft.id));
    const retain = (old: Set<string>, valid: Set<string>) => {
      const next = new Set([...old].filter(key => valid.has(key)));
      return next.size === old.size ? old : next;
    };
    setSelected(old => retain(old,approvalKeys));
    setAdmissions(old => retain(old,admissionKeys));
    setDraftsSelected(old => retain(old,draftKeys));
  }, [view]);
  const disabled = busy || loading || !fresh || !view || previousScope.current !== scope;
  const toggle = (set: (fn: (old: Set<string>) => Set<string>) => void, key: string, checked: boolean) => set(old => { const next = new Set(old); if (checked) next.add(key); else next.delete(key); return next; });
  function putEdit(key: string, value?: EditDraft) {
    setEditState(old => { const values = {...(old.workspaceId === workspaceId ? old.values : {})}; if (value) values[key] = value; else delete values[key]; return {workspaceId, values}; });
  }
  function protect(build: () => CoreCommand, target = 'panel') {
    if (disabled || busyTicket.current !== null) return;
    setFeedbackTarget(target); setFeedback(''); setError('');
    try { void run(build()); } catch (cause) { setError(explainError(cause)); }
  }
  async function run(command: CoreCommand, retryOriginal = false) {
    if (busyTicket.current !== null || disabled) return;
    const ticket = epoch.current.advance(); busyTicket.current = ticket; setBusy(true); setError(''); setFeedback('');
    try {
      // An uncertain prepare/decision is retried only by explicit user action, after reading current facts, using the identical requestId/body.
      if (retryOriginal) await readCoreView(request, workspaceId, sourceId);
      if (!epoch.current.isCurrent(ticket)) return;
      const result = await performCoreCommand(request, workspaceId, sourceId, command);
      if (!epoch.current.isCurrent(ticket)) return;
      if (result.view) { setView(result.view); setFresh(true); } else setFresh(false);
      if (result.acknowledgement === 'unknown') {
        setPending(command);
        setFeedback('请求结果尚未完全核实；没有自动重试。' + (result.view ? '下方为当前回读记录。' : '先重新读取，勿重复提交。'));
      } else {
        setPending(null);
        if (result.acknowledgement === 'received') {
          setFeedback(resultCopy(command.action));
          if (command.action === 'prepare-messages') setDraftsSelected(new Set());
          if (command.action === 'decide-messages') {
            const batchId = String(command.sourceId);
            setSelected(old => new Set([...old].filter(key => { try { return JSON.parse(key)[0] !== batchId; } catch { return false; } })));
            const doneAdmissions = command.admissions as {id: string; expectedVersion: number}[] | undefined;
            setAdmissions(old => new Set([...old].filter(key => !doneAdmissions?.some(i => key === admissionKey({id:i.id,version:i.expectedVersion})))));
            if (result.view) for (const d of (command.decisions || []) as {id: string; action: string}[]) {
              if (d.action === 'edit' || d.action === 'cancel') putEdit(messageKey(batchId,d.id));
            }
          }
        }
      }
      if (result.operationError || result.readbackError) setError([
        result.operationError,
        result.readbackError && (result.acknowledgement === 'received' ? '操作已返回，但显示回读失败；只重新读取，不重新提交：' : '当前记录回读失败：') + result.readbackError,
      ].filter(Boolean).join('；'));
      if (result.acknowledgement === 'received') {
        try { await callback.current?.(); }
        catch { if (epoch.current.isCurrent(ticket)) setError('操作已返回，外层页面刷新失败；请重新读取，不重复提交。'); }
      }
    } catch (cause) { if (epoch.current.isCurrent(ticket)) setError(explainError(cause) + '；未自动重放原请求。'); }
    finally { if (busyTicket.current === ticket) { busyTicket.current = null; setBusy(false); if (refreshQueued.current) void load(); } }
  }
  function renderFeedback(target: string, context: string) {
    if (feedbackRegion !== target) return null;
    return <ActionFeedback context={context} busy={busy} message={feedback || (pending ? '请求结果尚未完全核实；请核对原请求。' : '')} error={error}>
      {pending && <section className="wb-int-warning" aria-label="尚未核实的请求">
        <p>上次{pending.action==='decide-messages'?'保存决定':pending.action==='prepare-messages'?'准备预览':'操作'}的结果尚未核实。继续时先查询同一次操作，不会自动重新提交。</p>
        <details><summary>原请求详情</summary><p>{pending.action} · {String(pending.requestId||'')}</p></details>
        {typeof pending.requestId === 'string' && ['decide-messages','prepare-messages'].includes(pending.action) && <button type="button" disabled={!!disabled} onClick={() => void run(pending,true)}>先查询，再按原身份核实／续办</button>}
        <button type="button" disabled={!!disabled} onClick={() => {setPending(null);setSelected(new Set());setFeedback('继续以已回读的当前状态操作；没有重放上一请求，也未把未知结果当作成功。');}}>已核对当前状态，继续（不重试）</button>
      </section>}
    </ActionFeedback>;
  }
  const drafts = view ? draftsFromView(view) : [];
  const messages = view?.runs.flatMap(b => b.items) || [];
  const pendingCount = messages.filter(m => ['pending_review','needs_preview','blocked'].includes(m.stage)).length;
  const shownInFilter = (m: Message) => filter === 'all' || (filter === 'review' ? ['pending_review','needs_preview','blocked'].includes(m.stage) : !['pending_review','needs_preview','blocked'].includes(m.stage));
  let feedbackRegion = feedbackTarget;
  // A completed action can remove its card from the current filter. Keep its
  // feedback in the same batch (or the panel if its whole source has disappeared).
  const feedbackBatch = view?.runs.find(b => b.id === feedbackTarget || 'execute:' + b.id === feedbackTarget || b.items.some(m => messageKey(b.id,m.id) === feedbackTarget));
  if (feedbackBatch?.items.some(m => messageKey(feedbackBatch.id,m.id) === feedbackTarget && !shownInFilter(m))) feedbackRegion = feedbackBatch.id;
  if (feedbackBatch && feedbackTarget === 'execute:' + feedbackBatch.id && filter !== 'all') feedbackRegion = feedbackBatch.id;
  if (feedbackTarget === 'drafts' && !drafts.length || feedbackTarget.startsWith('input:') && !view?.inputs.some(i => 'input:' + i.id === feedbackTarget && ['budget_wait','waiting','failed','needs_association'].includes(i.status))) feedbackRegion = 'panel';
  if (feedbackTarget.startsWith('notice:') && !view?.notices.some(n => 'notice:' + n.id === feedbackTarget)) feedbackRegion = 'panel';
  if (feedbackTarget !== 'panel' && feedbackTarget !== 'drafts' && !feedbackTarget.startsWith('input:') && !feedbackTarget.startsWith('notice:') && !feedbackBatch) feedbackRegion = 'panel';
  function messageCard(batch: Batch, m: Message) {
    const key = messageKey(batch.id,m.id), edit = edits[key];
    const currentDraft: EditDraft = edit || {fingerprint:m.fingerprint,text:m.text,recipientId:recipientId(m)};
    const presentation = stagePresentation(m), editable = canEdit(m), stale = draftStale(m, edit);
    const options = m.recipient.channel === 'group' ? view!.groups : view!.people;
    const changes=['交付物','负责人','计划日期','要求日期','交付要求'].flatMap(label=>{
      const before=m.previewChanges?.previous?.target?.[label],after=m.previewChanges?.current?.target?.[label];
      return JSON.stringify(before)===JSON.stringify(after)?[]:[{label,before,after}];
    });
    return <article className="wb-int-message" key={key} tabIndex={-1} ref={node=>{if(node)messageNodes.current.set(key,node);else messageNodes.current.delete(key);}} data-tone={presentation.tone} data-message-id={m.id}>
      <header className="wb-int-message-heading"><div><h4>{m.nodeName ? m.nodeName + ' · ' : ''}{m.title}</h4>{sourceId && m.workItemId !== sourceId && <p className="wb-int-muted">同批其他事项</p>}</div>
        <span className="wb-int-tag" data-tone={presentation.tone}>{presentation.label}</span>
      </header>
      <p>{m.recipient.name} · {m.recipient.channel === 'group' ? '群聊' : '私聊'} · {ownerLabel(m)}</p>
      {canApprove(m) && <label className="wb-int-check"><input type="checkbox" disabled={!!disabled || !!pending || stale || draftChanged(m,edit)} checked={selected.has(approvalKey(batch.id,m))} onChange={e => toggle(setSelected,approvalKey(batch.id,m),e.target.checked)}/>批准这一版完整消息（不等于纳入事项）</label>}
      {editable ? <div className="wb-int-editor">
        <label>收件范围<select aria-label={'收件范围 ' + m.title} disabled={!!disabled || !!pending} value={currentDraft.recipientId} onChange={e => putEdit(key,{...currentDraft,recipientId:e.target.value})}>
          {!options.some(p => p.id === currentDraft.recipientId) && <option value={currentDraft.recipientId}>{m.recipient.name}（当前范围未列出，需核实）</option>}
          {options.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}
        </select></label>
        <label>完整正文<textarea aria-label={'完整正文 ' + m.title} rows={4} maxLength={4000} disabled={!!disabled || !!pending} value={currentDraft.text} onChange={e => putEdit(key,{...currentDraft,text:e.target.value})}/></label>
        {stale && <p role="status">这份本地草稿基于旧预览，尚未覆盖较新内容。先阅读下方当前正文，再选择如何继续。</p>}
        {stale && <details><summary>当前服务器正文与收件人</summary><p>{m.recipient.name}</p><p className="wb-int-full-text">{m.text}</p><button type="button" disabled={!!disabled || !!pending} onClick={() => putEdit(key,{...currentDraft,fingerprint:m.fingerprint})}>保留草稿，以当前版本重新核对</button></details>}
        <div className="wb-int-actions">
          <button type="button" disabled={!!disabled || !!pending || stale} onClick={() => protect(() => editCommand(batch,m,currentDraft,crypto.randomUUID()),key)}>保存修改并回读预览</button>
          {edit && <button type="button" disabled={!!disabled || !!pending} onClick={() => putEdit(key)}>放弃本地修改，使用当前预览</button>}
          <button type="button" disabled={!!disabled || !!pending} onClick={() => protect(() => cancelCommand(batch,m,crypto.randomUUID()),key)}>取消此消息</button>
        </div>
      </div> : <p className="wb-int-full-text">{m.text}</p>}
      {edit && !editable && <details className="wb-int-history wb-int-local-draft">
        <summary>未提交的本地草稿（不是发送记录）</summary>
        <p className="wb-int-muted">消息当前只读。草稿仍保留，不覆盖服务器正文或已发事实；放弃草稿只清理本地编辑缓存。</p>
        <p>草稿收件范围：{options.find(p => p.id === edit.recipientId)?.title || edit.recipientId}</p>
        <p className="wb-int-full-text">{edit.text}</p>
        <button type="button" disabled={!!disabled || !!pending} onClick={() => putEdit(key)}>放弃这份本地草稿（不改变消息）</button>
      </details>}
      <details><summary>依据与记录详情</summary><p>本消息只发送上述正文；依据中的图片不会作为附件发送。</p><p>事项身份：<code>{m.workItemId}</code></p><p>当前预览指纹：<code>{m.fingerprint}</code></p><ProofList proof={m.proof}/>{m.messageId&&<p>原消息身份：<code>{m.messageId}</code></p>}</details>
      {changes.length>0 && <details><summary>本次业务前提变化</summary>{changes.map(({label,before,after})=><p key={label}>{label}：{String(before??'未提供')} → {String(after??'未提供')}</p>)}</details>}
      <ApprovalHistory history={m.approvalHistory}/>
      {canChangeAuthority(m) && <button type="button" disabled={!!disabled || !!pending} onClick={() => protect(() => authorityCommand(batch,m),key)}>{m.executionOwner === 'human' ? '明确交回系统（不立即发送）' : '这条由我执行'}</button>}
      {m.stage === 'sending' && <p className="wb-int-muted">已发起的请求可能仍在执行；接手不能撤回已发出的请求，先查询实际结果。</p>}
      {renderFeedback(key,'消息：' + m.title)}
      {m.error && <p className="wb-int-error" role="status">{m.error}</p>}
      {m.stage === 'sent' || m.stage === 'readback_verified' ? <p className="wb-int-muted">发送事实不表示已读、知晓、认可或业务完成。</p> : null}
    </article>;
  }
  return <details className="wb-int-collaboration" aria-label="协作消息预览">
    <summary>协作消息 · 待决定 {pendingCount} · 共 {messages.length} 条记录</summary>
    <div className="wb-int-body" aria-busy={busy || loading}>
      <header className="wb-int-toolbar"><p>先保存决定，再核对并执行发送。</p><button type="button" disabled={busy || loading} onClick={() => {setFeedbackTarget('panel');setFeedback('');setError('');void load();}}>重新读取当前记录</button></header>
      {loading && <p role="status">正在读取持久协作记录…</p>}
      {!fresh && view && <p role="status">当前显示的是上一份回读，操作已停用；请先重新读取。</p>}
      {renderFeedback('panel','协作记录')}
      {drafts.length > 0 && <details className="wb-int-section"><summary>待准备的协作草稿 · {drafts.length} 条</summary>
        <p className="wb-int-muted">每批最多 20 条；准备完整预览不会批准或发送。</p>
        {drafts.map(m => <article key={m.id} className="wb-int-draft">
          <label className="wb-int-check"><input type="checkbox" disabled={!!disabled || !!pending || !draftsSelected.has(m.id) && draftsSelected.size >= 20} checked={draftsSelected.has(m.id)} onChange={e => toggle(setDraftsSelected,m.id,e.target.checked)}/>{m.title} · {view?.people.find(p => p.id === m.recipientId)?.title || view?.groups.find(g => g.id === m.recipientId)?.title || '接收人待核实'}</label>
          <p className="wb-int-full-text">{m.text}</p>
          {m.channel === 'private' && view?.people.find(p => p.id === m.recipientId)?.identityVerified !== true && <div className="wb-int-editor">
            <label>完整姓名或工作邮箱<input disabled={!!disabled || !!pending} value={fields['query:'+m.id] || ''} onChange={e => setFields(old => ({...old,['query:'+m.id]:e.target.value}))}/></label>
            <button type="button" disabled={!!disabled || !!pending || !m.recipientId} onClick={() => protect(() => ({action:'resolve-recipient',personId:m.recipientId,query:fields['query:'+m.id] || ''}),'drafts')}>核对收件人身份</button>
          </div>}
        </article>)}
        <button type="button" disabled={!!disabled || !!pending || !draftsSelected.size} onClick={() => protect(() => prepareCommand(drafts,draftsSelected,crypto.randomUUID()),'drafts')}>准备所选完整预览 · {draftsSelected.size} 条</button>
        {renderFeedback('drafts','准备完整预览')}
      </details>}
      {!!view?.notices.length && <details className="wb-int-section"><summary>本人提醒回执 · {view.notices.length} 条</summary>{view.notices.map(n => <article key={n.id}>
        <h4>{n.title}</h4><small>{receiptTimestamp(n.createdAt)}</small>
        {Object.entries(n.channels).map(([channel,value]) => <p key={channel}>{channel === 'desktop' ? '电脑通知' : '飞书本人信息'}：{noticeLabel(channel,value)}{value.error ? ' · ' + value.error : ''}</p>)}
        <button type="button" disabled={!!disabled || !!pending} onClick={() => protect(() => ({action:'reconcile-notice',sourceId:n.id}),'notice:'+n.id)}>查询这轮提醒</button>{renderFeedback('notice:'+n.id,'本人提醒：'+n.title)}
      </article>)}</details>}
      {view?.inputs.filter(i => ['budget_wait','waiting','failed','needs_association'].includes(i.status)).map(i => <section key={i.id} className="wb-int-warning">
        <p>{i.status === 'budget_wait' ? '等待后台额度恢复' : i.status === 'waiting' ? '原输入已排队' : i.status === 'needs_association' ? '这条引用尚未关联事项' : '这条输入尚未处理完成'}：{i.excerpt}{i.error ? ' · ' + i.error : ''}</p>
        <p className="wb-int-muted">这是输入接收／处理状态，不代替业务保存回执。</p>
        {i.status === 'needs_association' && <><label>对应事项<select disabled={!!disabled || !!pending} value={fields['target:'+i.id] || ''} onChange={e => setFields(old => ({...old,['target:'+i.id]:e.target.value}))}>
          <option value="">请选择具体事项</option>{view.items.map(item => <option key={item.id} value={item.id}>{item.title} · {item.projectNames.join('、')}</option>)}
        </select></label><button type="button" disabled={!!disabled || !!pending || !fields['target:'+i.id]} onClick={() => protect(() => ({action:'associate-input',sourceId:i.id,targetId:fields['target:'+i.id],expectedVersion:i.version}),'input:'+i.id)}>关联并处理原输入</button></>}
        {renderFeedback('input:'+i.id,'关联原输入')}
      </section>)}
      {!!view?.runs.length && <nav className="wb-int-filters" aria-label="协作记录筛选">{(['all','review','results'] as const).map(value => <button type="button" key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{value === 'all' ? '全部记录' : value === 'review' ? '待决定' : '历史与结果'}</button>)}</nav>}
      {view?.runs.map(batch => {
        const shown = batch.items.filter(shownInFilter);
        // Entire batches are previewed; the backend execution scope cannot be narrowed by UI selection.
        const plan = executionPlan(batch,edits);
        const candidates = view.items.filter(i => i.core.admission === 'candidate' && batch.items.some(m => m.workItemId === i.id));
        const hasDecision = batch.items.some(m => selected.has(approvalKey(batch.id,m))) || candidates.some(i => admissions.has(admissionKey(i)));
        const blockedDrafts=batch.items.filter(m=>draftChanged(m,edits[messageKey(batch.id,m.id)])||draftStale(m,edits[messageKey(batch.id,m.id)]));
        if (!shown.length && filter !== 'all' && feedbackRegion !== batch.id) return null;
        return <section key={batch.id} className="wb-int-batch" aria-label={'协作批次 ' + batch.id}>
          <header><h3>{batch.projectNames.join('、') || '归属待核实'} · {batch.items.length} 条独立消息</h3><details><summary>批次记录详情</summary><code>{batch.id}</code><p>回读后失效的勾选会退出；新版需要重新核对和选择。</p></details></header>
          {!!candidates.length && <fieldset className="wb-int-admissions" disabled={!!disabled || !!pending}><legend>独立决定：候选纳入</legend>
            {candidates.map(i => <label className="wb-int-check" key={admissionKey(i)}><input type="checkbox" checked={admissions.has(admissionKey(i))} onChange={e => toggle(setAdmissions,admissionKey(i),e.target.checked)}/>将「{i.title}」纳入跟进（版本 {i.version}；不等于批准或发送消息）</label>)}
          </fieldset>}
          <div className="wb-int-decision-bar"><p>本次选择：批准 {batch.items.filter(m=>selected.has(approvalKey(batch.id,m))).length} 条消息；纳入 {candidates.filter(i=>admissions.has(admissionKey(i))).length} 个事项。</p><div className="wb-int-actions"><button type="button" disabled={!!disabled || !!pending || !hasDecision} onClick={() => protect(() => decisionCommand(batch,view,selected,admissions,edits,crypto.randomUUID()),batch.id)}>保存本批所选决定（不发送）</button>
            <button type="button" disabled={!!disabled} onClick={() => protect(() => reconcileCommand(batch),batch.id)}>查询本批实际发送结果</button>
            <button type="button" onClick={event=>{const section=event.currentTarget.closest('.wb-int-batch')?.querySelector<HTMLDetailsElement>('.wb-int-execution');if(section){section.open=true;section.scrollIntoView({block:'center'});section.querySelector<HTMLElement>('summary')?.focus({preventScroll:true});}}}>查看本批执行范围</button>
          </div>{renderFeedback(batch.id,'本批决定：' + (batch.projectNames.join('、') || '归属待核实'))}</div>
          {blockedDrafts.length>0&&<section className="wb-int-warning" aria-label="待处理的本地草稿"><p>以下消息有未保存或过期草稿，保存或明确放弃后才能继续本批操作：</p>{blockedDrafts.map(m=><p key={m.id}>{m.title}：{!canEdit(m)?'消息已只读，草稿仍保留':draftStale(m,edits[messageKey(batch.id,m.id)])?'预览已更新，需要重新核对草稿':'正文或收件人尚未保存'}。<button type="button" onClick={()=>locateMessage(batch,m)}>定位并处理：{m.title}</button></p>)}</section>}
          {shown.map(m => messageCard(batch,m))}
          {filter !== 'all' && <p className="wb-int-warning">当前有筛选，仅显示 {shown.length}/{batch.items.length} 条。发送必须切回全部记录核对完整批次。</p>}
          <details className="wb-int-execution"><summary>本批执行范围 · {plan.messages.length} 条{plan.retryCount ? '，其中明确未发重试 ' + plan.retryCount + ' 条' : ''}</summary>
            <p>执行接口按整批处理：本批已批准、执行权为系统且符合最新前提的消息。上方勾选仅决定批准范围，不是发送过滤器。</p>
            {plan.messages.map(m => <p key={m.id}>{m.title} → {m.recipient.name}{m.stage === 'failed_not_sent' ? '（已核实未发，将尝试原发送）' : ''}</p>)}
            {plan.reason && <p role="status">{plan.reason}</p>}
            {!executionUiConfirmed && <p role="status">PLAN1 Q01：发送按钮的分步交互待确认。本开发批次不启用发送入口。</p>}
            <button type="button" className="wb-int-primary" disabled={!!disabled || !!pending || filter !== 'all' || !plan.allowed || !executionUiConfirmed} onClick={() => { if (executionUiConfirmed && filter === 'all') protect(() => executeCommand(batch,edits),'execute:'+batch.id); }}>执行本批已批准消息 · {plan.messages.length} 条</button>
            {renderFeedback('execute:'+batch.id,'本批执行：' + (batch.projectNames.join('、') || '归属待核实'))}
          </details>
        </section>;
      })}
      {view && !view.runs.length && !drafts.length && <p>当前没有已准备的第三方消息；协作记录入口保留。</p>}
      {view && filter === 'review' && !pendingCount && <p>本次没有待决定消息。历史与结果仍可从上方入口查看。</p>}
    </div>
  </details>;
}
