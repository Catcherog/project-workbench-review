"use client";
/* eslint-disable @next/next/no-img-element -- The local desktop serves retained evidence without a Next image optimizer. */
import type {V2State,V2Kind} from '../lib/v2-types';
import type {Item} from '../lib/domain';
import type {ItemEvidence} from './item-workspace-model';
import {itemTime} from './item-workspace-model';

export function EvidenceReader({s,evidence}:{s:V2State;evidence:ItemEvidence}) {
  const source=s.sources.find(row=>row.id===evidence.id);
  let snapshot:Item|null=null;
  if(source?.importedFrom?.system==='feishu')try{
    const value=JSON.parse(evidence.text);
    if(value&&typeof value==='object'&&!Array.isArray(value)&&value.fields&&value.kind)snapshot=value;
  }catch{/* Ordinary text stays readable when a historical record is incomplete. */}
  const fields=snapshot?.fields||{},raw=snapshot?.raw||{};
  const record=snapshot?s[ snapshot.kind as V2Kind ]:null;
  const object=Array.isArray(record)?record.find((row:Item)=>row.importedFrom?.sourceId===snapshot?.sourceId):null;
  const owner=raw.assignees?.owners?.map((row:Item)=>row.name).filter(Boolean).join('、')||fields.owner||'';
  const ownerLabel=/^(?:\d{8,}|ou_|on_)/.test(owner)?'负责人身份待核对':owner||'未记录';
  const projects=(source?.projectIds||[]).map((id:string)=>s.projects.find(row=>row.id===id)?.title).filter(Boolean);
  const facts=snapshot?[
    ['记录对象',snapshot.title||evidence.title],['所属项目',projects.join('、')||'未关联'],
    ['当时状态',fields.nodeStatus||fields.status||raw.basic?.status||'未记录'],['当时负责人',ownerLabel],
    ...(snapshot.kind==='deliverables'?[['交付物审核',fields.deliveryReview||fields.reviewStatus||'未记录']]:[]),
    ['进展说明',fields.progressNote||fields.deliverableProgress||'未记录'],
  ]:[];
  const attachments=(source?.attachments||[]).filter((file:Item)=>file.id);
  const url=(id:string)=>'/api/v2/attachments/'+encodeURIComponent(id)+'?workspaceId='+encodeURIComponent(s.workspaceId);
  return <article className="iw-reading">
    <h3>{evidence.title}</h3><p className="iw-meta">{evidence.author||'作者未提供'} · {itemTime(evidence.occurredAt)}{evidence.version!==undefined?` · v${evidence.version}`:''}</p>
    {!evidence.available&&<p className="iw-warning">来源已失效；以下为历史留存，需要重新核对当前情况。</p>}
    {snapshot?<>
      <p>这是采集时保存的业务记录，先看简介与关键字段。</p>
      <dl className="iw-snapshot-facts">{facts.map(([name,value])=><div key={name}><dt>{name}</dt><dd>{typeof value==='string'?value:'需核对原始记录'}</dd></div>)}</dl>
      {snapshot.kind==='flowNodes'&&<p className="iw-muted">本地明确关联的交付物：{s.deliverables.filter(row=>!row.archived&&object&&row.flowNodeIds?.includes(object.id)).length} 项。未关联不代表工程师没有交付。</p>}
      {!attachments.some((file:Item)=>/^image\//.test(file.mime||file.mimeType||''))&&<p className="iw-muted">这份记录未保存页面截图。</p>}
      <details><summary>查看原始字段记录</summary><pre>{evidence.text}</pre></details>
    </>:<pre>{evidence.text||'尚未取得正文。请核对来源读取状态。'}</pre>}
    {attachments.map((file:Item)=><div key={file.id}>{/^image\//.test(file.mime||file.mimeType||'')&&<img className="iw-evidence-image" src={url(file.id)} alt={file.name||'原始图像'}/>}<a href={url(file.id)} target="_blank" rel="noreferrer">查看原件：{file.name||'附件'}</a></div>)}
    {source?.url&&/^https?:\/\//.test(source.url)&&<a href={source.url} target="_blank" rel="noreferrer">打开来源</a>}
  </article>;
}
