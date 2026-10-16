import {createHash} from 'node:crypto';
import {mkdtemp,readFile,stat,rm,realpath} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {FeishuTaskClient} from './feishu-task-client.mjs';
import {readIntakeCloud} from './intake-cloud.mjs';
import {readIntakeFile} from './intake-files.mjs';
import {verifiedGroupMessages} from './group-chat-reader.mjs';

const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const fail=message=>Object.assign(Error(message),{status:409});
const urls=text=>[...new Set(String(text||'').match(/https:\/\/[A-Za-z0-9.-]+\/(?:docx|wiki)\/[A-Za-z0-9]+/g)||[])];
const messageOf=source=>source.personalMessage?{...source.personalMessage,updateTime:source.personalMessage.rawUpdateTime}:source.caseChat?{...source.caseChat,messageType:source.caseChat.raw.msg_type,updateTime:source.caseChat.raw.update_time}:source.riskEvidence?.message;
function assets(text){
 const rows=[];
 for(const m of String(text||'').matchAll(/(?:\[Image:\s*|"image_key"\s*:\s*")([\w-]+)/g))rows.push({key:m[1],type:'image',name:'群聊图片.png'});
 for(const m of String(text||'').matchAll(/<file\b[^>]*key="([\w-]+)"[^>]*name="([^"]+)"/g))rows.push({key:m[1],type:'file',name:m[2]});
 try{const raw=JSON.parse(text);if(raw.file_key)rows.push({key:raw.file_key,type:'file',name:raw.file_name||'群文件'});}catch{/* Shortcut content is normally text. */}
 return [...new Map(rows.map(row=>[row.key,row])).values()];
}
export function riskResourceCatalog(state,proofs,domain){
 const rows=[{id:'local-search',kind:'search',title:'检索工作台已有原文',description:'按问题、项目名或人员检索已获准的本地资料；query 最多80字。'}],used=new Set();
 const add=row=>{if(!used.has(row.id)){rows.push(row);used.add(row.id);}};
 for(const proof of proofs){
  const source=state.sources.find(s=>s.id===proof.sourceId);if(!source||!domain.caseEvidenceAvailable(state,source))continue;
  for(const url of urls(source.excerpt))if(domain.safeFeishuResource(url))add({id:'doc-'+hash(url).slice(0,24),kind:'document',title:'读取云文档正文',url,parentId:source.id});
  const message=messageOf(source);
  if(message&&/^oc_[\w-]+$/.test(message.chatId||'')){
   const channels=source.personalMessage?.channels||[];
   if(source.caseChat||source.riskEvidence?.origin==='chat-message'||channels.some(c=>['mention','group-discovery'].includes(c)))add({id:'chat-'+hash(message.chatId).slice(0,24),kind:'chat',title:'补读同一群聊上下文',parentId:source.id,chatId:message.chatId});
   for(const asset of assets(source.excerpt))add({id:'asset-'+hash([message.messageId,asset.key]).slice(0,24),kind:'attachment',title:asset.name,parentId:source.id,...asset});
  }
 }
 return rows;
}

/** Executes only a resource already exposed in the job's read catalog. */
export class RiskEvidenceReader {
 constructor({store,domain,client=new FeishuTaskClient(),readFile=readIntakeFile,clock=()=>new Date().toISOString()}={}){Object.assign(this,{store,domain,client,readFile,clock});}
 async identity(parent,signal){
  const current=await this.client.identity({signal}),message=messageOf(parent)||parent.riskEvent||parent.riskEvidence?.cloudDocument;
  if(message&&(current.scope!==message.scope||current.userId!==message.accountId))throw fail('补查账号与原资料范围不一致');
  return current;
 }
 async verifyMessage(parent,signal){
  const m=messageOf(parent);if(!m?.messageId)return null;
  const raw=await this.client.run(['api','GET','/open-apis/im/v1/messages/mget','--params',JSON.stringify({message_ids:[m.messageId],with_sender_name:true}),'--as','user'],{signal});
  const row=raw.items?.find(row=>row.message_id===m.messageId);
  if(!row||row.chat_id!==m.chatId||row.deleted||m.updateTime&&row.update_time&&String(row.update_time)!==String(m.updateTime))throw fail('飞书原消息已变化或无法核对，请先重新采集');
  return row;
 }
 async read({workspaceId,resource,query='',signal}){
  const state=this.store.load(workspaceId);
  if(resource.kind==='search'){
   if(typeof query!=='string'||!query.trim()||query.length>80)throw fail('补查检索词须为1至80字');
   const terms=query.toLowerCase().split(/[\s，、,;；]+/).filter(Boolean);
   const matches=state.sources.filter(s=>!s.archived&&!s.workItem&&!s.managementSignal&&!s.intakeBatch&&!s.riskEvidence&&this.domain.caseEvidenceAvailable(state,s)).map(s=>({s,score:terms.reduce((score,t)=>score+(s.title+' '+(s.excerpt||'')).toLowerCase().includes(t)*1,0)})).filter(x=>x.score).sort((a,b)=>b.score-a.score).slice(0,5);
   return {documents:matches.map(({s})=>({existingSourceId:s.id})),limitations:matches.length?[]:['未在本地已接入原文中找到匹配资料']};
  }
  const parent=state.sources.find(s=>s.id===resource.parentId&&!s.archived);if(!parent||!this.domain.caseEvidenceAvailable(state,parent))throw fail('补查入口的原依据已失效');
  const identity=await this.identity(parent,signal);await this.verifyMessage(parent,signal);
  let documents=[];
  if(resource.kind==='document'){
   const doc=await readIntakeCloud({client:this.client,domain:this.domain,state,url:resource.url,signal});
   documents=[{title:doc.name==='飞书云文档'?(doc.parsed.text.match(/<title>([^<]+)<\/title>/)?.[1]||doc.name):doc.name,text:doc.parsed.text,url:doc.cloudDocument.url,complete:doc.parsed.complete,limitations:doc.parsed.limitations,origin:'document',cloudDocument:doc.cloudDocument}];
  }else if(resource.kind==='chat'){
   const time=Date.parse(parent.occurredAt||parent.collectedAt),now=Date.parse(this.clock());if(!Number.isFinite(time))throw fail('原消息时间不明确，不能推测读取范围');
   const start=new Date(Math.max(Date.parse(this.domain.feedbackCollectFrom),time-2*3600000)).toISOString(),end=new Date(Math.min(now,time+6*3600000)).toISOString();
   let token='',complete=false;const rows=[],seen=new Set();
   for(let i=0;i<3;i++){
    const data=await this.client.run(['im','+chat-messages-list','--chat-id',resource.chatId,'--start',start,'--end',end,'--order','desc','--page-size','50','--no-reactions','--as','user',...(token?['--page-token',token]:[])],{signal});
    if(!Array.isArray(data.messages)||typeof data.has_more!=='boolean')throw fail('群上下文分页不完整');
    rows.push(...await verifiedGroupMessages(this.client,data.messages,resource.chatId,{signal}));
    if(!data.has_more){complete=true;break;}if(!data.page_token||seen.has(data.page_token))throw fail('群上下文分页异常');token=data.page_token;seen.add(token);
   }
   documents=rows.filter(m=>!m.deleted&&Number(m.create_time)>=Date.parse(start)&&Number(m.create_time)<=Date.parse(end)).slice(0,60).map(m=>({title:parent.title+' · '+(m.sender.name||'群消息'),text:m.content,occurredAt:new Date(Number(m.create_time)).toISOString(),url:m.message_app_link||parent.url||'',origin:'chat-message',complete:complete&&rows.length<=60,limitations:complete&&rows.length<=60?[]:['仅补读本次限定窗口内最近60条消息，未覆盖全部群历史'],message:{messageId:m.message_id,chatId:resource.chatId,scope:identity.scope,accountId:identity.userId,messageType:m.msg_type,updateTime:m.update_time}}));
  }else if(resource.kind==='attachment'){
   const message=await this.verifyMessage(parent,signal),body=message?.body?.content||'';
   if(!body.includes(resource.key))throw fail('文件或图片已不在原消息内');
   const folder=await mkdtemp(path.join(tmpdir(),'pm-risk-read-'));
   try{
    const extension=path.extname(resource.name),filename='original'+(resource.type==='image'?'.png':/^\.[a-z0-9]{1,10}$/i.test(extension)?extension:'.bin'),target=path.join(folder,filename),m=messageOf(parent);
    const saved=await this.client.run(['im','+messages-resources-download','--message-id',m.messageId,'--file-key',resource.key,'--type',resource.type,'--output',filename,'--as','user'],{signal,cwd:folder});
    if(!saved?.saved_path||await realpath(path.resolve(folder,saved.saved_path))!==await realpath(target)||(await stat(target)).size>20*1024*1024)throw fail('原件位置或大小未通过核对');
    const bytes=await readFile(target);let parsed;
    try{parsed=await this.readFile({name:resource.name,bytes},{signal});}catch(error){if(signal?.aborted)throw error;parsed={text:'原件已保留，正文尚未成功读取。',images:[],complete:false,limitations:[error.message]};}
    await this.verifyMessage(parent,signal);
    documents=[{title:resource.name,text:parsed.text||'图片原件已读取，文字含义请结合图像核实。',url:parent.url||'',origin:'attachment',complete:parsed.complete,limitations:parsed.limitations,original:{name:resource.name,mime:resource.type==='image'?'image/png':'application/octet-stream',bytes},images:parsed.images||[]}];
   }finally{await rm(folder,{recursive:true,force:true});}
  }else throw fail('不支持的补查工具');
  const after=await this.client.identity({signal});if(after.scope!==identity.scope||after.userId!==identity.userId)throw fail('补查期间登录身份变化，结果未采用');
  return {documents,limitations:[]};
 }
}
