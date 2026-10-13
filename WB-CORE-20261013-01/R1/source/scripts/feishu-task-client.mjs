import {resolveLarkCli} from './cli-runtime.mjs';
import {spawnMeegle} from './feishu-sync-cli.mjs';

const fail=(message,status=422)=>Object.assign(new Error(message),{status});
const guid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
export function taskGuid(value){
  if(typeof value!=='string')throw fail('请填写飞书任务链接或 GUID');
  if(guid.test(value.trim()))return value.trim().toLowerCase();
  try{const u=new URL(value.trim());if(u.protocol==='https:'&&u.hostname==='applink.feishu.cn'&&!u.username&&!u.password&&!u.port&&/^\/client\/todo\/(task|detail)$/.test(u.pathname)&&guid.test(u.searchParams.get('guid')||''))return u.searchParams.get('guid').toLowerCase();}catch{}
  throw fail('无法识别任务链接；请使用飞书任务的分享链接或 GUID');
}
export function stableTaskAttachment(row){
  // Download URLs expire within minutes; never use them as a source identity.
  const stable={...row};delete stable.url;return stable;
}
export class FeishuTaskClient {
  constructor({runner=spawnMeegle,cli=resolveLarkCli()}={}){Object.assign(this,{runner,cli});}
  async run(args,{signal,raw=false,cwd}={}){
    const result=await this.runner(this.cli,args,{signal,maxOutputBytes:6*1024*1024,shell:false,...(cwd?{cwd}:{})});
    let value;try{value=JSON.parse(result.stdout||result.stderr||'');}catch{throw fail('飞书返回无法解析的结果，请检查读取工具。',502);}
    if((result.status??result.exitCode??0)!==0||value.ok===false||value.error){
      const error=value.error||{},message=String(error.message||'');
      const failure=fail(error.missing_scopes?.length?'飞书权限缺口：'+error.missing_scopes.join('、'):/permission|forbidden|access denied|无权/i.test(message)?'当前用户无权读取这项飞书资源。':'飞书调用未完成：'+message.slice(0,200),502);
      // A CLI validation rejection occurs before the message request. Network,
      // API and unparseable failures are still unknown and must be reconciled.
      if(args[0]==='im'&&args[1]==='+messages-send'&&error.type==='validation')failure.definitelyNotSent=true;
      throw failure;
    }
    if(raw)return value;
    if(value.ok!==true||value.identity!=='user')throw fail('未确认使用当前飞书用户身份，已停止。',403);
    return value.data;
  }
  async identity(options={}){
    const who=await this.run(['whoami','--as','user'],{...options,raw:true});
    if(who.identity!=='user'||!who.available||who.brand!=='feishu'||!who.appId)throw fail('请先核对飞书用户登录。',401);
    const user=await this.run(['api','GET','/open-apis/authen/v1/user_info','--as','user'],options);
    if(!user.tenant_key||!user.open_id||user.open_id!==who.onBehalfOf?.openId)throw fail('飞书登录身份发生变化，请重新读取。',409);
    return {appId:who.appId,tenantKey:user.tenant_key,userId:user.open_id,name:user.name,scope:user.tenant_key+'/'+who.appId};
  }
  async assertScope(link,options={}){const identity=await this.identity(options);if(link.spaceKey!==identity.scope||link.accountId&&link.accountId!==identity.userId)throw fail('当前飞书账号与此任务关联的租户、应用或用户不一致。',409);return identity;}
  async resolveOwner(owner,options={}){
    const query=owner.email||owner.name;if(typeof query!=='string'||!query.trim()||query.length>50)throw fail('负责人缺少可核对的飞书查询信息');
    const data=await this.run(['contact','+search-user','--query',query,'--exclude-external-users','--as','user'],options);
    if(data?.has_more===true||!Array.isArray(data?.users))throw fail('负责人查询范围尚未完整，请核对具体身份');
    const normalized=value=>String(value||'').trim().toLowerCase();
    const matches=data.users.filter(user=>{
      const emails=[user.email,user.enterprise_email,user.work_email].filter(Boolean);
      const names=[user.name,user.name_cn,user.display_name,typeof user.localized_name==='string'?user.localized_name:user.localized_name?.zh_cn].filter(Boolean);
      const exact=owner.email?emails.some(email=>normalized(email)===normalized(owner.email)):names.some(name=>normalized(name)===normalized(owner.name));
      return exact&&/^ou_\w+$/.test(user.open_id||'')&&!user.is_cross_tenant&&!user.is_external&&user.is_activated!==false&&!user.left_organization;
    });
    if(matches.length!==1)throw fail('负责人未唯一匹配到当前飞书应用身份，不能按相似姓名发送');
    return {userId:matches[0].open_id,name:owner.name,meegleUserKey:owner.userKey,larkUserId:owner.larkUserId};
  }
  async task(id,options={}){
    const data=await this.run(['task','tasks','get','--params',JSON.stringify({task_guid:taskGuid(id),user_id_type:'open_id'}),'--as','user'],options);
    if(data?.task?.guid!==taskGuid(id))throw fail('飞书返回的任务身份不一致。',409);
    return data.task;
  }
  async related(options={}){
    const tasks=[],seen=new Set();let pageToken='';
    for(let page=0;page<40;page++){
      const data=await this.run(['task','+get-related-tasks','--as','user',...(pageToken?['--page-token',pageToken]:[])],options);
      if(!Array.isArray(data?.items)||typeof data.has_more!=='boolean')throw fail('相关任务分页结果不完整',502);
      tasks.push(...data.items);if(!data.has_more)return [...new Map(tasks.map(t=>[t.guid,t])).values()];
      if(!data.page_token||seen.has(data.page_token))throw fail('相关任务分页未完成',502);pageToken=data.page_token;seen.add(pageToken);
    }throw fail('相关任务超过本轮分页范围，请核对采集范围',502);
  }
  async pages(resource,id,options={}){
    const items=[],seen=new Set();let token='';
    for(let page=0;page<100;page++){
      const data=await this.run(['api','GET','/open-apis/task/v2/'+resource,'--params',JSON.stringify({resource_id:taskGuid(id),resource_type:'task',page_size:100,user_id_type:'open_id',...(token?{page_token:token}:{})}),'--as','user'],options);
      if(!Array.isArray(data?.items)||typeof data.has_more!=='boolean')throw fail('任务'+resource+'分页结果不完整。',502);
      items.push(...data.items);if(!data.has_more)return items;
      if(!data.page_token||seen.has(data.page_token))throw fail('任务反馈分页未完成，已保留先前记录。',502);
      token=data.page_token;seen.add(token);
    }
    throw fail('任务反馈分页超出本次读取上限，请缩小范围。',502);
  }
  async feedback(link,options={}){
    const identity=await this.assertScope(link,options);
    const task=await this.task(link.remoteId,options),reads=[],issues=[];
    const base={externalObjectId:link.id,remoteId:link.remoteId,spaceKey:link.spaceKey,collectedAt:new Date().toISOString(),complete:true,rangeVerified:false,viewer:{id:identity.userId,name:identity.name||''}};
    reads.push({...base,channel:'feishu-task-update',comments:[{id:'body',content:[task.summary,task.description].filter(Boolean).join('\n\n'),creator:task.creator,created_at:task.created_at,updated_at:task.updated_at,status:task.status,completed_at:task.completed_at,task_guid:task.guid}]});
    for(const resource of ['comments','attachments']){
      try{
        const items=await this.pages(resource,task.guid,options);
        if(items.some(row=>row.resource&&(row.resource.id!==task.guid||row.resource.type!=='task')))throw fail('反馈所属任务不一致。',409);
        const comments=resource==='comments'?items.map(row=>({...row,content:row.content??row.text,created_at:row.created_at??row.create_time,updated_at:row.updated_at??row.update_time,attachments:Array.isArray(row.attachments)?row.attachments.map(stableTaskAttachment):[]})):items.map(row=>({...stableTaskAttachment(row),id:row.guid,content:'任务附件：'+row.name,created_at:row.uploaded_at,creator:row.uploader,attachments:[stableTaskAttachment(row)]}));
        reads.push({...base,channel:resource==='comments'?'feishu-task-comment':'feishu-task-attachment',comments});
      }catch(error){if(options.signal?.aborted)throw error;issues.push(resource==='comments'?'任务评论：'+error.message:'任务附件：'+error.message);}
    }
    return {reads,issues,task:{...task,attachments:(task.attachments||[]).map(stableTaskAttachment)}};
  }
  async attachment(link,attachmentId,options={}){
    await this.assertScope(link,options);
    if(!guid.test(attachmentId))throw fail('附件身份无效。');
    const data=await this.run(['api','GET','/open-apis/task/v2/attachments/'+attachmentId,'--params',JSON.stringify({user_id_type:'open_id'}),'--as','user'],options),a=data?.attachment;
    if(a?.guid!==attachmentId||a.resource?.id!==link.remoteId||a.resource?.type!=='task')throw fail('附件所属任务已变化，停止读取。',409);
    const u=new URL(a.url);if(u.protocol!=='https:'||u.username||u.password||u.port||!['feishu.cn','feishucdn.com','larksuite.com','larkoffice.com'].some(h=>u.hostname===h||u.hostname.endsWith('.'+h)))throw fail('附件下载地址无法验证。');
    return a;
  }
}
