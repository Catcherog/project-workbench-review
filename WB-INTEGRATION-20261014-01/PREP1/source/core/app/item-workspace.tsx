import type {Item} from '../lib/domain';
"use client";
import {ItemWorkspaceNavigation} from './item-workspace-navigation';
import {workItemState} from '../lib/work-items';

import React,{useEffect,useRef,useState} from 'react';
import {ArrowLeft,BookOpen,Clock3,FileText,Sparkles,X} from 'lucide-react';
import type {V2State} from '../lib/v2-types';
import {attentionLabel,attentionPresentation} from './attention-presentation';
import {handlingLabel,itemTime,itemTypeLabel,type ItemContext,type ItemEvidence} from './item-workspace-model';
import './item-workspace.css';
import {readInputDraft,writeInputDraft} from './local-draft';
import {EvidenceReader} from './evidence-reader';

export type ItemWorkspacePanels={feedback?:React.ReactNode;documents?:React.ReactNode;operations?:React.ReactNode;results?:React.ReactNode;assistant?:React.ReactNode;history?:React.ReactNode;hasResults?:boolean};
export type ItemPanelRenderer=(context:ItemContext)=>ItemWorkspacePanels;
type Props={openItem?:(id:string)=>void;initialEntry?:import('../lib/work-item-progress').P1EntrySeed;onLocalSaved?:(receipt:Omit<Item,'id'|'title'|'projectIds'|'sourceIds'>,stay:boolean)=>Promise<void>;s:V2State;context:ItemContext;panels?:ItemWorkspacePanels;onClose:()=>void;openRecord:(id:string)=>void};
type Page='work'|'evidence'|'history'|'assistant';

export function ItemWorkspace({s,context,panels={},onClose,openRecord,initialEntry,onLocalSaved,openItem}:Props){
  const dialog=useRef<HTMLDialogElement>(null),heading=useRef<HTMLHeadingElement>(null);
  const [entrySeed,setEntrySeed]=useState(initialEntry);
  const [page,setPage]=useState<Page>(initialEntry?'assistant':'work'),[reading,setReading]=useState<ItemEvidence|null>(null),[wide,setWide]=useState(false);
  const {item,record}=context;
  const workState=record?.workItem?workItemState(s,record):null;
  const presentation=attentionPresentation(s,item);
  const scrollKey='item-scroll:'+s.workspaceId+':'+item.targetId;
  const [initialScroll]=useState(()=>readInputDraft(scrollKey,{top:0}).top);
  const workScroll=useRef(Number.isFinite(initialScroll)?Math.max(0,initialScroll):0);
  const restoreFrame=useRef<number>(0);
  useEffect(()=>{
    const element=dialog.current,trigger=document.activeElement instanceof HTMLElement?document.activeElement:null;
    element?.showModal();heading.current?.focus({preventScroll:true});
    restoreFrame.current=requestAnimationFrame(()=>element?.scrollTo({top:workScroll.current}));
    return()=>{cancelAnimationFrame(restoreFrame.current);writeInputDraft(scrollKey,{top:workScroll.current});element?.close();if(trigger?.isConnected)trigger.focus({preventScroll:true});};
  },[scrollKey]);
  function show(next:Page,source:ItemEvidence|null=null){
    if(page==='work')workScroll.current=dialog.current?.scrollTop||0;
    const top=next==='work'?workScroll.current:0;
    setPage(next);setReading(source);cancelAnimationFrame(restoreFrame.current);
    restoreFrame.current=requestAnimationFrame(()=>dialog.current?.scrollTo({top}));
  }
  const history=s.audit.filter(entry=>entry.objectId===item.targetId);
  const projectNames=item.projectIds.map(id=>s.projects.find(row=>row.id===id)?.title||id);
  const caseName=item.caseId?s.cases.find(row=>row.id===item.caseId)?.title:'';
  const contextLabel=(record?.workItem?.association.kind==='personal'?'个人工作事项':'')||caseName||(projectNames.length>2?`${projectNames[0]} 等 ${projectNames.length} 个项目`:projectNames.join(' / '))||'归属待核对';
  const impact=item.impactSummary||record?.blockerImpact||record?.impact;
  const ownerLabel=item.owner&&/^(?:\d{8,}|(?:ou_|on_|user_)[\w-]+|[a-f\d]{24,})$/i.test(item.owner)?'负责人身份待核对':item.owner;
  const unavailable=context.evidence.filter(source=>!source.available);
  const evidence=reading?<EvidenceReader s={s} evidence={reading}/>:null;
  return <ItemWorkspaceNavigation.Provider value={{openAssistant:()=>show('assistant'),openItem:openItem||openRecord,entrySeed,editEntry:receipt=>{setEntrySeed({receipt});show('assistant');},saved:onLocalSaved,cancelEntry:()=>initialEntry?onClose():show('work')}}><dialog ref={dialog} className={'iw-dialog'+(wide?' iw-wide':'')} aria-labelledby="iw-title" onScroll={()=>{if(page==='work')workScroll.current=dialog.current?.scrollTop||0;}} onCancel={event=>{event.preventDefault();onClose();}}>
    <header className="iw-top"><div><span>{itemTypeLabel(s,item)} · {workState?.ignored?'已忽略':workState?.closed?'已处理':workState&&!workState.actionable?workState.hasNewData?'新变化':'资料留存':item.urgent?"立即介入 · "+handlingLabel(item):attentionLabel(item)}</span><h2 id="iw-title" ref={heading} tabIndex={-1}>{presentation.title}</h2></div><button className="iw-close" aria-label="关闭事项，返回清单" onClick={onClose}><X size={20}/></button></header>
    <div className="iw-content">
      {page!=='work'&&<button className="iw-back" onClick={()=>show('work')}><ArrowLeft size={16}/>返回当前事项</button>}
      <p className="iw-context">{contextLabel}</p>
      <div hidden={page!=='work'}>
        {!workState&&<section className="iw-summary" aria-label="本次判断"><h3>本次判断</h3><p>{presentation.reason}</p>
          {typeof impact==='string'&&impact&&impact!==item.reason&&<p className="iw-impact">影响：{impact}</p>}
          {(ownerLabel||item.date)&&<p className="iw-meta">{ownerLabel}{item.date?` · ${itemTime(item.date)}`:''}</p>}
          {item.requiresVerification&&<p className="iw-warning">待核实：当前判断仍需依据确认。</p>}
          {unavailable.length>0&&<p className="iw-warning">{unavailable.length} 份来源已失效或缺失，请先核对当前版本。</p>}
          {item.handlingState==='waiting'&&<p className="iw-waiting">{item.waitingReason||'等待外部回复'} · 下次跟进 {itemTime(item.nextCheckAt)}</p>}
        </section>}
        {!context.record?.workItem&&<section className="iw-block" aria-label="判断材料"><h3>判断材料</h3>{panels.documents}
          {context.evidence.map(source=><div className="iw-material" key={source.id}><FileText size={17}/><div><strong>{source.title}</strong><small>{source.available?'已留存':'需要重新核对'}{source.version!==undefined?` · v${source.version}`:''}{source.author?` · ${source.author}`:''}</small></div><button onClick={()=>show('evidence',source)}><BookOpen size={15}/>阅读</button></div>)}
          {!panels.documents&&!context.evidence.length&&<p className="iw-muted">当前没有已关联的材料。先核对提交与采集情况，再判断需要补什么。</p>}
        </section>}
        <section className="iw-block" data-item-section="operations" aria-label="我的处理"><h3>我的处理</h3>{panels.operations||<button onClick={()=>openRecord(item.targetId)}>记录判断与下一步</button>}</section>
        {panels.hasResults&&<section className="iw-block" aria-label="最近处理结果"><h3>最近处理结果</h3>{panels.results}</section>}
        <footer className="iw-footer">{!workState&&<button onClick={()=>show('history')}><Clock3 size={16}/>处理记录</button>}{panels.assistant&&<button onClick={()=>show('assistant')}><Sparkles size={16}/>问AI</button>}<button onClick={()=>openRecord(item.targetId)}>完整记录</button></footer>
      </div>
      {page==='evidence'?<section className="iw-block"><div className="iw-reader-tools"><button onClick={()=>setWide(v=>!v)}>{wide?'收回阅读宽度':'展开阅读宽度'}</button></div>{evidence}</section>:page==='assistant'?<section className="iw-block" aria-label="围绕当前事项问AI">{panels.assistant}</section>:page==='history'?<section className="iw-block" aria-label="处理历史">
        <h3>处理记录与关联</h3>{panels.history||panels.results}{panels.feedback}
        {history.map((entry,index)=><div className="iw-history" key={entry.id||index}><strong>{entry.operation||'记录更新'}</strong><p>{itemTime(entry.time)} · {entry.actor||'操作人未记录'}</p></div>)}
        {!history.length&&!panels.hasResults&&<p className="iw-muted">尚无已保存的处理结果。</p>}
        {item.relatedIds.map(id=><button key={id} onClick={()=>openRecord(id)}>查看关联：{s.actions.find(row=>row.id===id)?.title||s.sources.find(row=>row.id===id)?.title||id}</button>)}
      </section>:null}
    </div>
  </dialog></ItemWorkspaceNavigation.Provider>;
}
