import {createHash} from 'node:crypto';
import {mkdtemp,readFile,stat,rm} from 'node:fs/promises';
import path from 'node:path';
import {parse} from 'parse5';

const hash=value=>createHash('sha256').update(value).digest('hex');
const fail=(message,status=422)=>Object.assign(new Error(message),{status});
// HTML reports often embed images. Keep the original within the store's 20 MB
// attachment limit, while limiting extracted text independently.
const MAX_BYTES=20*1024*1024,MAX_TEXT_BYTES=2*1024*1024;

export function extractChatFile(bytes,name){
  if(bytes.length>MAX_BYTES)throw fail('文件超过 20 MB，暂不提取正文，请从飞书查看');
  let text;try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{throw fail('文件不是 UTF-8 文本，请从飞书查看原文件');}
  if(/\.(html?)$/i.test(name)){
    const chunks=[],blocks=new Set(['p','div','section','article','header','footer','li','tr','h1','h2','h3','h4','h5','h6','br','table']);
    const stack=[parse(text)];
    while(stack.length){
      const node=stack.pop();if(typeof node==='string'){chunks.push(node);continue;}
      if(['head','script','style','template','noscript','iframe','object','svg','canvas','button'].includes(node.tagName))continue;
      if(node.attrs?.some(a=>a.name==='hidden'||a.name==='aria-hidden'&&a.value==='true'||a.name==='style'&&/(?:display\s*:\s*none|visibility\s*:\s*hidden)/i.test(a.value)))continue;
      const attrs=Object.fromEntries((node.attrs||[]).map(a=>[a.name,a.value]));
      if(node.tagName==='input'){
        const type=(attrs.type||'text').toLowerCase();
        if(['hidden','submit','reset','button','image','file'].includes(type))continue;
        chunks.push(['checkbox','radio'].includes(type)?('checked' in attrs?' [已选] ':' [未选] '):' '+(attrs.value||'')+' ');continue;
      }
      if(node.tagName==='select'){
        const options=[],pending=[...(node.childNodes||[])];
        while(pending.length){const child=pending.shift();if(child.tagName==='option')options.push(child);else pending.unshift(...(child.childNodes||[]));}
        let selected=options.filter(o=>o.attrs?.some(a=>a.name==='selected'));
        if(!selected.length&&!('multiple' in attrs))selected=options.slice(0,1);
        chunks.push(' ');stack.push(' ');for(let i=selected.length-1;i>=0;i--)stack.push(selected[i]);continue;
      }
      if(blocks.has(node.tagName))chunks.push('\n');
      if(node.nodeName==='#text')chunks.push(node.value);
      if(blocks.has(node.tagName))stack.push('\n');
      if(['td','th'].includes(node.tagName))stack.push('\t');
      for(let i=(node.childNodes?.length||0)-1;i>=0;i--)stack.push(node.childNodes[i]);
    }
    text=chunks.join('').replace(/[ \t]+/g,' ').replace(/ *\n */g,'\n').replace(/\n{3,}/g,'\n\n').trim();
  }else if(!/\.(md|txt|csv|json|log)$/i.test(name))throw fail('此格式暂不支持正文提取，请从飞书查看原文件');
  if(!text.trim())throw fail('未提取到可读正文；原文件可能只有图片，请从飞书核对');
  if(Buffer.byteLength(text)>MAX_TEXT_BYTES)throw fail('提取正文超过 2 MB，请从飞书核对原文件');
  return {content:text,sha256:hash(bytes),textSha256:hash(text),format:/\.html?$/i.test(name)?'html-text':'text',limitations:/\.html?$/i.test(name)?'仅提取文字与表格文字；图片、图纸和原文版式请查看原文件。':'正文已按 UTF-8 文本读取。'};
}

/** The thread endpoint has no time filter. Use original timestamps, never guess
 * the timezone of the CLI's formatted display strings. */
export async function readCaseThreads({client,domain,binding,messages,end,signal,maxThreads=40,maxPages=40}){
  const threads=[...new Set(messages.map(m=>m.thread_id).filter(Boolean))],replies=[],errors=[];let completed=0;
  for(const threadId of threads.slice(0,maxThreads)){
    if(!/^om[t]?_[\w-]+$/.test(threadId)){errors.push('讨论串标识无效');continue;}
    let token='',done=false;const seen=new Set();
    try{
      for(let page=0;page<maxPages;page++){
        const data=await client.run(['api','GET','/open-apis/im/v1/messages','--params',JSON.stringify({container_id_type:'thread',container_id:threadId,page_size:50,sort_type:'ByCreateTimeAsc',with_sender_name:true,...(token?{page_token:token}:{})}),'--as','user'],{signal});
        if(!Array.isArray(data?.items)||typeof data.has_more!=='boolean')throw fail('讨论串分页结果不完整',502);
        for(const raw of data.items){
          if(typeof raw.message_id!=='string'||raw.chat_id!==binding.chatId||raw.thread_id&&raw.thread_id!==threadId)throw fail('讨论串消息归属不一致',409);
          const time=domain.feedbackTime(raw.create_time);
          if(!time){errors.push('讨论串 '+threadId+' 有消息缺少可靠时间，未纳入正文');continue;}
          if(Date.parse(time)<Date.parse(domain.feedbackCollectFrom)||Date.parse(time)>Date.parse(end)||raw.msg_type==='system')continue;
          let content=raw.body?.content??raw.content??'';
          try{const parsed=JSON.parse(content);if(typeof parsed.text==='string')content=parsed.text;}catch{}
          replies.push({...raw,thread_id:threadId,content:typeof content==='string'?content:JSON.stringify(content),create_time:time,original_create_time:raw.create_time,message_app_link:domain.safeFeishuUrl(raw.message_app_link)||binding.url});
        }
        if(!data.has_more){done=true;completed++;break;}
        if(!data.page_token||seen.has(data.page_token))throw fail('讨论串分页游标未推进',502);token=data.page_token;seen.add(token);
      }
      if(!done)errors.push('讨论串 '+threadId+' 达到分页上限，保留已读回复');
    }catch(error){if(signal.aborted)throw error;errors.push('讨论串 '+threadId+'：'+error.message);}
  }
  if(threads.length>maxThreads)errors.push('讨论串数量超过本次上限，保留已读回复');
  return {messages:replies,errors,coverage:{discovered:threads.length,completed,replies:replies.length}};
}

export async function readCaseFile(intake,{workspaceId,caseId,sourceId,fileKey},signal){
  const resolve=()=>{
    const s=intake.store.load(workspaceId),row=intake.get(workspaceId,caseId),source=intake.domain.caseSources(s,caseId).find(src=>src.id===sourceId);
    if(!source?.caseChat||!intake.domain.caseEvidenceAvailable(s,source)||source.caseChat.chatId!==row.chatBinding?.chatId||source.caseChat.scope!==row.chatBinding?.scope||source.caseChat.accountId!==row.chatBinding?.accountId)throw fail('原消息已变化或不属于当前专项群，请刷新群消息',409);
    const file=intake.domain.chatFiles(source.caseChat.raw).find(f=>f.key===fileKey);if(!file?.readable)throw fail('该文件不在当前消息中或暂不支持正文读取');
    return {source,row,file};
  };
  const {source,row,file}=resolve(),identity=await intake.client.identity({signal});
  if(identity.scope!==row.chatBinding.scope||identity.userId!==row.chatBinding.accountId)throw fail('当前账号与群来源不一致',409);
  const latest=await intake.client.run(['im','+messages-mget','--message-ids',source.caseChat.messageId,'--no-reactions','--as','user'],{signal});
  const message=latest?.messages?.find(m=>m.message_id===source.caseChat.messageId);
  if(!message||message.chat_id!==source.caseChat.chatId)throw fail('未能核对飞书原消息归属，请重新读取群消息',409);
  if(message.deleted||!intake.domain.chatFiles(message).some(f=>f.key===fileKey&&f.name===file.name)){
    intake.mutate(workspaceId,caseId,(s,current)=>{
      const parent=s.sources.find(src=>src.id===source.id);if(!parent||parent.caseChat.rawHash!==source.caseChat.rawHash)throw fail('原消息已经变化，请刷新',409);
      parent.caseChat.history=[...(parent.caseChat.history||[]),{raw:parent.caseChat.raw,collectedAt:parent.collectedAt}];parent.caseChat.raw=message;parent.caseChat.rawHash=hash(JSON.stringify(message));parent.excerpt=message.deleted?'消息已撤回，历史版本保留。':typeof message.content==='string'?message.content:JSON.stringify(message.content||{});parent.collectedAt=intake.clock();parent.version++;
      current.caseAnalysis={status:intake.analysisSources(s,current).length?'pending':'empty'};
    });
    void intake.scheduleSuggest({workspaceId,caseId}).catch(()=>{});
    throw fail('飞书原消息已变化或撤回，已保留旧文件版本；请重新核对依据',409);
  }
  const temp=await mkdtemp(path.join(intake.store.dir,'case-file-'));
  try{
    const target=path.join(temp,'source.bin');
    const result=await intake.client.run(['im','+messages-resources-download','--message-id',source.caseChat.messageId,'--file-key',fileKey,'--type','file','--output',target,'--as','user'],{signal});
    if(path.resolve(result?.saved_path||'')!==target)throw fail('下载文件路径未通过核对',502);
    const info=await stat(target);if(info.size>MAX_BYTES)throw fail('文件为 '+(info.size/1024/1024).toFixed(1)+' MB，超过 20 MB，请从飞书查看');
    const bytes=await readFile(target),text=extractChatFile(bytes,file.name);
    if(signal.aborted)throw fail('读取已取消',504);
    const checked=resolve();if(checked.source.caseChat.rawHash!==source.caseChat.rawHash)throw fail('读取期间原消息已变化，请重试',409);
    const id='case-file-'+hash(JSON.stringify([source.id,fileKey])).slice(0,36),at=intake.clock();let changed=false;
    const saved=intake.store.load(workspaceId).sources.find(src=>src.id===id);
    const attachment=saved?.attachments?.find(a=>a.sha256===text.sha256)||intake.store.attach(workspaceId,{name:file.name,mime:'application/octet-stream',base64:bytes.toString('base64')});
    if(intake.store.attachment(workspaceId,attachment.id).sha256!==text.sha256)throw fail('本地原文件校验失败',500);
    const state=intake.mutate(workspaceId,caseId,(s,current)=>{
      const prior=s.sources.find(src=>src.id===id),caseIds=[...new Set([...(prior?.caseIds||[]),caseId])];
      if(prior?.caseFile?.sha256===text.sha256&&prior.caseFile.textSha256===text.textSha256&&prior.caseFile.parentHash===source.caseChat.rawHash&&prior.caseIds.includes(caseId)){prior.caseFile.checkedAt=at;return true;}
      const value={...(prior||{}),id,title:file.name,type:'群文件正文',projectIds:prior?.projectIds||[],sourceIds:[source.id],caseIds,objectIds:[...new Set([...(prior?.objectIds||[]),caseId])],author:source.author,url:source.url,excerpt:text.content,occurredAt:source.occurredAt||'',collectedAt:at,confirmed:false,version:(prior?.version||0)+1,archived:false,attachments:[attachment],caseFile:{schemaVersion:1,parentSourceId:source.id,parentHash:source.caseChat.rawHash,fileKey,name:file.name,sha256:text.sha256,textSha256:text.textSha256,format:text.format,limitations:text.limitations,readAt:at,history:prior?[...(prior.caseFile?.history||[]),{version:prior.version,excerpt:prior.excerpt,readAt:prior.collectedAt,attachments:prior.attachments,sha256:prior.caseFile.sha256}]:[]}};
      if(prior)Object.assign(prior,value);else s.sources.push(value);
      current.sourceIds=[...new Set([...current.sourceIds,id])];current.caseAnalysis={status:'pending'};changed=true;
    });
    if(changed)void intake.scheduleSuggest({workspaceId,caseId}).catch(()=>{});
    return {state,sourceId:id,changed};
  }finally{await rm(temp,{recursive:true,force:true});}
}
