"use client";
import {CoreMaterials} from './core-materials';
import {useState} from 'react';
import {CoreCollaborationPanel} from './integration/core-collaboration-panel';
import type {Item} from '../lib/domain';
import type {V2State} from '../lib/v2-types';
import {workItemState} from '../lib/work-items';
import {coreState,effectivePriority} from '../lib/work-item-core';
import type {AssistantRequest} from './codex-assistant';
type Value=Omit<Item,'id'|'title'|'projectIds'|'sourceIds'>;
export function WorkItemCoreControls({s,source,request,refresh}:{s:V2State;source:Item;request:AssistantRequest;refresh:()=>Promise<unknown>}){
  const c=coreState(source),[busy,setBusy]=useState(false),[error,setError]=useState(''),[priority,setPriority]=useState(effectivePriority(source)),[until,setUntil]=useState(''),[manual,setManual]=useState(false),[fullFocus,setFullFocus]=useState(false),[weeklyTime,setWeeklyTime]=useState(c.weekly?.time||'14:00'),[weekday,setWeekday]=useState(String(c.weekly?.weekday||'last'));
  async function operate(action:string,extra:Value={}){
    if(busy)return;setBusy(true);setError('');try{const state=workItemState(s,source);await request('/api/v2/work-items',{workspaceId:s.workspaceId,sourceId:source.id,expectedVersion:source.version,expectedBasis:state.basis,expectedEvidenceBasis:state.liveEvidenceBasis,requestId:crypto.randomUUID(),action,...extra});await refresh();}catch(e){setError(e instanceof Error?e.message:'本次未能保存');}finally{setBusy(false);}
  }
  return <section className="wb-int-core" aria-label="持续跟进"><p><strong>{c.admission==='candidate'?'待纳入候选':c.admission==='withdrawn'?'已撤下候选':'持续跟进'}</strong> · {effectivePriority(source)}{c.cycle.temp?'（临时催办等级）':''} · 连续有效提醒 {c.cycle.count} 次</p>
    <p>{c.need.description}{c.need.arranged?' · 当前已妥善安排':''}{c.pause?' · 提醒已暂停':''}</p>
    {c.admission==='candidate'&&<button type="button" className="v2-button" disabled={busy} onClick={()=>void operate('core-admit')}>纳入跟进</button>}
    <details><summary>优先级与提醒安排</summary><label>优先级<select aria-label="优先级" value={priority} onChange={e=>setPriority(e.target.value as typeof priority)}>{['P0','P1','P2','P3'].map(p=><option key={p}>{p}</option>)}</select></label>{priority==='P0'&&<label><input type="checkbox" checked={fullFocus} onChange={e=>setFullFocus(e.target.checked)}/>已明确全力处理</label>}<button className="v2-button" disabled={busy} onClick={()=>void operate('core-priority',{priority,fullFocus})}>保存优先级</button>
      {c.pause?<button className="v2-button" disabled={busy} onClick={()=>void operate('core-resume')}>恢复提醒</button>:<div><label>恢复时间（北京时间，可不填）<input type="datetime-local" value={until} disabled={manual} onChange={e=>setUntil(e.target.value)}/></label><label><input type="checkbox" checked={manual} onChange={e=>setManual(e.target.checked)}/>等我主动恢复</label><p>未指定时，按下一个实际工作日9:00恢复；日历缺失时保留待核对。</p><button className="v2-button" disabled={busy} onClick={()=>void operate('core-pause',{until:until&&!manual?until+':00+08:00':'',manualResume:manual})}>暂停提醒</button></div>}
      <details><summary>P3 周度复查</summary><label>复查日<select aria-label="周度复查日" value={weekday} onChange={e=>setWeekday(e.target.value)}><option value="last">本周最后一个实际工作日</option>{['一','二','三','四','五','六','日'].map((day,i)=><option key={day} value={String(i+1)}>星期{day}</option>)}</select></label><label>复查时间（北京时间）<input type="time" value={weeklyTime} onChange={e=>setWeeklyTime(e.target.value)}/></label><button className="v2-button" disabled={busy} onClick={()=>void operate('core-weekly',{time:weeklyTime,...(weekday==='last'?{}:{weekday:Number(weekday)})})}>保存周度安排</button></details>
    </details>
    {!!c.steps?.length&&<details><summary>责任步骤</summary>{c.steps.map((step:Value)=><p key={step.id}>{step.title} · {s.people.find(p=>p.id===step.ownerId)?.title||'责任待核实'} · {{needed:'待处理',waiting:'等待结果',done:'已完成'}[step.state as string]||step.state}</p>)}</details>}
    {c.dependencies?.map((d:Value)=><details key={d.id}><summary>{d.result.reason}</summary><p>{d.window.dependency.affectedWork} · {d.window.dependency.impact}</p>{d.result.gaps?.map((g:string)=><p key={g}>{g}</p>)}{d.result.brief&&<p>{Object.values(d.result.brief).join('；')}</p>}{d.result.options?.map((o:Value)=><p key={o.title}>{o.title}：{o.impact}；成立前提：{o.preconditions}</p>)}</details>)}
    {c.delivery&&<details><summary>{c.delivery.delivered?'工程师交付已记录':'资料与协作准备'}</summary>{c.delivery.decision&&<p>{c.delivery.decision}</p>}<CoreMaterials s={s} materials={c.delivery.materials}/>{c.delivery.gaps.map((g:string)=><p key={g}>{g}</p>)}</details>}
    {c.preparation&&<p role="status">资料与协作准备：{c.preparation.reason||'等待核对'}</p>}<details><summary>检查与历史</summary><p>最后成功核对：{c.checks.lastSuccess||'尚无本轮记录'}</p><p>{c.checks.coverage||''}{c.checks.error||''}</p>{c.checks.gap&&<p>未覆盖时段：{c.checks.gap.from} 至 {c.checks.gap.to}</p>}{c.history.slice(-20).reverse().map((h:Value,i:number)=><p key={i}>{h.at} · {h.reason||({'assessment':'当前需要已核对','need-cycle':'待处理需要已更新','core-priority':'本人调整优先级','core-admit':'本人纳入跟进','core-pause':'本人暂停提醒','core-resume':'本人恢复提醒','core-weekly':'本人调整周度安排','pause-resumed':'到达恢复时间'} as Record<string,string>)[h.kind]||'跟进状态已更新'}</p>)}</details>{error&&<p role="alert">{error}</p>}
    <CoreCollaborationPanel workspaceId={s.workspaceId} sourceId={source.id} revision={source.version} request={request} onChanged={refresh}/>
  </section>;
}
export {CoreCollaborationPanel};
