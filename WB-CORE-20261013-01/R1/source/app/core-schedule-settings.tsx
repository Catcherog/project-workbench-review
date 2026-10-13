"use client";
import {useEffect,useState} from 'react';
import {addDays,chinaDay,type WorkCalendar} from '../lib/work-calendar';
import type {AssistantRequest} from './codex-assistant';
type Settings={revision:number;enabled:boolean;lastTick:string;error:string};
export function CoreScheduleSettings({workspaceId,request}:{workspaceId:string;request:AssistantRequest}){
  const [settings,setSettings]=useState<Settings|null>(null),[calendar,setCalendar]=useState<WorkCalendar|null>(null),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
  const [from,setFrom]=useState(()=>chinaDay(Date.now())),[through,setThrough]=useState(()=>addDays(chinaDay(Date.now()),13)),[source,setSource]=useState(''),[days,setDays]=useState<Record<string,boolean>>({});
  useEffect(()=>{let active=true;void request<{settings:Settings;calendar:WorkCalendar|null}>('/api/v2/core?workspaceId='+encodeURIComponent(workspaceId)).then(v=>{if(!active)return;setSettings(v.settings);setCalendar(v.calendar);if(v.calendar){setFrom(v.calendar.from);setThrough(v.calendar.through);setDays(v.calendar.days);setSource(v.calendar.source);}}).catch(e=>{if(active)setError(String(e.message));});return()=>{active=false;};},[workspaceId,request]);
  const dates:string[]=[];if(from&&through&&from<=through)for(let day=from;day<=through&&dates.length<62;day=addDays(day,1))dates.push(day);
  async function save(enabled?:boolean){
    if(!settings||busy)return;setBusy(true);setError('');setNotice('');
    try{const value=enabled===undefined?{calendar:{id:calendar?.id||crypto.randomUUID(),revision:(calendar?.revision||0)+1,source,verifiedAt:new Date().toISOString(),from,through,days:Object.fromEntries(dates.map(day=>[day,days[day]===true]))}}:{enabled};
      const result=await request<{settings:Settings;calendar:WorkCalendar|null}>('/api/v2/core',{workspaceId,action:'configure',revision:settings.revision,...value});setSettings(result.settings);setCalendar(result.calendar);setNotice(enabled===undefined?'已保存本段实际工作日配置。':enabled?'持续跟进已启用；按当前证据与合法时段核对。':'持续跟进已暂停，历史和待处理保留。');
    }catch(e){setError(e instanceof Error?e.message:'未能保存设置');}finally{setBusy(false);}
  }
  return <section className="v2-settings-card" aria-label="持续跟进运行设置"><h2>持续跟进与工作日历</h2><p>{settings?.enabled?'已启用':'未启用'} · 最后检查：{settings?.lastTick||'暂无'}</p><p>常规提醒使用下面核对过的实际工作日。未覆盖日期会显示缺口；明确检查与真实紧急介入单独处理。</p><button className="v2-button" disabled={!settings||busy} onClick={()=>void save(!settings?.enabled)}>{settings?.enabled?'暂停持续跟进':'启用持续跟进'}</button>
    <details><summary>核对实际工作日</summary><p>勾选工作日，未勾选的日期按休息日保存。一次最多配置62天。</p><label>开始日期<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label><label>结束日期<input type="date" value={through} onChange={e=>setThrough(e.target.value)}/></label><label>依据或配置说明<input value={source} onChange={e=>setSource(e.target.value)} placeholder="例如：已核对的公司排班通知"/></label><div className="v2-toolbar">{dates.map(day=><label className="v2-check" key={day}><input type="checkbox" checked={days[day]===true} onChange={e=>setDays(v=>({...v,[day]:e.target.checked}))}/>{day}</label>)}</div><button className="v2-button" disabled={busy||!source.trim()||!dates.length||dates.at(-1)!==through} onClick={()=>void save()}>保存已核对日历</button></details>
    {notice&&<p role="status">{notice}</p>}{(error||settings?.error)&&<p role="alert">{error||settings?.error}</p>}
  </section>;
}
