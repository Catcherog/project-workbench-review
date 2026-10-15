"use client";
import {useEffect,useRef,useState} from 'react';
import type {V2State} from '../lib/v2-types';
import {caseEvidenceAvailable} from '../lib/case-evidence';
import {EvidenceReader} from './evidence-reader';
import './core-materials.css';

type Material={id:string;title:string;reason?:string};
/** Read the existing retained source in place; opening a document never navigates or writes. */
export function CoreMaterials({s,materials}:{s:V2State;materials:Material[]}){
  const [selection,setSelection]=useState<{workspaceId:string;id:string;title:string}|null>(null);
  const dialog=useRef<HTMLDialogElement>(null);
  const active=selection?.workspaceId===s.workspaceId?selection:null;
  const source=active?s.sources.find(row=>row.id===active.id):undefined;
  const available=!!source&&!source.archived&&!source.stale&&!s.sources.some(row=>!row.archived&&row.supersedesId===source.id)&&caseEvidenceAvailable(s,source);
  useEffect(()=>{
    const element=dialog.current;if(!element)return;
    if(active&&!element.open)element.showModal();
    if(!active&&element.open)element.close();
  },[active]);
  const close=()=>{dialog.current?.close();setSelection(null);};
  return <div className="core-materials">
    <ul>{materials.map(material=><li key={material.id}><button type="button" className="v2-text-button" onClick={()=>setSelection({workspaceId:s.workspaceId,id:material.id,title:material.title})}>阅读资料：{material.title}</button>{material.reason&&<p>{material.reason}</p>}</li>)}</ul>
    <dialog ref={dialog} className="core-material-dialog" aria-label="资料阅读" onKeyDown={event=>{if(['Escape','Tab'].includes(event.key))event.stopPropagation();}} onCancel={event=>{event.preventDefault();event.stopPropagation();close();}} onClose={event=>{event.stopPropagation();setSelection(null);}}>
      <header><strong>{active?.title||'资料阅读'}</strong><button type="button" className="v2-button" onClick={close}>返回原处</button></header>
      {!source?<p role="alert">这份资料在当前工作区中未找到。请核对资料来源；原事项与未提交草稿仍保留。</p>:<>
        {!available&&<p role="status">这份来源当前已失效或不可用，下面仅为已有留存。没有重新获取访问权限或读取新内容。</p>}
        {source.intakeDocument?.error&&<p role="alert">资料读取未完成：{source.intakeDocument.error}</p>}
        <EvidenceReader s={s} evidence={{id:source.id,title:source.title,version:source.version,available,author:typeof source.author==='string'?source.author:'',occurredAt:source.occurredAt||source.collectedAt||'',text:source.excerpt||''}}/>
      </>}
    </dialog>
  </div>;
}
