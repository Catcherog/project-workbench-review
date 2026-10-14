import {workItemState,workItemRecordView} from '../lib/work-items';
"use client";

import {workbenchStatistics} from '../lib/workbench-statistics';
import { useMemo, useState } from 'react';
import { ChevronRight, Search } from 'lucide-react';
import type { WorkbenchOverviewProps } from './workbench-overview';
import { buildWorkbenchOverview, workbenchToday } from '../lib/workbench-overview';
import { attentionSections, handlingLabel, itemContext, itemKey, itemTime, itemTypeLabel, type ItemAttention } from './item-workspace-model';
import { attentionFilter, attentionFilters, attentionLabel, attentionPresentation, matchesAttentionFilter } from './attention-presentation';
import { ItemWorkspace } from './item-workspace';
import { FeedbackDetail } from './comment-feedback';
import { DeliverableDocuments } from './deliverable-documents';
import './attention-inbox.css';
import {riskSubcategories,riskSubcategory} from './risk-inbox-categories';

export function AttentionInbox({ s, initialProjectId = '', initialFilter = 'all', attentionItems, onSelectItem, renderItemPanels, open, feedbackAction, readDocument, navigate, onBulkReminders }: WorkbenchOverviewProps) {
  const day = workbenchToday();
  const model = useMemo(() => buildWorkbenchOverview(s, day, undefined, {includeDataReview:false}), [s, day]);
  const items = attentionItems || model.allAttention;
  const [showEnded,setShowEnded]=useState(false);
  const ended=s.sources.filter(r=>r.workItem&&!r.archived&&!r.workItem.mergedIntoId&&workItemState(s,r).closed&&!workItemState(s,r).ignored).map(r=>workItemRecordView(s,r));
  const [filter, setFilter] = useState(() => attentionFilter(initialFilter));
  const [urgentOnly, setUrgentOnly] = useState(initialFilter === 'urgent');
  const [project, setProject] = useState(initialProjectId);
  const [query, setQuery] = useState('');
  const [subclass,setSubclass]=useState('');
  const [selected, setSelected] = useState<ItemAttention | null>(null);
  const sections = attentionSections(items);
  const statistics=useMemo(()=>workbenchStatistics(s,{projectId:project}),[s,project]);
  const needle = query.trim().toLocaleLowerCase();
  const names = (item: ItemAttention) => item.projectIds.map(id => s.projects.find(row => row.id === id)?.title || id);
  const scope = (item: ItemAttention) => (!project || item.projectIds.includes(project) || item.caseId === project)
    && (!needle || [item.title, item.reason, ...item.reasons, ...names(item), s.cases.find(row => row.id === item.caseId)?.title || ''].join(' ').toLocaleLowerCase().includes(needle));
  const scoped = sections.focus.filter(scope);
  const baseMatches = (item:ItemAttention) => scope(item) && matchesAttentionFilter(item,filter) && (!urgentOnly || item.urgent);
  const categories=riskSubcategories(filter),available=sections.focus.filter(baseMatches);
  const effectiveSubclass=categories.some(([key])=>key===subclass)?subclass:categories.find(([key])=>available.some(item=>riskSubcategory(s,item,filter)===key))?.[0]||categories[0][0];
  const matches = (item: ItemAttention) => baseMatches(item) && riskSubcategory(s,item,filter)===effectiveSubclass;
  const focus = sections.focus.filter(matches), waiting = sections.waiting.filter(matches), handled = sections.handled.filter(matches);
  const otherUrgent=sections.focus.filter(item=>scope(item)&&item.urgent&&!matches(item));
  const current = selected && items.find(item => itemKey(s.workspaceId, item) === itemKey(s.workspaceId, selected));
  const context = current ? itemContext(s, current) : undefined;
  const select = onSelectItem || setSelected;
  function row(item: ItemAttention) {
    const presentation = attentionPresentation(s, item), projects = names(item);
    const scopeName = item.caseId ? s.cases.find(value => value.id === item.caseId)?.title : projects.length > 1 ? `跨 ${projects.length} 个项目` : projects[0];
    return <button key={itemKey(s.workspaceId, item)} className={'att-row' + (item.urgent ? ' is-urgent' : '')} data-attention-id={item.id} data-handling-state={item.handlingState || 'attention'} onClick={() => select(item)}>
      <span className="att-copy"><small>{scopeName || '归属待核对'} · {presentation.type || itemTypeLabel(s, item)}</small><strong title={item.title}>{presentation.title}</strong><span>{showEnded?s.sources.find(r=>r.id===item.targetId)?.workItem?.p1?.lifecycle?.reason||presentation.reason:presentation.reason}</span>{item.nextCheckAt && <small>下次跟进 {itemTime(item.nextCheckAt)}</small>}</span>
      <span className="att-state">{showEnded?'已结束':item.urgent ? '紧急' : attentionLabel(item)}{!showEnded&&item.handlingState && item.handlingState !== 'attention' && <small>{handlingLabel(item)}</small>}{!showEnded&&item.requiresVerification && <small>待核实</small>}{showEnded&&<small>{itemTime(s.sources.find(r=>r.id===item.targetId)?.workItem?.p1?.lifecycle?.at||s.sources.find(r=>r.id===item.targetId)?.workItem?.reviews?.at(-1)?.at)}</small>}</span><ChevronRight size={17}/>
    </button>;
  }
  return <div className="att-inbox">
    {s.workspaceType === 'demo' && <p className="wo-demo-note">虚构演示数据</p>}
    <details className="att-waiting" data-testid="business-statistics"><summary>整合事项 {statistics.items.total} · 未关闭风险 {statistics.risks.open}（待核实 {statistics.risks.pending} · 已确认 {statistics.risks.confirmed}）</summary><p>当前{project?'项目或专项':'工作区'}：已解除 {statistics.risks.resolved} · 不成立 {statistics.risks.dismissed} · 已忽略 {statistics.risks.ignored}。事项统计包含已处理记录；下方筛选用于查看待办。</p></details>
<div className="att-filter-bar"><div className="att-filters" aria-label="待处理事项类型">{attentionFilters.map(([key, label]) => <button key={key} aria-pressed={!showEnded&&filter === key} onClick={() => {setFilter(key);setSubclass('');setShowEnded(false);}}>{label}<span>{scoped.filter(item => matchesAttentionFilter(item, key) && (!urgentOnly || item.urgent)).length}</span></button>)}<button aria-pressed={showEnded} onClick={()=>setShowEnded(true)}>已结束<span>{ended.filter(scope).length}</span></button></div>
      <div className="att-secondary-actions" aria-label="风险管理辅助操作"><button onClick={()=>navigate('review')}>业务修改审核</button>{onBulkReminders&&<button onClick={onBulkReminders}>批量私信催办</button>}</div></div>
    <div className="att-toolbar"><select aria-label="按项目筛选待处理事项" value={project} onChange={e => setProject(e.target.value)}><option value="">全部项目与专项</option>{s.cases.filter(row => !row.archived).map(row => <option key={row.id} value={row.id}>专项 · {row.title}</option>)}{model.projects.map(row => <option key={row.project.id} value={row.project.id}>{row.project.title}</option>)}</select><label className="att-search"><Search size={17}/><input aria-label="搜索待处理事项" placeholder="搜索事项或项目" value={query} onChange={e => setQuery(e.target.value)}/></label></div>
    <nav className="att-subcategories" aria-label="事项二级分类">{categories.map(([key,label])=><button key={key} aria-pressed={effectiveSubclass===key} onClick={()=>setSubclass(key)}>{label}<span>{available.filter(item=>riskSubcategory(s,item,filter)===key).length}</span></button>)}</nav>
    <div className="att-hint"><span>{filter === 'check' ? '先核对事实、证据与必要性，再确定下一步' : '先看要推动的事；等待回复和处理记录在下方'}</span>{(scoped.some(item => item.urgent) || urgentOnly) && <button aria-pressed={urgentOnly} onClick={() => setUrgentOnly(!urgentOnly)}>只看紧急</button>}</div>
    {!showEnded&&otherUrgent.length>0&&<section aria-label="其他分类中的紧急事项"><h3>需要立即介入</h3><div className="att-list">{otherUrgent.map(row)}</div></section>}
    <section className="att-list" aria-label="需要你处理的事项">{(showEnded?ended.filter(scope):focus).map(row)}{!(showEnded?ended.filter(scope):focus).length && <p className="att-empty">{items.length ? '当前筛选下暂无待处理事项' : '暂无需要你处理的事项'}</p>}</section>
    {!showEnded&&waiting.length > 0 && <details className="att-waiting"><summary>等待回复 <span>{waiting.length}</span><small>下次跟进 {itemTime(waiting.map(item => item.nextCheckAt).filter((value): value is string => !!value).sort()[0])}</small></summary>{waiting.map(row)}</details>}
    {!showEnded&&handled.length > 0 && <details className="att-waiting"><summary>已处理记录 <span>{handled.length}</span></summary>{handled.map(row)}</details>}
    {selected && !current && <p role="status">事项已更新，请重新选择。<button onClick={() => setSelected(null)}>知道了</button></p>}
    {context && <ItemWorkspace key={context.key} s={s} context={context} onClose={() => setSelected(null)} openRecord={open} panels={{
      feedback: current?.feedbackSourceIds?.map(id => { const source = s.sources.find(row => row.id === id); return source ? <FeedbackDetail key={id} s={s} source={source} action={feedbackAction} open={open}/> : null; }),
      documents: current?.kind === 'deliverables' && context.record ? <DeliverableDocuments s={s} record={context.record} readDocument={readDocument} compact/> : undefined,
      ...renderItemPanels?.(context),
    }}/>}
  </div>;
}
