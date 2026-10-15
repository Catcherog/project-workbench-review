"use client";
import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {Send,Loader2,Undo2,Plus,Settings2} from 'lucide-react';
import type {V2State} from '../lib/v2-types';
import type {Item} from '../lib/domain';
import type {AssistantRequest} from './codex-assistant';
import {workItemState} from '../lib/work-items';
import {itemTiming,timeLabel,entryReceipts,receiptProgressId,normalizeTime,type TimeChoice} from '../lib/work-item-progress';
import {WorkItemTime,timeDraft,type TimeDraft} from './work-item-time';
import {useItemWorkspaceNavigation} from './item-workspace-navigation';
import {AssistantControls} from './assistant-controls';
import {AssistantActions} from './assistant-actions';
import {CorePreparationResult} from './core-preparation-result';
import {CoreCollaborationPanel} from './work-item-core-controls';
import {InputImages,type InputImage} from './input-images';
import {WorkItemAssistant} from './work-item-assistant';
import {readInputDraft,writeInputDraft} from './local-draft';
import {workItemInputLabel} from './work-item-input-label';
import {IntegrationReceiptHeading} from './integration/receipt-heading';
import {receiptInScope} from './integration/receipt-scope';
import {ActionFeedback} from './integration/action-feedback';
import './work-item-entry.css';

type Value=Omit<Item,'id'|'title'|'projectIds'|'sourceIds'>;
type Props={s:V2State;source:Item;request:AssistantRequest;onReview:(id:string)=>Promise<void>};
const explain=(error:unknown)=>error instanceof Error?error.message:String(error);
export function WorkItemEntry({s,source,request,onReview}:Props){
 const navigation=useItemWorkspaceNavigation(),timing=itemTiming(s,source),current=workItemState(s,source),key='p1:'+s.workspaceId+':'+source.id;
 const [saved]=useState(()=>readInputDraft(key,{text:'',sessionId:crypto.randomUUID(),images:'[]',dirtyCheck:false,dirtyCompletion:false,check:JSON.stringify(timeDraft(timing.check)),completion:JSON.stringify(timeDraft(timing.completion)),expectedVersion:source.version,expectedBasis:current.basis,expectedEvidenceBasis:current.liveEvidenceBasis,editProgressId:''}));
 const [text,setText]=useState(()=>navigation?.entrySeed?.receipt?navigation.entrySeed.receipt.progress||'':saved.text),[times,setTimes]=useState<TimeDraft>(()=>({check:saved.dirtyCheck?JSON.parse(saved.check):timeDraft(timing.check),completion:saved.dirtyCompletion?JSON.parse(saved.completion):timeDraft(timing.completion)}));
 const [images,setImages]=useState<InputImage[]>(()=>{try{return JSON.parse(saved.images||'[]');}catch{return [];}});
 const [dirty,setDirty]=useState({check:saved.dirtyCheck,completion:saved.dirtyCompletion});
 const [expected,setExpected]=useState(()=>navigation?.entrySeed||!saved.text&&!saved.dirtyCheck&&!saved.dirtyCompletion?{version:source.version,basis:current.basis,evidence:current.liveEvidenceBasis}:{version:saved.expectedVersion,basis:saved.expectedBasis,evidence:saved.expectedEvidenceBasis});
 const [sessionId,setSessionId]=useState(saved.sessionId),[editProgressId,setEditProgressId]=useState(navigation?.entrySeed?.receipt?receiptProgressId(navigation.entrySeed.receipt):saved.editProgressId);
 const [jobs,setJobs]=useState<Value[]>([]),[pending,setPending]=useState<Value|null>(()=>{try{return JSON.parse(localStorage.getItem(key+':pending')||'null');}catch{return null;}});
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[receipt,setReceipt]=useState<Value|null>(()=>entryReceipts(s,source.id)[0]||null),[conflicts,setConflicts]=useState<Value[]>([]),[resolution,setResolution]=useState<Value>({});
 const [sessions,setSessions]=useState<Value[]>([]),[showOptions,setShowOptions]=useState(false),[selectedSources,setSelectedSources]=useState<string[]>([]),[prepareDraft,setPrepareDraft]=useState(false);
 const [available,setAvailable]=useState(true),[loaded,setLoaded]=useState(false);
 const [fieldErrors,setFieldErrors]=useState<Partial<Record<'check'|'completion',string>>>({});
 const alive=useRef(true),submitting=useRef(false),generation=useRef(0),sentGeneration=useRef(0),handled=useRef(new Set<string>()),inputRef=useRef<HTMLTextAreaElement>(null),timeRef=useRef<HTMLDivElement>(null);
 const draftRef=useRef({text,times,dirty,editProgressId,images}),pendingRef=useRef(pending);
 const running=jobs.find(j=>j.status==='running'),runningId=running?.id,latest=jobs.at(-1);
 const finishRef=useRef(finish);
 useLayoutEffect(()=>{draftRef.current={text,times,dirty,editProgressId,images};pendingRef.current=pending;finishRef.current=finish;});
 const stale=!!(text||dirty.check||dirty.completion||pending||images.length)&&(source.version!==expected.version||current.basis!==expected.basis||current.liveEvidenceBasis!==expected.evidence);
 const dirtyAny=dirty.check||dirty.completion;
 useLayoutEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 useEffect(()=>{writeInputDraft(key,{text,sessionId,images:JSON.stringify(images),dirtyCheck:dirty.check,dirtyCompletion:dirty.completion,check:JSON.stringify(times.check),completion:JSON.stringify(times.completion),expectedVersion:expected.version,expectedBasis:expected.basis,expectedEvidenceBasis:expected.evidence,editProgressId});},[key,text,sessionId,dirty,times,expected,editProgressId,images]);
 useEffect(()=>{try{if(pending)localStorage.setItem(key+':pending',JSON.stringify(pending));else localStorage.removeItem(key+':pending');}catch{/* Keep current input in memory. */}},[key,pending]);
 useEffect(()=>{let active=true;void (async()=>{try{const result=await request<{sessions:Value[]}>('/api/v2/codex/sessions?workspaceId='+encodeURIComponent(s.workspaceId));if(!active)return;setSessions(result.sessions);if(result.sessions.some(x=>x.id===sessionId)){const history=await request<{jobs:Value[]}>('/api/v2/codex/sessions/'+sessionId+'?workspaceId='+encodeURIComponent(s.workspaceId));if(active){const recovering=pendingRef.current?await request<{job:Value|null}>('/api/v2/codex/requests/'+pendingRef.current.requestId+'?workspaceId='+encodeURIComponent(s.workspaceId)):null;if(!active)return;for(const j of history.jobs)if(j.status!=='running'&&recovering?.job?.id!==j.id)handled.current.add(j.id);setJobs(history.jobs);if(recovering?.job&&recovering.job.status!=='running')await finishRef.current(recovering.job);}}const status=await request<{available:boolean}>('/api/v2/codex/status');if(active)setAvailable(status.available);}catch(e){if(active)setError(explain(e));}finally{if(active)setLoaded(true);}})();return()=>{active=false;};},[request,s.workspaceId,sessionId]);
 const seed=navigation?.entrySeed;
 useEffect(()=>{if(!seed)return;if(seed.focusTime){timeRef.current?.scrollIntoView({block:'center'});(timeRef.current?.querySelector('select') as unknown as HTMLSelectElement|null)?.focus();}},[seed]);
 function adopt(job:Value){setJobs(old=>[...old.filter(j=>j.id!==job.id),job].sort((a,b)=>a.createdAt.localeCompare(b.createdAt)));}
 async function finish(job:Value){
  if(!alive.current||job.workspaceId!==s.workspaceId||job.contextRef?.id!==source.id||handled.current.has(job.id)||job.status==='running')return;handled.current.add(job.id);
  if(job.p1Outcome?.receipt)job={...job,p1Outcome:{...job.p1Outcome,receipt:{...job.p1Outcome.receipt,workspaceId:s.workspaceId}}};
  setPending(null);try{localStorage.removeItem(key+':pending');}catch{/* Stored request identity is non-authoritative. */}
  if(job.status!=='completed'){if(job.p1Outcome?.status==='saved'){setReceipt(job.p1Outcome.receipt);setNotice('后续分析已停止，已保存的本地记录保留。');await navigation?.saved?.(job.p1Outcome.receipt,true);}else setError(job.error||'本次尚未完成，输入已保留。');return;}
  const outcome=job.p1Outcome;
  const sentDraft=pendingRef.current?.clientDraft;
  const newer=sentDraft?JSON.stringify(draftRef.current)!==JSON.stringify({...sentDraft,editProgressId:sentDraft.editProgressId||pendingRef.current?.p1Input?.editProgressId||'',images:sentDraft.images||[]}):generation.current!==sentGeneration.current;
  if(outcome?.status==='clarify'){setResolution({});setConflicts(newer?[]:outcome.conflicts||[]);setNotice(newer?'输入或手选时间已变化，旧冲突候选已失效。当前草稿已保留，请重新发送后核对新候选。':'本次尚未保存，请选择具体差异；原输入保留。');return;}
  const resultTimes=outcome?.receipt?.timing;const draftAfter=newer?draftRef.current:{text:'',times:resultTimes?{check:timeDraft(resultTimes.check),completion:timeDraft(resultTimes.completion)}:times,dirty:{check:false,completion:false}};
  const expectedAfter=outcome?.status==='saved'?{version:outcome.receipt.version,basis:outcome.receipt.basis,evidence:outcome.receipt.evidence}:expected;
  writeInputDraft(key,{text:draftAfter.text,sessionId,images:newer?JSON.stringify(images):'[]',dirtyCheck:draftAfter.dirty.check,dirtyCompletion:draftAfter.dirty.completion,check:JSON.stringify(draftAfter.times.check),completion:JSON.stringify(draftAfter.times.completion),expectedVersion:expectedAfter.version,expectedBasis:expectedAfter.basis,expectedEvidenceBasis:expectedAfter.evidence,editProgressId:newer?editProgressId:''});
  if(!newer){setText('');setImages([]);setDirty({check:false,completion:false});setResolution({});setConflicts([]);setEditProgressId('');}
  if(outcome?.status==='saved'){
   if(!newer)setTimes({check:timeDraft(outcome.receipt.timing.check),completion:timeDraft(outcome.receipt.timing.completion)});
   setExpected({version:outcome.receipt.version,basis:outcome.receipt.basis,evidence:outcome.receipt.evidence});setReceipt(outcome.receipt);setNotice(newer?'上一条已保存；本次新输入仍保留。':'');
   const preparationUnfinished=['incomplete','partial'].includes(job.coreWorkOutcome?.status);
   try{await navigation?.saved?.(outcome.receipt,!!outcome.stay||newer||preparationUnfinished);}catch{setError('记录已保存，页面刷新失败。可以重新读取，勿重复提交。');}
  }
 }
 useEffect(()=>{if(!runningId)return;let active=true;let timer:ReturnType<typeof setTimeout>;const poll=async()=>{try{const result=await request<{job:Value}>('/api/v2/codex/jobs/'+runningId+'?workspaceId='+encodeURIComponent(s.workspaceId));if(active){adopt(result.job);if(result.job.status!=='running')await finishRef.current(result.job);}}catch{if(active)setError('暂时无法读取处理结果，正在查询原操作，输入保留。');}if(active)timer=setTimeout(poll,600);};timer=setTimeout(poll,200);return()=>{active=false;clearTimeout(timer);};},[runningId,request,s.workspaceId]); // Completion reads the current draft through generation; input is never reset while a job runs.
 function invalidateChoices(){generation.current++;setResolution({});setConflicts([]);}
 function changeTime(k:'check'|'completion',value:TimeChoice){setFieldErrors(v=>{const next={...v};delete next[k];return next;});setError('');if(!text&&!dirtyAny)setExpected({version:source.version,basis:current.basis,evidence:current.liveEvidenceBasis});invalidateChoices();setTimes(v=>({...v,[k]:value}));setDirty(v=>({...v,[k]:true}));}
 async function submit(){
  if(submitting.current||running||!loaded||!text.trim()&&!dirtyAny&&!images.length&&!pending||stale&&!pending)return;
  if(!pending&&!prepareDraft){
   const errors:Partial<Record<'check'|'completion',string>>={};
   for(const key of ['check','completion'] as const)if(dirty[key])try{normalizeTime(times[key],'manual',new Date().toISOString());}catch{errors[key]='请填写有效的'+(key==='check'?'检查':'完成')+'日期和时刻；本次尚未提交。';}
   setFieldErrors(errors);
   const first=(['check','completion'] as const).find(k=>errors[k]);
   if(first){setError('时间安排尚未填写完整；输入已保留，本次没有提交。');setNotice('');requestAnimationFrame(()=>{const field=timeRef.current?.querySelector<HTMLInputElement>('[data-time-field="'+first+'"]');field?.focus({preventScroll:true});field?.scrollIntoView({block:'center'});});return;}
  }
  submitting.current=true;setBusy(true);setError('');setNotice('');
  const value=pending||{workspaceId:s.workspaceId,contextRef:{kind:'sources',id:source.id},sessionId,requestId:crypto.randomUUID(),mode:prepareDraft?'draft':'answer',sourceIds:selectedSources,attachmentIds:images.map(i=>i.id),text,clientDraft:{text,times,dirty,editProgressId,images},parentJobId:latest?.id||'',...(!prepareDraft?{p1Input:{occurredAt:new Date().toISOString(),expectedVersion:expected.version,expectedBasis:expected.basis,expectedEvidenceBasis:expected.evidence,manual:Object.fromEntries((['check','completion'] as const).filter(k=>dirty[k]).map(k=>[k,times[k]])),resolution,...(editProgressId?{editProgressId}:{})}}:{})};
  if(!pending)sentGeneration.current=generation.current;setPending(value);pendingRef.current=value;
  try{
   // Read the original request before retrying an uncertain POST.
   let job:Value|undefined;
   if(pending){const found=await request<{job:Value|null}>('/api/v2/codex/requests/'+value.requestId+'?workspaceId='+encodeURIComponent(s.workspaceId));job=found.job||undefined;}
   if(!job){try{job=(await request<{job:Value}>('/api/v2/codex/jobs',value)).job;}catch(cause){try{const found=await request<{job:Value|null}>('/api/v2/codex/requests/'+value.requestId+'?workspaceId='+encodeURIComponent(s.workspaceId));if(found.job)job=found.job;else{setPending(null);throw cause;}}catch{throw cause;}}}
   if(alive.current&&job){adopt(job);await finish(job);}
  }catch(e){if(alive.current)setError(explain(e)+'；输入与手选值已保留。结果未明时重试会先查询原操作。');}finally{submitting.current=false;if(alive.current)setBusy(false);}
 }
 function cancel(){writeInputDraft(key,{text:'',sessionId,dirtyCheck:false,dirtyCompletion:false,check:JSON.stringify(timeDraft(timing.check)),completion:JSON.stringify(timeDraft(timing.completion)),expectedVersion:source.version,expectedBasis:current.basis,expectedEvidenceBasis:current.liveEvidenceBasis,editProgressId:''});generation.current++;setText('');setImages([]);setTimes({check:timeDraft(timing.check),completion:timeDraft(timing.completion)});setDirty({check:false,completion:false});setResolution({});setConflicts([]);setEditProgressId('');navigation?.cancelEntry?.();}
 return <section className="ca-conversation p1-entry" aria-label="当前事项记录与讨论"><div className="ca-toolbar"><strong>{source.title}</strong><div className="ca-toolbar-actions"><button type="button" className="ca-text-button" disabled={busy||!!running||!!pending} onClick={()=>{setSessionId(crypto.randomUUID());setJobs([]);setError('');}}><Plus size={15}/>新对话</button><button type="button" className="ca-text-button" aria-expanded={showOptions} onClick={()=>setShowOptions(v=>!v)}><Settings2 size={15}/>选项</button></div></div>
  <div className="ca-turns" aria-live="polite">{jobs.map(job=><article className="ca-turn" key={job.id}><div className="ca-user-message"><p>{workItemInputLabel(job,s.sources)}</p></div><div className="ca-assistant-message">{job.status==='running'?<p role="status"><Loader2 size={14} className="spin"/>{job.p1Outcome?.status==='saved'?'本地记录已保存，正在核对相关依赖与协作准备…':'正在理解本次输入…'}</p>:<>{job.coreWorkOutcome&&<CorePreparationResult value={job.coreWorkOutcome}/>}{job.answer&&<div className="ca-answer"><strong>{job.p1Outcome?.status==='clarify'?'理解与建议（本次尚未保存）':'理解与建议'}</strong><p>{job.answer}</p></div>}{job.p1Outcome?.status==='saved'&&job.p1Outcome.receipt?.operationId!==receipt?.operationId&&<p>已保存：{job.p1Outcome.receipt?.progress||'本次明确安排'}{job.p1Outcome.receipt?.closed?' · 已移入已结束':''}</p>}{job.evidenceStatus==='stale'&&<p role="status">依据已变化；以下保留历史，请重新核对。</p>}{!!job.gaps?.length&&<details><summary>依据与缺口</summary>{job.gaps.map((g:string,i:number)=><p key={i}>{g}</p>)}{job.citations?.map((c:Value,i:number)=><div key={i}><strong>{c.title}</strong><blockquote>{c.quote}</blockquote><p>{c.interpretation}</p></div>)}</details>}{job.groupId&&<button className="v2-button" onClick={()=>void onReview(job.groupId)}>查看待审核修改</button>}{job.error&&<p role="alert">{job.error}</p>}{job.actionRequests?.length>0&&<AssistantActions workspaceId={s.workspaceId} jobId={job.id} request={request}/>} {job.workItemRequests?.length>0&&<WorkItemAssistant workspaceId={s.workspaceId} jobId={job.id} request={request}/>}</>}</div></article>)}</div>
  {running&&<button type="button" className="v2-text-button" onClick={()=>void request<{job:Value}>('/api/v2/codex/jobs/'+running.id+'/cancel',{workspaceId:s.workspaceId}).then(async result=>{adopt(result.job);await finish(result.job);}).catch(e=>setError(explain(e)))}>取消本轮</button>}
  {receipt&&<><p className="p1-previous-receipt">此前保存的结果 · 下方新输入需另行提交</p><P1Receipt receipt={receipt} s={s} request={request} onRefresh={async next=>{await navigation?.saved?.(next||receipt,true);setReceipt(null);}} onOpen={()=>navigation?.openItem(source.id)} onEdit={live=>{invalidateChoices();setText(live.progress||'');setEditProgressId(receiptProgressId(live));inputRef.current?.focus();}} onTime={()=>{timeRef.current?.scrollIntoView({block:'center'});(timeRef.current?.querySelector('select') as HTMLSelectElement|null)?.focus();}}/></>}
  {stale&&(text||dirtyAny)&&!running&&<p role="status">事项已更新，草稿和手选时间保留。<button type="button" className="v2-text-button" onClick={()=>{invalidateChoices();setExpected({version:source.version,basis:current.basis,evidence:current.liveEvidenceBasis});}}>已核对当前记录，继续</button></p>}
  {!!conflicts.length&&<div className="p1-conflict" role="status">{conflicts.map((c,i)=><div key={i}><p>{c.message}</p>{c.text&&c.manual&&(['text','manual'] as const).map(kind=><label key={kind}><input type="radio" name={'choice-'+c.field} disabled={busy||!!running} checked={resolution[c.field]?.choice===kind&&resolution[c.field]?.fingerprint===c.fingerprint} onChange={()=>setResolution(v=>({...v,[c.field]:{choice:kind,fingerprint:c.fingerprint}}))}/>{kind==='text'?'文字安排':'手选安排'}：{timeLabel(c[kind])}</label>)}{c.field==='followup'&&(['continue','end'] as const).map(kind=><label key={kind}><input type="radio" name="followup-choice" disabled={busy||!!running} checked={resolution.followup?.choice===kind&&resolution.followup?.fingerprint===c.fingerprint} onChange={()=>setResolution(v=>({...v,followup:{choice:kind,fingerprint:c.fingerprint}}))}/>{kind==='continue'?'还有后续，保留新安排':'明确结束，不采用本次未来安排'}</label>)}</div>)}</div>}
  {latest?.coreWorkOutcome&&<CoreCollaborationPanel workspaceId={s.workspaceId} revision={s.revision} request={request}/>}
  <form className="ca-chat-compose p1-record-compose" onSubmit={e=>{e.preventDefault();void submit();}}><label className="ca-sr-only" htmlFor={'p1-message-'+source.id}>消息</label><textarea ref={inputRef} id={'p1-message-'+source.id} data-assistant-input value={text} maxLength={20000} rows={4} placeholder="记录新进展、安排时间，或继续讨论…" onChange={e=>{if(!text&&!dirtyAny)setExpected({version:source.version,basis:current.basis,evidence:current.liveEvidenceBasis});invalidateChoices();setText(e.target.value);}}/>
   <InputImages workspaceId={s.workspaceId} request={request} images={images} onChange={value=>{invalidateChoices();setImages(value);}} disabled={busy||!!running||!!pending||prepareDraft}/>
   <div ref={timeRef}><WorkItemTime value={times} onChange={changeTime} sources={timing} disabled={prepareDraft} errors={fieldErrors}/></div>
   <div className="ca-compose-footer"><button type="button" className="v2-text-button" disabled={busy||!!running||!!pending} onClick={cancel}>取消编辑</button><button className="v2-button primary" type="submit" disabled={!loaded||busy||!!running||!text.trim()&&!dirtyAny&&!images.length&&!pending||stale&&!pending||!!text.trim()&&!available}>{busy||running?<Loader2 size={15} className="spin"/>:<Send size={15}/>}发送</button></div>
   <ActionFeedback context="当前事项输入" busy={busy||!!running} message={notice} error={error} reveal={!Object.keys(fieldErrors).length}>
    {receipt&&error.includes('刷新')&&<button type="button" className="v2-text-button" onClick={()=>void navigation?.saved?.(receipt,true).then(()=>setError('')).catch(()=>setError('记录已保存，仍无法刷新；请稍后重新读取。'))}>重新读取保存结果</button>}
   </ActionFeedback>
  </form><div className="ca-shortcuts">{['请整理当前事项的归属，给我可确认的调整方案。','请查找当前事项的重复记录，给我可确认的合并方案。','请把当前事项中混在一起的事情拆开，给我可确认的拆分方案。'].map((x,i)=><button type="button" key={x} disabled={!!running} onClick={()=>{invalidateChoices();setText(x);inputRef.current?.focus();}}>{['调整归属','合并重复','拆分事项'][i]}</button>)}</div>
 {showOptions&&<section className="ca-options-panel" aria-label="对话选项"><AssistantControls workspaceId={s.workspaceId} request={request} mode="chat"/><label>已有对话<select aria-label="已有对话" value={sessionId} disabled={busy||!!running||!!pending} onChange={e=>{setSessionId(e.target.value);setJobs([]);setError('');}}><option value={sessionId}>当前对话</option>{sessions.filter(v=>v.id!==sessionId&&v.contextRef.kind==='sources'&&v.contextRef.id===source.id).map(v=><option key={v.id} value={v.id}>{new Date(v.createdAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</option>)}</select></label><details><summary>指定资料</summary>{s.sources.filter(r=>!r.archived&&!r.workItem&&!r.intakeBatch).slice(0,150).map(r=><label className="ca-source-option" key={r.id}><input type="checkbox" checked={selectedSources.includes(r.id)} disabled={!selectedSources.includes(r.id)&&selectedSources.length>=20} onChange={e=>setSelectedSources(v=>e.target.checked?[...v,r.id]:v.filter(id=>id!==r.id))}/>{r.title}</label>)}</details><label className="ca-draft-option"><input type="checkbox" checked={prepareDraft} disabled={dirtyAny||!!running||!!pending} onChange={e=>setPrepareDraft(e.target.checked)}/>准备待审核修改（正式业务仍走原审核）</label>{prepareDraft&&<p>本地时间区保留原值；本轮仅准备修改草稿，不自动写入。</p>}</section>}
 </section>;
}
export function P1Receipt({receipt,s,request,onOpen,onTime,onEdit,onRefresh,isCurrent=()=>true}:{receipt:Value;s:V2State;request:AssistantRequest;onOpen?:(live:Value)=>void;onTime:(live:Value)=>void;onEdit:(live:Value)=>void;onRefresh:(next?:Value)=>Promise<void>;isCurrent?:()=>boolean}){
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),pendingOperation=useRef<Value|null>(null),submitting=useRef(false),alive=useRef(true);
 const latest=useRef({s,receipt,isCurrent});latest.current={s,receipt,isCurrent};
 useLayoutEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 const live=receiptInScope(s,receipt),row=live?s.sources.find(r=>r.id===live.sourceId):undefined,c=row?.workItem?workItemState(s,row):null;
 function current(){const value=latest.current;return alive.current&&value.isCurrent()?receiptInScope(value.s,value.receipt):null;}
 function guard(){const value=current();if(!value||value.undoneAt)throw Error('当前页面已切换或保存回执待核实，请回原事项重新读取。');}
 function act(callback:(value:Value)=>void,write=false){const value=current();if(value&&(!write||!value.undoneAt&&!value.duplicate))callback(value);}
 async function undo(){
  const value=current();if(!value||value.undoneAt||value.duplicate||submitting.current)return;
  submitting.current=true;setBusy(true);setError('');
  try{await localOperation(request,{workspaceId:value.workspaceId,sourceId:value.sourceId,requestId:'undo-'+value.operationId,action:'p1-undo',operationId:value.operationId},guard);if(current())try{await onRefresh();}catch{if(current())setError('撤销已保存，显示刷新失败，请重新读取。');}}
  catch(e){if(current())setError(explain(e));}finally{submitting.current=false;if(alive.current)setBusy(false);}
 }
 async function pending(){
  const value=current(),state=latest.current.s,source=value?state.sources.find(r=>r.id===value.sourceId):undefined;
  if(!value||value.undoneAt||!source||submitting.current)return;const context=workItemState(state,source);if(context.closed)return;
  submitting.current=true;setBusy(true);setError('');
  try{const entry={intent:'record',progress:'',progressQuote:'',waitingFor:'',waitingResult:'',waitingQuote:'',checkCompleted:false,checkQuote:'',riskDecision:'none',riskQuote:'',followup:'unchanged',followupQuote:'',check:{state:'unchanged'},completion:{state:'unchanged'},clarification:''};
   const body=pendingOperation.current||{workspaceId:value.workspaceId,sourceId:source.id,requestId:'pending-'+value.operationId,action:'p1-submit',expectedVersion:source.version,expectedBasis:context.basis,expectedEvidenceBasis:context.liveEvidenceBasis,entry,input:{text:'',occurredAt:new Date().toISOString(),manual:{check:{state:'pending'},completion:{state:'pending'}}}};
   pendingOperation.current=body;const result=await localOperation(request,body,guard);if(current())await onRefresh({...result,workspaceId:value.workspaceId});
  }catch(e){if(current())setError(explain(e));}finally{submitting.current=false;if(alive.current)setBusy(false);}
 }
 if(!live)return <section className="p1-receipt" aria-label="保存回执待核实"><p role="status">当前工作区没有对应的持久保存回执，请回原事项重新读取；关联操作已停用。</p></section>;
 const inactive=!!live.undoneAt;
 return <section className="p1-receipt" aria-label="本次保存回执"><IntegrationReceiptHeading receipt={live}/>{live.progress&&<p>{live.progress}</p>}{live.pendingChanges?.map((p:Value)=><p key={p.id} role="status">{p.message}</p>)}{c&&!c.closed&&!inactive&&<p>{c.timing.status}{c.timing.status==='时间待确认'?' · 后续时间待补':''}</p>}{c&&!c.closed&&c.timing.completionDue.map((v,i)=><p className="p1-overdue" key={i}>{v.node.date} · {v.label}</p>)}<div className="p1-actions">{onOpen&&<button className="v2-text-button" onClick={()=>act(onOpen)}>查看记录</button>}{!inactive&&!live.duplicate&&<><button className="v2-text-button" disabled={busy} onClick={()=>act(onEdit,true)}>修改记录</button><button className="v2-text-button" disabled={busy} onClick={()=>void undo()}><Undo2 size={14}/>撤销本次操作</button></>}{c&&!c.closed&&!inactive&&<><button className="v2-text-button" disabled={busy} onClick={()=>act(onTime)}>设置时间</button>{c.timing.status==='时间待确认'&&<button className="v2-text-button" disabled={busy} onClick={()=>void pending()}>目前都待定</button>}</>}</div><ActionFeedback context="保存回执操作" busy={busy} error={error}/></section>;
}

async function localOperation(request:AssistantRequest,body:Value,guard:()=>void){
 guard();
 const read=()=>request<{receipt?:{result?:Value}}>('/api/v2/work-items?workspaceId='+encodeURIComponent(body.workspaceId)+'&requestId='+encodeURIComponent(body.requestId));
 const known=await read();guard();if(known.receipt?.result)return known.receipt.result;
 try{return await request<Value>('/api/v2/work-items',body);}catch(error){try{const result=await read();if(result.receipt?.result)return result.receipt.result;}catch{/* Keep the original request identity and report an unknown result. */}throw error;}
}
