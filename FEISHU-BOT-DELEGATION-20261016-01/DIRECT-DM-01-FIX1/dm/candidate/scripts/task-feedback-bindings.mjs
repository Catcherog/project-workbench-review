import {randomUUID,createHash} from 'node:crypto';
import {taskGuid} from './feishu-task-client.mjs';
const fail=(message,status=422)=>Object.assign(new Error(message),{status});
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
export class TaskFeedbackBindings {
  constructor({store,domain,client}){Object.assign(this,{store,domain,client});}
  target(workspaceId,deliverableId){const s=this.store.load(workspaceId),record=s.deliverables.find(d=>d.id===deliverableId&&!d.archived);if(!record)throw fail('交付物不存在或已归档',404);return {s,record};}
  async preview({workspaceId,deliverableId,url}){
    this.target(workspaceId,deliverableId);
    const signal=AbortSignal.timeout(35000),identity=await this.client.identity({signal}),task=await this.client.task(taskGuid(url),{signal});
    const preview={id:randomUUID(),workspaceId,deliverableId,identity,task,createdAt:new Date().toISOString()};
    this.store.setSetting('taskBinding:'+preview.id,preview);return preview;
  }
  async link({workspaceId,previewId}){
    const preview=this.store.getSetting('taskBinding:'+previewId);
    if(!preview||preview.workspaceId!==workspaceId)throw fail('任务关联预览不存在，请重新读取',409);
    if(Date.now()-Date.parse(preview.createdAt)>30*60000)throw fail('任务关联预览已过期，请重新读取',409);
    const identity=await this.client.identity({signal:AbortSignal.timeout(35000)});
    if(identity.scope!==preview.identity.scope||identity.userId!==preview.identity.userId)throw fail('飞书账号已变化，请重新读取',409);
    return this.store.transaction(()=>{
      const {s,record}=this.target(workspaceId,preview.deliverableId),task=preview.task,key=hash([identity.scope,task.guid]).slice(0,32),id='task-link-'+key;
      const existing=s.externalLinks.find(l=>l.system==='feishu_tasks'&&l.spaceKey===identity.scope&&l.remoteId===task.guid&&!l.archived);
      if(existing){if(s.actions.some(a=>a.id===existing.localObjectId&&(a.outputIds||[]).includes(record.id)))return {state:s,link:existing};throw fail('这项任务已关联其他工作，请先核对原关联，避免重复挂接。',409);}
      const at=new Date().toISOString(),actionId='task-action-'+key;
      const handling=this.domain.taskDefaultHandling(task,identity.userId),myRoles=this.domain.taskRoles(task,identity.userId);
      let next=this.domain.manualEdit(s,{kind:'actions',targetId:actionId,action:'create',before:{},after:{title:task.summary,projectIds:record.projectIds,outputIds:[record.id],executionChannel:'feishu_task',executionStatus:'待确认',acceptanceStatus:'待验收',status:handling==='attention'?'今天需要推动':'进展动态',taskObservationOnly:handling==='progress',dispatchDescription:task.description||'',followUp:handling==='attention'?'处理分配给我的任务':'',confirmed:true},requestId:'task-action-'+preview.id});
      next=this.domain.manualEdit(next,{kind:'externalLinks',targetId:id,action:'create',before:{},after:{title:'飞书任务 · '+task.summary,projectIds:record.projectIds,localObjectId:actionId,system:'feishu_tasks',remoteKind:'task',host:'applink.feishu.cn',spaceKey:identity.scope,remoteId:task.guid,verified:true,url:task.url||'',accountId:identity.userId,myRoles,handling,taskContext:{...task,readAt:preview.createdAt},boundAt:at},requestId:'task-binding-'+preview.id});
      this.store.save(next,s.revision);return {state:this.store.load(workspaceId),link:next.externalLinks.find(l=>l.id===id)};
    });
  }
  async attachment({workspaceId,sourceId,attachmentId}){
    const s=this.store.load(workspaceId),source=s.sources.find(row=>row.id===sourceId&&!row.archived&&this.domain.isCommentFeedback(row)),f=source?.feedback;
    if(!f?.channel.startsWith('feishu-task-')||!f.raw.attachments?.some(a=>a.guid===attachmentId))throw fail('附件不在当前反馈中',404);
    const link=this.domain.taskFeedbackLinks(s,source.projectIds).find(l=>l.id===f.externalObjectId&&l.remoteId===f.remoteId&&l.spaceKey===f.spaceKey);
    if(!link)throw fail('任务关联已失效，请核对后重试',409);
    const signal=AbortSignal.timeout(35000),a=await this.client.attachment(link,attachmentId,{signal});
    if(a.size>10*1024*1024)throw fail('附件大于 10 MB，请在飞书任务中查看');
    const response=await fetch(a.url,{signal,redirect:'error'});if(!response.ok)throw fail('附件下载未完成，请重试',502);
    let size=0;const chunks=[];for await(const chunk of response.body){size+=chunk.length;if(size>10*1024*1024)throw fail('附件超过读取大小限制');chunks.push(chunk);}
    const bytes=Buffer.concat(chunks);if(bytes.length!==a.size)throw fail('附件大小不匹配，请重试',502);
    return {name:a.name,mime:response.headers.get('content-type')||'application/octet-stream',base64:bytes.toString('base64'),sha256:createHash('sha256').update(bytes).digest('hex'),readAt:new Date().toISOString()};
  }
}
