"use client";
import {useEffect,useRef,useState} from 'react';
import type {V2State} from '../lib/v2-types';
import type {AssistantRequest} from './codex-assistant';
import {caseEvidenceAvailable} from '../lib/case-evidence';
import {EvidenceReader} from './evidence-reader';
import './core-materials.css';

type Material={id:string;title:string;reason?:string;library?:unknown;locator?:unknown};
type Props={s:V2State;materials:Material[];sourceId:string;jobId?:string;request:AssistantRequest};
type Reading={workspaceId:string;sourceId:string;jobId:string;materialId:string;original:{title:string;version:string;text:string;excerpt:string};limitations:string[]};

/** Only the reader remounts on scope/reference changes; surrounding drafts stay mounted. */
export function CoreMaterials(props:Props){
  const scope=JSON.stringify([props.s.workspaceId,props.sourceId,props.jobId||'',props.materials.map(m=>[m.id,m.library,m.locator])]);
  return <ScopedCoreMaterials key={scope} {...props}/>;
}

function ScopedCoreMaterials({s,materials,sourceId,jobId='',request}:Props){
  const [active,setActive]=useState<Material|null>(null);
  const [reading,setReading]=useState<Reading|null>(null);
  const [error,setError]=useState('');
  const generation=useRef(0),dialog=useRef<HTMLDialogElement>(null);
  const library=!!active&&(active.id.startsWith('library:')||!!active.library);
  const source=active&&!library?s.sources.find(row=>row.id===active.id):undefined;
  const available=!!source&&!source.archived&&!source.stale&&!s.sources.some(row=>!row.archived&&row.supersedesId===source.id)&&caseEvidenceAvailable(s,source);
  useEffect(()=>()=>{generation.current++;},[]);
  useEffect(()=>{
    const element=dialog.current;if(!element)return;
    if(active&&!element.open)element.showModal();
    if(!active&&element.open)element.close();
  },[active]);
  const close=()=>{generation.current++;dialog.current?.close();setActive(null);setReading(null);setError('');};
  async function open(material:Material){
    const current=++generation.current;
    setActive(material);setReading(null);setError('');
    if(!material.id.startsWith('library:')&&!material.library)return;
    try{
      const query=new URLSearchParams({workspaceId:s.workspaceId,sourceId,jobId,materialId:material.id});
      const result=await request<Reading>('/api/v2/core/material?'+query);
      if(generation.current!==current)return;
      if(result.workspaceId!==s.workspaceId||result.sourceId!==sourceId||result.jobId!==jobId||result.materialId!==material.id)throw Error('读取结果与原资料身份不一致，请重新打开');
      setReading(result);
    }catch(cause){if(generation.current===current)setError(cause instanceof Error?cause.message:'资源库读取失败，尚未取得正文');}
  }
  return <div className="core-materials">
    <ul>{materials.map(material=><li key={material.id}><button type="button" className="v2-text-button" onClick={()=>void open(material)}>阅读资料：{material.title}</button>{material.reason&&<p>{material.reason}</p>}</li>)}</ul>
    <dialog ref={dialog} className="core-material-dialog" aria-label="资料阅读" onKeyDown={event=>{if(['Escape','Tab'].includes(event.key))event.stopPropagation();}} onCancel={event=>{event.preventDefault();event.stopPropagation();close();}} onClose={event=>event.stopPropagation()}>
      <header><strong>{active?.title||'资料阅读'}</strong><button type="button" className="v2-button" onClick={close}>返回原处</button></header>
      {active&&(library?<>
        {error?<p role="alert">{error}。原事项与未提交草稿仍保留。</p>:!reading?<p role="status">正在核对资源库原引用并读取资料…</p>:<>
          <p className="iw-meta">资源库 · 版本 {reading.original.version} · {reading.limitations.join('；')}</p>
          <EvidenceReader s={s} evidence={{id:active.id,title:reading.original.title,available:true,author:'',occurredAt:'',text:reading.original.text}}/>
          <details><summary>本次准备引用的位置</summary><pre>{reading.original.excerpt}</pre></details>
        </>}
      </>:!source?<p role="alert">这份资料在当前工作区中未找到。请核对资料来源；原事项与未提交草稿仍保留。</p>:<>
        {!available&&<p role="status">这份来源当前已失效或不可用，下面仅为已有留存。没有重新获取访问权限或读取新内容。</p>}
        {source.intakeDocument?.error&&<p role="alert">资料读取未完成：{source.intakeDocument.error}</p>}
        <EvidenceReader s={s} evidence={{id:source.id,title:source.title,version:source.version,available,author:typeof source.author==='string'?source.author:'',occurredAt:source.occurredAt||source.collectedAt||'',text:source.excerpt||''}}/>
      </>)}
    </dialog>
  </div>;
}
