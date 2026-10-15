"use client";

import React, { useEffect, useId, useRef, useState } from 'react';
import { ArrowUpRight, CalendarDays, ClipboardList, FileText, Loader2, Plus, RefreshCw, Send, Settings2, ShieldCheck, Square } from 'lucide-react';
import {InputImages,type InputImage} from './input-images';
import {CorePreparationResult} from './core-preparation-result';
import {CoreCollaborationPanel} from './work-item-core-controls';
import {WorkItemEntry} from './work-item-entry';
import type { V2State } from '../lib/v2-types';
import type { AssistantContextRef, AssistantCitation, AssistantCoverage, AssistantSession } from '../lib/assistant-contracts';
import './codex-assistant.css';
import { AssistantControls } from './assistant-controls';
import {AssistantActions} from './assistant-actions';
import {WorkItemAssistant} from './work-item-assistant';
import type {AssistantActionDraft} from '../lib/assistant-actions';

type Job = {
  id: string; workspaceId: string; sessionId: string; text: string; mode: 'answer' | 'draft';
  status: 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
  createdAt: string; updatedAt: string; events: { time: string; message: string }[];
  answer?: string; error?: string; groupId?: string; citations?: AssistantCitation[]; coverage?: AssistantCoverage[];
  model?: string; reasoningEffort?: string;
  actionRequests?:AssistantActionDraft[];
  workItemRequests?:unknown[];
  coreWorkOutcome?:{status:string;reason?:string};
  coreOutcome?:{status:string;duplicate?:boolean;applied:{sourceId:string;progressId:string}[];pending:{text:string}[];ambiguities:string[];receipt?:{operationId:string;sourceId:string}};
  gaps?: string[]; nextSteps?: string[]; conflicts?: { citationIds: string[]; reason: string }[];
  evidenceStatus?: 'current' | 'stale'; warnings?: string[];
  preview?: { availability: string; objects: { kind: string; id: string; action: string; before: Record<string, unknown>; after: Record<string, unknown>; reason: string }[]; recipients: string[]; files: unknown[] };
};
export type AssistantRequest = <T = unknown>(url: string, body?: unknown) => Promise<T>;
type Props = { s: V2State; request: AssistantRequest; onReview: (groupId: string) => Promise<void>; contextRef?: AssistantContextRef; onOpen?: (id:string)=>void; previewMode?:boolean;initialPrompt?:string };
type Input = { images?:InputImage[];attachmentIds?:string[];text: string; mode: 'answer' | 'draft'; requestId: string; sessionId: string; sourceIds: string[]; parentJobId?: string; retryOf?: string };
const errorText = (e: unknown) => e instanceof Error ? e.message : String(e);
const keyFor = (workspaceId: string, ref: AssistantContextRef) => `workbench-assistant:v2:${workspaceId}:${ref.kind}:${ref.id}`;
const fresh = (): Input => ({ text: '', mode: 'answer', requestId: crypto.randomUUID(), sessionId: crypto.randomUUID(), sourceIds: [] });
const labels = { running: '正在处理', completed: '已回答', failed: '处理失败', cancelled: '已取消', interrupted: '已中断' };
function savedInput(key: string): Input {
  const fallback = fresh();
  try { const saved = JSON.parse(localStorage.getItem(key) || 'null'); return saved && typeof saved.text === 'string' && typeof saved.sessionId === 'string' && typeof saved.requestId === 'string' && ['answer', 'draft'].includes(saved.mode) && Array.isArray(saved.sourceIds) ? saved : fallback; } catch { return fallback; }
}
const resolvedReview=(s:V2State,job:Job)=>s.changeGroups.some(group=>group.id===job.groupId&&['accepted','rejected','withdrawn'].includes(group.status));
const reviewLabel=(s:V2State,job:Job)=>({pending:'待审核修改已准备',conflict:'修改存在冲突，待核对',partial:'修改已部分接受',accepted:'修改已接受',rejected:'修改已拒绝',withdrawn:'修改已撤回'}[s.changeGroups.find(group=>group.id===job.groupId)?.status||'pending']);
function merge(jobs: Job[], job: Job) {
  const old = jobs.find(j => j.id === job.id);
  if (old && (old.updatedAt > job.updatedAt || old.status !== 'running' && job.status === 'running')) return jobs;
  return [...jobs.filter(j => j.id !== job.id), job].sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

/** Remount on workspace/object changes, so late HTTP responses cannot cross scopes. */
export function CodexAssistant(props: Props) {
  const source=props.contextRef?.kind==='sources'?props.s.sources.find(r=>r.id===props.contextRef?.id&&r.workItem):undefined;
  if(source)return <div className="ca-workspace ca-minimal"><WorkItemEntry key={props.s.workspaceId+':'+source.id} s={props.s} source={source} request={props.request} onReview={props.onReview}/></div>;
  return <AssistantScopePicker key={props.s.workspaceId + ':' + JSON.stringify(props.contextRef)} {...props} />;
}
function AssistantScopePicker(props: Props) {
  const { s } = props;
  const [scope, setScope] = useState<AssistantContextRef>(props.contextRef || { kind: 'workspace', id: s.workspaceId });
  const scopeControl=!props.contextRef ? <select aria-label="对话范围" value={scope.kind + ':' + scope.id} onChange={e => { const i = e.target.value.indexOf(':'); setScope({ kind: e.target.value.slice(0, i) as AssistantContextRef['kind'], id: e.target.value.slice(i + 1) }); }}>
      <option value={'workspace:' + s.workspaceId}>全部项目 / 专项</option>
      {(['projects', 'cases'] as const).flatMap(kind => s[kind].filter(r => !r.archived).map(r => <option key={kind + r.id} value={kind + ':' + r.id}>{kind === 'cases' ? '专项' : '项目'} · {r.title} · {r.code || r.id}</option>))}
    </select> : <span className="ca-fixed-scope">{scope.kind==='workspace'?s.workspaceName:s[scope.kind].find(row=>row.id===scope.id)?.title||'当前事项'}</span>;
  return <div className="ca-workspace ca-minimal">
    <Conversation key={keyFor(s.workspaceId, scope)} {...props} scope={scope} scopeControl={scopeControl}/>
  </div>;
}
function Conversation({ s, request, onReview,onOpen, scope, scopeControl, previewMode, initialPrompt }: Props & { scope: AssistantContextRef;scopeControl:React.ReactNode }) {
  const inputId = useId();
  const optionsId=useId(),textareaRef=useRef<HTMLTextAreaElement>(null);
  const storageKey = keyFor(s.workspaceId, scope);
  const [input, setInput] = useState(() => {const saved=savedInput(storageKey);return initialPrompt&&!saved.text?{...saved,text:initialPrompt}:saved;});
  const [sessions, setSessions] = useState<AssistantSession[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [readyKey, setReadyKey] = useState(''), [available, setAvailable] = useState(false);
  const [settledKey, setSettledKey] = useState(''), [sending, setSending] = useState(false);
  const [error, setError] = useState(''), [pollError, setPollError] = useState('');
  const [reload, setReload] = useState(0), [acting, setActing] = useState('');
  const [showOptions,setShowOptions]=useState(false);
  const alive = useRef(true), submitting = useRef(false);
  const scopeEpoch = useRef(0);
  const latest = jobs.at(-1), running = jobs.find(j => j.status === 'running');
  const runningId = running?.id;
  const loadKey = JSON.stringify([s.workspaceId, s.revision, input.sessionId, reload, scope.kind, scope.id]);
  const ready = readyKey === loadKey, loading = settledKey !== loadKey;
  const scopeSessions = sessions.filter(session => session.contextRef.kind === scope.kind && session.contextRef.id === scope.id);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { try { localStorage.setItem(storageKey, JSON.stringify(input)); } catch { /* Server history is still durable. */ } }, [input, storageKey]);
  useEffect(() => {
    let active = true;
    void Promise.all([request<{available:boolean;error?:string}>('/api/v2/codex/status'), request<{sessions:AssistantSession[]}>('/api/v2/codex/sessions?workspaceId=' + encodeURIComponent(s.workspaceId))]).then(async ([status, list]) => {
      if (!active) return;
      setAvailable(!!status.available); setError(status.available ? '' : status.error || '助手暂不可用');
      setSessions(list.sessions);
      const existing = list.sessions.find((v: AssistantSession) => v.id === input.sessionId && v.contextRef.kind === scope.kind && v.contextRef.id === scope.id);
      if (existing) { const value = await request<{jobs:Job[]}>(`/api/v2/codex/sessions/${encodeURIComponent(input.sessionId)}?workspaceId=${encodeURIComponent(s.workspaceId)}`); if (active) setJobs(value.jobs); }
      else setJobs([]);
      if (active) { setReadyKey(loadKey); setSettledKey(loadKey); }
    }).catch(cause => { if (active) { setError(errorText(cause)); setSettledKey(loadKey); } });
    return () => { active = false; };
  }, [request, s.workspaceId, input.sessionId, loadKey, scope.kind, scope.id]);
  useEffect(() => {
    if (!runningId) return;
    let active = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const value = await request<{job:Job}>(`/api/v2/codex/jobs/${runningId}?workspaceId=${encodeURIComponent(s.workspaceId)}`); if (active && value.job.sessionId === input.sessionId) { setJobs(js => merge(js, value.job)); setPollError(''); } }
      catch { if (active) setPollError('连接暂时中断，正在重新读取进度。'); }
      if (active) timer = setTimeout(poll, 800);
    };
    timer = setTimeout(poll, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [runningId, request, s.workspaceId, input.sessionId]);
  function changeSession(id:string = crypto.randomUUID()) { scopeEpoch.current++; setJobs([]); setError(''); setInput({ ...fresh(), sessionId: id }); }
  async function submit(retry?: Job) {
    if (submitting.current || running || !ready) return;
    const epoch = scopeEpoch.current;
    submitting.current = true; setSending(true); setError('');
    const value = retry ? input.retryOf === retry.id ? input : { ...input, text: retry.text, mode: retry.mode, requestId: crypto.randomUUID(), retryOf: retry.id, parentJobId: latest?.id || '' } : { ...input, parentJobId: input.parentJobId ?? latest?.id ?? '' };
    // Retain the same idempotency key after an uncertain HTTP result.
    setInput(value);
    try {
      const result = await request<{job:Job & {projectId:string}}>('/api/v2/codex/jobs', { ...value,attachmentIds:(value.images||[]).map(i=>i.id), workspaceId: s.workspaceId, contextRef: scope, parentJobId: value.parentJobId });
      if (!alive.current || epoch !== scopeEpoch.current) return;
      setJobs(js => merge(js, result.job)); setInput(v => ({ ...v, text: '',images:[], parentJobId: undefined, retryOf: undefined, requestId: crypto.randomUUID() }));
      if (!sessions.some(v => v.id === input.sessionId)) setSessions(v => [...v, { schemaVersion: 1, id: input.sessionId, workspaceId: s.workspaceId, contextRef: scope, projectId: result.job.projectId, lastJobId: result.job.id, revision: 1, createdAt: result.job.createdAt, updatedAt: result.job.createdAt }]);
    } catch (cause) { if (alive.current && epoch === scopeEpoch.current) setError(errorText(cause)); }
    finally { submitting.current = false; if (alive.current) setSending(false); }
  }
  async function cancel(job: Job) {
    const epoch = scopeEpoch.current; setActing(job.id);
    try { const value = await request<{job:Job}>('/api/v2/codex/jobs/' + job.id + '/cancel', { workspaceId: s.workspaceId }); if (alive.current && epoch === scopeEpoch.current) setJobs(js => merge(js, value.job)); }
    catch (cause) { if (alive.current && epoch === scopeEpoch.current) setError(errorText(cause)); }
    finally { if (alive.current) setActing(current => current === job.id ? '' : current); }
  }
  async function review(job: Job) {
    const epoch = scopeEpoch.current; setActing(job.id);
    try { const value = await request<{groupId:string}>('/api/v2/codex/jobs/' + job.id + '/review-preview', { workspaceId: s.workspaceId }); if (alive.current && epoch === scopeEpoch.current) await onReview(value.groupId); }
    catch (cause) { if (alive.current && epoch === scopeEpoch.current) setError(errorText(cause)); }
    finally { if (alive.current) setActing(current => current === job.id ? '' : current); }
  }
  function startRequest(text:string){
    const starters=['请帮我派发一个飞书任务：','请帮我创建一个会议日程：','请整理当前事项的归属，给我可确认的调整方案。','请查找当前事项的重复记录，给我可确认的合并方案。','请把当前事项中混在一起的事情拆开，给我可确认的拆分方案。'];
    setInput(v=>!v.text.trim()||starters.includes(v.text)?{...v,text,parentJobId:undefined,retryOf:undefined,requestId:crypto.randomUUID()}:v);
    textareaRef.current?.focus();
  }
  const renderJob=(job:Job)=><article className="ca-turn" key={job.id}>
      <div className="ca-user-message"><p>{job.text}</p></div>
      <div className="ca-assistant-message"><div className="ca-result-top"><strong>助手分析</strong><span className={'ca-job-status ' + job.status}>{labels[job.status]}</span></div>
        {job.status === 'running' && <p role="status"><Loader2 size={14} className="spin" /> {job.events.at(-1)?.message || '正在准备上下文'}</p>}
        {job.evidenceStatus === 'stale' && <div role="status" className="ca-stale">依据已变化或撤回。以下保留历史，需重新提问核对。</div>}
        {job.answer && <div className="ca-answer">{job.answer}</div>}
        {job.status==='completed'&&!!job.actionRequests?.length&&<AssistantActions workspaceId={s.workspaceId} jobId={job.id} request={request}/>}
        {job.status==='completed'&&!!job.workItemRequests?.length&&<WorkItemAssistant workspaceId={s.workspaceId} jobId={job.id} request={request}/>}
        {!!job.nextSteps?.length && <div className="ca-next"><strong>下一步</strong><ul>{job.nextSteps.map((step, i) => <li key={i}>{step}</li>)}</ul></div>}
        {!!job.conflicts?.length && <div className="ca-task-error"><strong>资料存在分歧，待核实</strong>{job.conflicts.map((v, i) => <p key={i}>{v.reason}</p>)}</div>}
        {job.coreWorkOutcome&&<CorePreparationResult s={s} value={job.coreWorkOutcome}/>}
        {job.error && <p className="ca-task-error" role="alert">{job.error}</p>}
        {job.coreOutcome?.status==='saved'&&<div className="p1-receipt" aria-label="统一输入保存回执"><strong>{job.coreOutcome.duplicate?'同一原图已记录，本次未重复保存':'已保存到 '+job.coreOutcome.applied.length+' 个对应事项'}</strong>{job.coreOutcome.pending.map((p,i)=><p key={i}>{p.text}</p>)}{job.coreOutcome.applied.map(p=>onOpen?<button key={p.sourceId} className="v2-text-button" onClick={()=>onOpen(p.sourceId)}>查看对应事项</button>:<a key={p.sourceId} className="v2-text-button" href={'/?'+new URLSearchParams({workspaceId:s.workspaceId,view:'inbox',record:p.sourceId})}>查看对应事项</a>)}{job.coreOutcome.receipt&&!job.coreOutcome.duplicate&&<button className="v2-text-button" disabled={acting===job.id} onClick={()=>{setActing(job.id);void request('/api/v2/work-items',{workspaceId:s.workspaceId,sourceId:job.coreOutcome!.receipt!.sourceId,operationId:job.coreOutcome!.receipt!.operationId,action:'p1-undo',requestId:'undo-'+job.coreOutcome!.receipt!.operationId}).then(()=>{setJobs(v=>v.map(x=>x.id===job.id?{...x,coreOutcome:{...x.coreOutcome!,status:'undone'}}:x));}).catch(e=>setError(errorText(e))).finally(()=>setActing(''));}}>撤销本次操作</button>}</div>}
        {!!job.gaps?.length && <details className="ca-evidence"><summary>判断缺口 · {job.gaps.length} 项</summary><ul>{job.gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul></details>}
        {!!job.coverage?.length && <details className="ca-evidence"><summary>读取范围 · {job.coverage.filter(c => c.complete).length} 份完整 / {job.coverage.filter(c => !c.complete&&c.read!==false).length} 份部分{job.coverage.some(c=>c.read===false)?' / '+job.coverage.filter(c=>c.read===false).length+' 份未读':''}</summary>{job.coverage.map(c => <div key={c.sourceId}><strong>{c.title}</strong><p>{c.read===false?'本轮未读取正文':c.complete ? '本轮已完整读取保存内容' : '本轮部分读取'}{c.limitations.length ? ' · ' + c.limitations.join('；') : ''}</p></div>)}</details>}
        {!!job.citations?.length && <details className="ca-evidence"><summary><FileText size={14} /> 核对引用 · {job.citations.length} 处</summary>{job.citations.map((c, i) => <Citation key={c.citationId + ':' + i} citation={c} job={job} request={request} />)}</details>}
        {job.groupId && <div className="ca-review-ready"><ShieldCheck size={18} /><div><strong>{reviewLabel(s,job)}</strong><p>{job.preview?.objects.length || 0} 项拟变更 · 引用版本已保存 · 外部操作未执行</p><details><summary>查看对象与拟变更</summary>{job.preview?.objects.map(o => <div key={o.kind + o.id}><p>{s[o.kind as keyof V2State] instanceof Array ? (s[o.kind as 'actions'] as { id: string; title: string }[]).find(r => r.id === o.id)?.title || o.id : o.id}</p><p>{o.reason}</p><pre>{JSON.stringify({ before: o.before, after: o.after }, null, 2)}</pre></div>)}</details></div><button className="v2-button primary" disabled={acting === job.id || !resolvedReview(s,job)&&job.preview?.availability !== 'current'} onClick={() => void review(job)}><ArrowUpRight size={14} />{resolvedReview(s,job)?'查看审核结果':'进入现有审核'}</button></div>}
        <div className="ca-result-actions">{job.status === 'running' && <button className="v2-button" disabled={acting === job.id} onClick={() => void cancel(job)}><Square size={12} />取消本轮</button>}{job.id === latest?.id && ['failed', 'cancelled', 'interrupted'].includes(job.status) && <button className="v2-button" disabled={sending || !available || !!running} onClick={() => void submit(job)}><RefreshCw size={14} />重试这一轮</button>}</div>
      </div>
    </article>;
  return <section className="ca-conversation" aria-label="连续智能助手">
    <div className="ca-toolbar"><div className="ca-scope-control">{scopeControl}{(previewMode||s.workspaceType==='demo')&&<span className="ca-preview-tag">模拟执行</span>}</div><div className="ca-toolbar-actions">
      {scopeSessions.some(v=>v.id!==input.sessionId)&&<select aria-label="已有对话" value={input.sessionId} onChange={e=>changeSession(e.target.value)}><option value={input.sessionId}>历史对话</option>{scopeSessions.filter(v=>v.id!==input.sessionId).map(v=><option key={v.id} value={v.id}>{new Date(v.createdAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</option>)}</select>}
      <button type="button" className="ca-text-button" disabled={sending} onClick={()=>changeSession()}><Plus size={15}/>新对话</button>
      <button type="button" className="ca-text-button" aria-expanded={showOptions} aria-controls={optionsId} onClick={()=>setShowOptions(v=>!v)}><Settings2 size={15}/>选项{input.mode==='draft'||input.sourceIds.length?' · 已设置':''}</button>
    </div></div>
    {error && <div className="ca-task-error" role="alert">{error}<button type="button" className="v2-button" onClick={() => setReload(v => v + 1)}><RefreshCw size={14} />刷新对话</button></div>}
    {loading&&<p className="ca-loading" role="status">正在读取会话…</p>}
    <form className="ca-chat-compose" onSubmit={e => { e.preventDefault(); void submit(); }}>
      <label htmlFor={inputId} className="ca-sr-only">消息</label><textarea ref={textareaRef} id={inputId} data-assistant-input value={input.text} maxLength={20000} required={!input.images?.length} rows={4} placeholder={jobs.length?'继续说…':'输入你的要求…'} onChange={e => setInput(v => ({ ...v, text: e.target.value, parentJobId: undefined, retryOf: undefined, requestId: crypto.randomUUID() }))} />
      <InputImages workspaceId={s.workspaceId} request={request} images={input.images||[]} onChange={images=>setInput(v=>({...v,images,requestId:crypto.randomUUID()}))} disabled={sending||!!running||input.mode==='draft'}/>
      <div className="ca-compose-footer"><div className="ca-shortcuts">{scope.kind==='sources'?<><button type="button" disabled={sending||!!running} onClick={()=>startRequest('请整理当前事项的归属，给我可确认的调整方案。')}>调整归属</button><button type="button" disabled={sending||!!running} onClick={()=>startRequest('请查找当前事项的重复记录，给我可确认的合并方案。')}>合并重复</button><button type="button" disabled={sending||!!running} onClick={()=>startRequest('请把当前事项中混在一起的事情拆开，给我可确认的拆分方案。')}>拆分事项</button></>:<><button type="button" disabled={sending||!!running} onClick={()=>startRequest('请帮我派发一个飞书任务：')}><ClipboardList size={15}/>派发任务</button><button type="button" disabled={sending||!!running} onClick={()=>startRequest('请帮我创建一个会议日程：')}><CalendarDays size={15}/>创建会议</button></>}</div><button className="v2-button primary" type="submit" disabled={!ready || !available || sending || !!running || !input.text.trim()&&!input.images?.length}>{sending ? <Loader2 size={14} className="spin" /> : <Send size={14} />}{running ? '处理中' : '发送'}</button></div>
    </form>
    {latest&&<div className="ca-turns" aria-live="polite">{renderJob(latest)}</div>}
    {jobs.length>1&&<details className="p1-conversation-history"><summary>此前对话 · {jobs.length-1} 轮</summary><div className="ca-turns">{jobs.slice(0,-1).map(renderJob)}</div></details>}
    {pollError && <p role="status">{pollError}</p>}
    <CoreCollaborationPanel workspaceId={s.workspaceId} revision={s.revision} request={request}/>

    {showOptions&&<section id={optionsId} className="ca-options-panel" aria-label="对话选项">
      <AssistantControls workspaceId={s.workspaceId} request={request} mode="chat"/>
      <details className="ca-evidence"><summary>指定资料{input.sourceIds.length?' · '+input.sourceIds.length+' 份':''}</summary>{s.sources.filter(src=>!src.archived&&!src.intakeBatch).slice(0,150).map(src=><label className="ca-source-option" key={src.id}><input type="checkbox" checked={input.sourceIds.includes(src.id)} disabled={!input.sourceIds.includes(src.id)&&input.sourceIds.length>=20} onChange={e=>setInput(v=>({...v,sourceIds:e.target.checked?[...v.sourceIds,src.id]:v.sourceIds.filter(id=>id!==src.id),parentJobId:undefined,retryOf:undefined,requestId:crypto.randomUUID()}))}/>{src.title}</label>)}</details>
      <label className="ca-draft-option"><input type="checkbox" checked={input.mode==='draft'} onChange={e=>setInput(v=>({...v,mode:e.target.checked?'draft':'answer',parentJobId:undefined,retryOf:undefined,requestId:crypto.randomUUID()}))}/>准备待审核修改</label>
    </section>}
  </section>;
}
function Citation({ citation: c, job, request }: { citation: AssistantCitation; job: Job; request: Props['request'] }) {
  const [notice, setNotice] = useState(''), [verified, setVerified] = useState(false);
  return <div className="ca-citation"><strong>{c.title}</strong>{c.library&&<small>Library · {c.library.snapshotDate||'本地登记版本'}{c.library.originalAvailability==='missing'?' · 原件缺失，引用已保存副本':''}</small>}<small>{c.locator.label} · 版本 {c.version} · {c.availability === 'current' ? c.coverage === 'complete' ? '已读取' : '部分读取' : '已失效'}</small>{c.quote ? <blockquote>{c.quote}</blockquote> : <p>图像观察：{c.locator.label}，需结合原图核实。</p>}<p>AI 判断：{c.interpretation}</p><button className="v2-button" disabled={c.availability !== 'current'} onClick={() => { void request(`/api/v2/codex/jobs/${job.id}/citation?workspaceId=${encodeURIComponent(job.workspaceId)}&id=${encodeURIComponent(c.citationId)}`).then(value => { const result=value as {original?:{text:string}}; setVerified(true); setNotice(result.original?.text || '已核对当前保存原文，引用位置与内容指纹一致。'); }).catch(e => { setVerified(false); setNotice(errorText(e)); }); }}>核对当前引用</button>{c.url && verified && <a href={c.url} target="_blank" rel="noreferrer">打开来源</a>}{notice && <p role="status">{notice}</p>}</div>;
}
