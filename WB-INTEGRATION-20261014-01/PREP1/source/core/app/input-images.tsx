"use client";
import {useState} from 'react';
import type {AssistantRequest} from './codex-assistant';
export type InputImage={id:string;name:string;url:string};
export function InputImages({workspaceId,request,images,onChange,disabled=false}:{workspaceId:string;request:AssistantRequest;images:InputImage[];onChange:(value:InputImage[])=>void;disabled?:boolean}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function add(files:FileList|null){
    if(!files?.length||busy)return;setBusy(true);setError('');const added:InputImage[]=[];
    try{
      if(images.length+files.length>8)throw Error('一次最多8张图片');
      for(const file of Array.from(files)){
        if(!file.type.startsWith('image/')||file.size>20*1024*1024)throw Error('请选择不超过20MB的图片');
        const base64=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('未读到原图'));reader.readAsDataURL(file);});
        const result=await request<{attachment:InputImage}>('/api/v2/attachments',{workspaceId,name:file.name,mime:file.type,base64});added.push(result.attachment);
      }
      onChange([...images,...added]);
    }catch(e){if(added.length)onChange([...images,...added]);setError(e instanceof Error?e.message:'图片尚未保存');}finally{setBusy(false);}
  }
  return <div className="p1-input-images"><label>添加原图<input type="file" accept="image/*" multiple disabled={disabled||busy} onChange={e=>{void add(e.target.files);e.currentTarget.value='';}}/></label>{busy&&<p role="status">正在保存原图…</p>}{images.length>0&&<ol>{images.map((image,index)=><li key={image.id}><span>图{index+1} · {image.name}</span><button type="button" className="v2-text-button" disabled={disabled||busy} onClick={()=>onChange(images.filter(x=>x.id!==image.id))}>移除</button>{index>0&&<button type="button" className="v2-text-button" disabled={disabled||busy} onClick={()=>{const next=[...images];[next[index-1],next[index]]=[next[index],next[index-1]];onChange(next);}}>前移</button>}</li>)}</ol>}{error&&<p role="alert">{error}</p>}</div>;
}
