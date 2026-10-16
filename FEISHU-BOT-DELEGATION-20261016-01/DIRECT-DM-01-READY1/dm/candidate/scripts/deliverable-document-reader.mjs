import {resolveLarkCli,resolveMeegleCli} from './cli-runtime.mjs';
import {mkdir, mkdtemp, readFile, writeFile, rename, rm, stat} from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnMeegle} from './feishu-sync-cli.mjs';

const fail=(message,status=422)=>Object.assign(new Error(message),{status});
const sha=value=>createHash('sha256').update(value).digest('hex');
const MAX_BYTES=2*1024*1024;
function attachmentBytes(value){
  const match=String(value).trim().match(/^(\d+(?:\.\d+)?)\s*(B|KB|KiB|MB|MiB)?$/i);
  return match?Number(match[1])*({b:1,kb:1024,kib:1024,mb:1024**2,mib:1024**2}[String(match[2]||'b').toLowerCase()]):NaN;
}
function userError(value){
  const text=typeof value==='string'?value:JSON.stringify(value);
  if(/permission|forbidden|403|无权|权限|access denied/i.test(text))return fail('当前用户无法读取这份文档，请核对飞书访问权限。',403);
  if(/login|token|refresh|auth|未登录|登录|401/i.test(text))return fail('飞书用户登录需要更新，请在前台完成登录后重试。',401);
  if(/ENOENT|not found/i.test(text))return fail('未找到文档或读取工具，请检查原文入口及本机配置。',503);
  return fail('文档读取未完成，请稍后重试或打开飞书原文。',502);
}

/** Bound read-only requests: resource URLs are resolved from the saved record,
 * never accepted from HTTP callers. No business state or remote state is written. */
export class DeliverableDocumentReader {
  constructor({store,domain,dataDir,runner=spawnMeegle,larkCli=resolveLarkCli(),meegleCli=resolveMeegleCli(),timeoutMs=35000}={}){
    Object.assign(this,{store,domain,runner,larkCli,meegleCli,timeoutMs});
    this.cacheDir=path.join(dataDir,'document-reads');this.controllers=new Set();this.pending=new Map();
  }
  resolve({workspaceId,deliverableId,documentKey}){
    if(![workspaceId,deliverableId,documentKey].every(value=>typeof value==='string' && value.length>0 && value.length<8000))throw fail('文档读取参数无效。',400);
    const state=this.store.load(workspaceId),record=state.deliverables.find(row=>row.id===deliverableId && !row.archived);
    if(!record)throw fail('当前工作区没有这项交付物。',404);
    const documents=this.domain.getDeliverableDocuments(state,record);
    const document=Object.values(documents.carriers).flatMap(carrier=>carrier.items).find(item=>item.key===documentKey);
    if(!document)throw fail('这份文档不在交付物当前已保存的关联中，请刷新后核对。',409);
    if(!document.readable)throw fail('此文件暂不支持文本阅读，请打开原文。');
    return {document,documents};
  }
  async run(executable,args,signal){
    let result;
    try{result=await this.runner(executable,args,{signal,maxOutputBytes:6*1024*1024,shell:false});}
    catch(error){if(signal.aborted)throw fail('读取超时或已取消，请重试。',504);throw userError(error.message);}
    let parsed;try{parsed=JSON.parse(result.stdout||'');}catch{throw userError(result.stderr||result.error||'invalid JSON');}
    if((result.status??result.exitCode??0)!==0 || parsed?.ok===false || parsed?.error || (parsed?.code!==undefined && ![0,'0'].includes(parsed.code)))throw userError(parsed?.error||result.stderr||parsed);
    return parsed;
  }
  async read(input){
    const resolved=this.resolve(input),cacheKey=sha(JSON.stringify([input.workspaceId,input.deliverableId,input.documentKey]));
    if(resolved.document.readable==='snapshot'){
      const record=this.store.load(input.workspaceId).deliverables.find(row=>row.id===input.deliverableId),saved=record.meetingDocument;
      if(Buffer.byteLength(saved.content)>MAX_BYTES)throw fail('纪要快照超过2 MB，请打开原文查看');
      if(sha(saved.content)!==saved.sha256)throw fail('归档纪要快照校验失败，请核对原件',409);
      return {documentKey:resolved.document.key,name:saved.title||record.title,url:saved.url,carrier:'results',format:'markdown',content:saved.content,revision:saved.revision,readAt:saved.readAt||record.updatedAt,sha256:saved.sha256,saved:true,snapshot:true};
    }
    if(this.pending.has(cacheKey))return this.pending.get(cacheKey);
    if(this.pending.size>=2)throw fail('已有文档正在读取，请稍后再打开。',429);
    const promise=this.perform(input,resolved,cacheKey);this.pending.set(cacheKey,promise);
    try{return await promise;}finally{this.pending.delete(cacheKey);}
  }
  async perform(input,{document,documents},cacheKey){
    const controller=new AbortController();this.controllers.add(controller);
    const timeout=setTimeout(()=>controller.abort(),this.timeoutMs);timeout.unref();
    let temp;
    try{
      let content,revision=null,raw,format;
      if(document.readable==='cloud'){
        raw=await this.run(this.larkCli,['docs','+fetch','--as','user','--doc',document.url,'--doc-format','markdown','--scope','full'],controller.signal);
        const data=raw?.data?.document;
        if(raw.identity!=='user')throw fail('无法确认读取使用了当前用户身份。',403);
        if(typeof data?.content!=='string' || !data.document_id)throw fail('飞书未返回可读正文，请打开原文。',502);
        if(document.documentType==='docx' && data.document_id!==document.token)throw fail('返回的文档身份不匹配，已停止显示。',409);
        content=data.content;revision=data.revision_id??null;format='markdown';
      }else{
        const size=attachmentBytes(document.size);
        if(!Number.isFinite(size)||size>MAX_BYTES)throw fail('附件大小未明确或超过 2 MB，请使用原文入口下载。');
        if(!documents.spaceKey || !/^\d+$/.test(documents.remoteId))throw fail('附件缺少已核对的空间或交付物身份，请先更新来源。',409);
        const auth=await this.run(this.meegleCli,['auth','status','--format','json'],controller.signal);
        if(auth.authenticated!==true || auth.host!=='project.feishu.cn')throw fail('飞书项目用户登录不可用或站点不一致，请在前台核对。',401);
        await mkdir(this.cacheDir,{recursive:true,mode:0o700});temp=await mkdtemp(path.join(this.cacheDir,'read-'));
        const target=path.join(temp,'attachment.txt');
        raw=await this.run(this.meegleCli,['attachment','+download',document.url,'--project-key',documents.spaceKey,'--work-item-id',documents.remoteId,'--output',target,'--format','json'],controller.signal);
        const info=await stat(target);if(info.size>MAX_BYTES)throw fail('附件超过 2 MB，请使用原文入口下载。');
        try{content=new TextDecoder('utf-8',{fatal:true}).decode(await readFile(target));}catch{throw fail('附件不是可识别的 UTF-8 文本，请下载原文件查看。');}
        format=/\.md$/i.test(document.name)?'markdown':'text';
      }
      if(controller.signal.aborted)throw fail('读取超时或已取消，请重试。',504);
      if(Buffer.byteLength(content)>MAX_BYTES)throw fail('正文超过 2 MB，请打开飞书原文查看。');
      // Recheck a link removed/reassigned during an in-flight read.
      const current=this.resolve(input);
      if(current.documents.remoteId!==documents.remoteId || current.documents.spaceKey!==documents.spaceKey)throw fail('交付物关联已变化，请刷新后重试。',409);
      const response={documentKey:document.key,name:document.name,url:document.url,carrier:document.carrier,format,content,revision,readAt:new Date().toISOString(),sha256:sha(content),saved:true};
      await mkdir(this.cacheDir,{recursive:true,mode:0o700});
      const saved={...response,workspaceId:input.workspaceId,deliverableId:input.deliverableId,raw};
      const target=path.join(this.cacheDir,cacheKey+'.json'),pending=target+'.pending';
      await writeFile(pending,JSON.stringify(saved),{mode:0o600});await rename(pending,target);
      const check=JSON.parse(await readFile(target,'utf8'));
      if(check.sha256!==sha(check.content))throw fail('本地阅读快照校验未通过，请重试。',500);
      return response;
    }finally{clearTimeout(timeout);this.controllers.delete(controller);if(temp)await rm(temp,{recursive:true,force:true});}
  }
  async close(){for(const controller of this.controllers)controller.abort();await Promise.allSettled([...this.pending.values()]);}
}
