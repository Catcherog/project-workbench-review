import {resolveMeegleCli} from './cli-runtime.mjs';
import {createHash} from 'node:crypto';
import {mkdtemp,readFile,stat,rm} from 'node:fs/promises';
import path from 'node:path';
import {FeishuTaskClient} from './feishu-task-client.mjs';
import {MeegleSyncAdapter} from './feishu-sync-cli.mjs';
import {caseChatId} from './case-chat-intake.mjs';
import {readCaseThreads} from './case-evidence-reader.mjs';
import {readIntakeFile} from './intake-files.mjs';
import {verifiedGroupMessages,normalizeGroupMessage,groupMessageFingerprint} from './group-chat-reader.mjs';
const hash=value=>createHash('sha256').update(typeof value==='string'?value:JSON.stringify(value)).digest('hex');
const fail=(message,status=409)=>Object.assign(Error(message),{status});
const groupPattern=/^oc_[a-zA-Z0-9]{8,100}$/;
export class ProjectGroupMetadata {
  constructor({adapter}={}){
    this.adapter=adapter||new MeegleSyncAdapter({cli:resolveMeegleCli(),profile:process.env.PM_MEEGLE_PROFILE||'',host:'project.feishu.cn'});
  }
  auth(options){return this.adapter.auth(options);}
  async group(object,{signal}={}){
    const response=await this.adapter._run('workitem get',{project_key:object.spaceKey,work_item_id:object.remoteId,fields:['group_type']},{signal});
    const raw=response.work_item_attribute?response:response.data,attribute=raw?.work_item_attribute;
    if(!attribute||String(attribute.work_item_id)!==String(object.remoteId)||![attribute.owned_project?.key,attribute.owned_project?.simple_name].includes(object.spaceKey))throw fail('项目群读取的空间或工作项身份不一致');
    const fields=raw.work_item_fields?.filter(field=>field.key==='group_type')||[];
    if(fields.length!==1||!['auto','bind','disabled'].includes(fields[0].value?.value))throw fail('未取得明确的group_type，不能推定项目没有关联群');
    const value=fields[0].value;
    if(value.value!=='disabled'&&!groupPattern.test(value.group_id||''))throw fail('项目群尚未返回稳定群标识');
    return {mode:value.value,chatId:value.value==='disabled'?'':value.group_id,projectRemoteId:String(attribute.work_item_id),metadataFingerprint:hash(value)};
  }
}
export class ProjectChatIntake {
  constructor({store,domain,materialIntake,client=new FeishuTaskClient(),metadata=new ProjectGroupMetadata(),readFile=readIntakeFile,onCaseChanged=()=>{},clock=()=>new Date().toISOString()}){
    Object.assign(this,{store,domain,materialIntake,client,metadata,readFile,onCaseChanged,clock});this.jobs=new Map();this.closed=false;
  }
  control(id){this.store.load(id);return {revision:0,enabled:false,intervalSeconds:300,nextReadAt:'',failures:0,lastError:'',...(this.store.getSetting('projectChats:'+id)||{})};}
  scopes(state){return state.sources.filter(source=>!source.archived&&source.chatScope);}
  status(id){
    const s=this.store.load(id);return {...this.control(id),running:this.jobs.has(id),collectFrom:this.domain.feedbackCollectFrom,
      scopes:this.scopes(s).map(source=>({id:source.id,version:source.version,...source.chatScope,state:source.chatScope.projectId&&!s.projects.some(p=>p.id===source.chatScope.projectId&&!p.archived)?'disabled':source.chatScope.state,read:this.store.getSetting('projectChatRead:'+id+':'+source.chatScope.chatId),projectTitle:s.projects.find(p=>p.id===source.chatScope.projectId)?.title||'指定工作群'}))};
  }
  save(id,fn){
    return this.store.transaction(()=>{const before=this.store.load(id),next=structuredClone(before);if(fn(next)===false)return before;
      this.materialIntake?.captureCollected(before,next);next.revision++;const errors=this.domain.validateState(next);if(errors.length)throw fail(errors.map(e=>e.message).join('；'));
      this.store.save(next,before.revision);return this.store.load(id);});
  }
  configure({workspaceId,revision,enabled}){
    const s=this.store.load(workspaceId),c=this.control(workspaceId);
    if(typeof enabled!=='boolean'||c.revision!==revision)throw fail('项目群采集设置已更新');
    if(enabled&&s.workspaceType==='restored')throw fail('恢复工作区的采集保持暂停，请在正式工作区配置');
    this.store.setSetting('projectChats:'+workspaceId,{...c,enabled,revision:c.revision+1,failures:0,lastError:'',nextReadAt:enabled?this.clock():''});
    if(enabled)void this.poll(workspaceId);else this.jobs.get(workspaceId)?.controller.abort();
    return this.status(workspaceId);
  }
  scope(state,key,value){
    const id='chat-scope-'+hash(key).slice(0,28),old=state.sources.find(source=>source.id===id),at=this.clock();
    const history=old?[...(old.chatScope.history||[]),...(old.chatScope.chatId!==value.chatId||old.chatScope.state!==value.state?[{...old.chatScope,history:undefined}]:[])]:[];
    const source={...(old||{}),id,title:value.name||'项目群采集范围',type:'采集范围记录',projectIds:value.projectId?[value.projectId]:[],sourceIds:[],objectIds:[],confirmed:true,version:(old?.version||0)+1,collectedAt:old?.collectedAt||at,updatedAt:at,excerpt:'已核对的群范围配置；不表示已读取群消息或完成业务工作。',chatScope:{schemaVersion:1,...value,history,verifiedAt:at}};
    if(old)Object.assign(old,source);else state.sources.push(source);return source;
  }
  async bind({workspaceId,projectId='',chat}){
    const s=this.store.load(workspaceId);if(s.workspaceType==='restored')throw fail('请在正式工作区配置新的群来源');
    if(projectId&&!s.projects.some(p=>p.id===projectId&&!p.archived))throw fail('所选项目不在当前范围');
    const chatId=caseChatId(chat),signal=AbortSignal.timeout(45000),identity=await this.client.identity({signal});
    const info=await this.client.run(['im','chats','get','--params',JSON.stringify({chat_id:chatId}),'--as','user'],{signal});
    if(typeof info?.name!=='string'||info.chat_id&&info.chat_id!==chatId)throw fail('群身份未通过核对');
    const after=await this.client.identity({signal});if(after.scope!==identity.scope||after.userId!==identity.userId)throw fail('读取期间账号变化，未保存关联');
    this.save(workspaceId,next=>{if(projectId&&!next.projects.some(p=>p.id===projectId&&!p.archived))throw fail('项目已归档');
      const old=this.scopes(next).find(row=>row.chatScope.origin==='manual'&&row.chatScope.projectId===projectId&&row.chatScope.chatId===chatId);
      this.scope(next,['manual',projectId,chatId],{origin:'manual',projectId,chatId,name:info.name,scope:identity.scope,accountId:identity.userId,state:'active',collectFrom:old?.chatScope.collectFrom||this.clock(),confirmedBy:'本人'});});
    return this.status(workspaceId);
  }
  unbind({workspaceId,sourceId,expectedVersion}){
    this.save(workspaceId,s=>{const source=s.sources.find(row=>row.id===sourceId&&row.chatScope?.origin==='manual');if(!source||source.version!==expectedVersion)throw fail('指定群范围已变化');source.chatScope.state='disabled';source.version++;});
    return this.status(workspaceId);
  }
  async discover(workspaceId,identity,signal){
    const initial=this.store.load(workspaceId),auth=await this.metadata.auth({signal}),errors=[],prepared=[];
    const previous=this.control(workspaceId).metadataUserKey;if(previous&&auth.userKey&&previous!==auth.userKey)throw fail('飞书项目登录身份已变化，请核对原采集范围');
    for(const project of initial.projects.filter(p=>!p.archived)){
      signal.throwIfAborted();
      const objects=initial.externalObjects.filter(o=>o.localObjectId===project.id&&o.system==='meegle'&&o.remoteKind==='project'&&o.verificationStatus==='verified'&&!['quarantined','conflict'].includes(o.mappingStatus));
      let value={origin:'project',projectId:project.id,name:project.title+' · 项目群',state:'unknown',chatId:'',collectFrom:this.domain.feedbackCollectFrom,scope:identity.scope,accountId:identity.userId};
      try{
        if(objects.length!==1)throw fail('缺少唯一、已核对的飞书项目关联');
        const group=await this.metadata.group(objects[0],{signal});
        value={...value,...group,state:group.mode==='disabled'?'disabled':'active'};
        if(group.chatId){const info=await this.client.run(['im','chats','get','--params',JSON.stringify({chat_id:group.chatId}),'--as','user'],{signal});if(typeof info?.name!=='string'||info.chat_id&&info.chat_id!==group.chatId)throw fail('群信息身份不一致');value.name=info.name;}
      }catch(error){if(signal.aborted)throw error;errors.push(project.title+'：'+error.message);value={...value,state:'unknown',error:error.message};}
      prepared.push(value);
    }
    const after=await this.metadata.auth({signal});if(auth.userKey&&after.userKey!==auth.userKey)throw fail('读取期间飞书项目账号变化');
    const reader=await this.client.identity({signal});if(reader.scope!==identity.scope||reader.userId!==identity.userId)throw fail('读取期间飞书消息账号变化');
    signal.throwIfAborted();
    this.save(workspaceId,s=>{for(const value of prepared)if(s.projects.some(p=>p.id===value.projectId&&!p.archived))this.scope(s,['project',value.projectId],value);return prepared.length>0;});
    this.store.setSetting('projectChats:'+workspaceId,{...this.control(workspaceId),metadataUserKey:auth.userKey||'',discoveryAt:this.clock(),discoveryErrors:errors});
    return errors;
  }
  poll(workspaceId){
    if(this.closed||!this.control(workspaceId).enabled)return Promise.resolve(this.status(workspaceId));
    if(this.jobs.has(workspaceId))return this.jobs.get(workspaceId).promise;
    const controller=new AbortController(),signal=AbortSignal.any([controller.signal,AbortSignal.timeout(240000)]);
    const promise=this.run(workspaceId,signal).finally(()=>this.jobs.delete(workspaceId));this.jobs.set(workspaceId,{controller,promise});return promise;
  }
  async run(workspaceId,signal){
    const c=this.control(workspaceId),errors=[];let changed=0,groupsRead=0;
    try{
      const identity=await this.client.identity({signal});
      if(c.identity&&(c.identity.scope!==identity.scope||c.identity.userId!==identity.userId))throw fail('飞书消息读取账号已变化，请核对采集范围');
      this.store.setSetting('projectChats:'+workspaceId,{...c,identity:{scope:identity.scope,userId:identity.userId},lastAttemptAt:this.clock()});
      errors.push(...await this.discover(workspaceId,identity,signal));
      const currentState=this.store.load(workspaceId),scopes=this.scopes(currentState).filter(row=>row.chatScope.state==='active'&&row.chatScope.scope===identity.scope&&row.chatScope.accountId===identity.userId&&(!row.chatScope.projectId||currentState.projects.some(p=>p.id===row.chatScope.projectId&&!p.archived)));
      for(const chatId of new Set(scopes.map(row=>row.chatScope.chatId))){
        signal.throwIfAborted();
        try{const result=await this.readGroup(workspaceId,scopes.filter(row=>row.chatScope.chatId===chatId),identity,signal);changed+=result.changed;groupsRead++;errors.push(...result.errors);}
        catch(error){if(signal.aborted)throw error;errors.push(error.message);}
      }
      const fresh=await this.client.identity({signal});if(fresh.scope!==identity.scope||fresh.userId!==identity.userId)throw fail('读取期间飞书身份变化');
    }catch(error){if(!this.closed&&this.control(workspaceId).enabled&&this.control(workspaceId).revision===c.revision)errors.push(signal.aborted?'项目群读取中断或超时，已保存资料保留，覆盖未记为完成。':error.message);}
    const latest=this.control(workspaceId);if(latest.revision!==c.revision||this.closed)return this.status(workspaceId);
    const failed=errors.length>0&&groupsRead===0,failures=failed?latest.failures+1:0;
    this.store.setSetting('projectChats:'+workspaceId,{...latest,failures,enabled:latest.enabled&&failures<3,phase:errors.length?'partial':'complete',lastError:[...new Set(errors)].join('；'),groupsRead,changed,lastCompletedAt:this.clock(),lastSucceededAt:errors.length||signal.aborted?latest.lastSucceededAt||'':this.clock(),nextReadAt:latest.enabled&&failures<3?new Date(Date.parse(this.clock())+300000).toISOString():''});
    return this.status(workspaceId);
  }
  async readGroup(workspaceId,scopes,identity,signal){
    const chatId=scopes[0].chatScope.chatId,collectFrom=scopes.map(s=>s.chatScope.collectFrom).sort()[0],scopeBasis=hash(scopes.map(s=>[s.id,s.chatScope.collectFrom,s.chatScope.scope,s.chatScope.accountId]).sort()),checkpoint=this.store.getSetting('projectChatRead:'+workspaceId+':'+chatId)||{},wall=this.clock();
    const windowSeconds=checkpoint.scopeBasis===scopeBasis?checkpoint.windowSeconds||86400:86400,start=new Date(Math.max(Date.parse(collectFrom),checkpoint.scopeBasis===scopeBasis?Date.parse(checkpoint.through||collectFrom)-Math.min(900,windowSeconds/4)*1000:0)).toISOString(),end=new Date(Math.min(Date.parse(wall),Date.parse(start)+windowSeconds*1000)).toISOString(),messages=[],errors=[],seen=new Set();let token='',complete=false;
    for(let page=0;page<40;page++){
      const data=await this.client.run(['im','+chat-messages-list','--chat-id',chatId,'--start',start,'--end',end,'--order','desc','--page-size','50','--no-reactions',...(token?['--page-token',token]:[]),'--as','user'],{signal});
      if(!Array.isArray(data?.messages)||typeof data.has_more!=='boolean')throw fail('群消息分页未完整返回');
      const verified=await verifiedGroupMessages(this.client,data.messages,chatId,{signal});
      messages.push(...verified.filter(message=>Number(message.create_time)>=Date.parse(start)&&Number(message.create_time)<=Date.parse(end)));
      if(!data.has_more){complete=true;break;}if(!data.page_token||seen.has(data.page_token))throw fail('群消息分页游标异常');seen.add(data.page_token);token=data.page_token;
    }
    if(!complete)errors.push('群消息达到分页上限，保留读取缺口');
    const threads=await readCaseThreads({client:this.client,domain:this.domain,binding:{chatId},messages,end,signal});errors.push(...threads.errors);
    const all=[...new Map([...messages,...threads.messages.map(raw=>normalizeGroupMessage(raw))].map(m=>[m.message_id,m])).values()];
    const after=await this.client.identity({signal});if(after.scope!==identity.scope||after.userId!==identity.userId)throw fail('群消息读取期间账号变化');
    signal.throwIfAborted();let changed=0;const changedCases=new Set();
    this.save(workspaceId,s=>{
      const activeScopes=scopes.filter(scope=>s.sources.some(row=>row.id===scope.id&&row.chatScope.state==='active'&&row.chatScope.chatId===chatId&&(!row.chatScope.projectId||s.projects.some(p=>p.id===row.chatScope.projectId&&!p.archived))));
      if(!activeScopes.length)throw fail('群范围已变化，本轮消息未入账');
      for(const raw of all){
        const at=this.domain.feedbackTime(raw.create_time);if(!at||Date.parse(at)>Date.parse(end))continue;
        const allowed=activeScopes.filter(scope=>Date.parse(at)>=Date.parse(scope.chatScope.collectFrom));if(!allowed.length)continue;
        const shared=s.sources.find(row=>{const m=row.personalMessage||row.caseChat;return m?.scope===identity.scope&&m.accountId===identity.userId&&m.messageId===raw.message_id;});
        const id=shared?.id||'case-chat-'+hash([identity.scope,identity.userId,chatId,raw.message_id]).slice(0,36),old=s.sources.find(source=>source.id===id),rawHash=old?.caseChat&&groupMessageFingerprint(old.caseChat.raw)===groupMessageFingerprint(raw)?old.caseChat.rawHash:groupMessageFingerprint(raw),scopeIds=[...new Set([...(old?.projectChat?.scopeIds||[]),...allowed.map(scope=>scope.id)])];
        if(old?.caseChat?.rawHash===rawHash&&JSON.stringify(old.projectChat?.scopeIds)===JSON.stringify(scopeIds))continue;
        const body=raw.deleted?'消息已撤回，历史版本保留。':typeof raw.content==='string'?raw.content:raw.body?.content||'';
        const projectIds=[...new Set([...(old?.projectIds||[]),...allowed.map(scope=>scope.chatScope.projectId).filter(Boolean)])];
        const value={...(old||{}),id,title:allowed[0].chatScope.name+' · '+at,projectIds,caseIds:old?.caseIds||[],objectIds:[...new Set([...(old?.objectIds||[]),...projectIds])],sourceIds:[],type:'项目与指定工作群消息',author:raw.sender?.name||(typeof raw.sender?.id==='string'?raw.sender.id:'作者未返回'),excerpt:body,occurredAt:at,collectedAt:end,version:(old?.version||0)+1,confirmed:false,projectChat:{schemaVersion:1,scopeIds},caseChat:{schemaVersion:1,chatId,messageId:raw.message_id,scope:identity.scope,accountId:identity.userId,raw,rawHash,displayTime:at,rangeVerified:true,collectFrom:start,history:old?[...(old.caseChat?.history||[]),{raw:old.caseChat?.raw,collectedAt:old.collectedAt}]:[]}};
        if(old)Object.assign(old,value);else s.sources.push(value);changed++;
        for(const caseId of value.caseIds){const item=s.cases.find(row=>row.id===caseId&&!row.archived&&row.status!=='已关闭');if(item){item.caseAnalysis={status:'pending'};item.version++;changedCases.add(caseId);}}
      }
      return changed>0;
    });
    for(const caseId of changedCases)void this.onCaseChanged({workspaceId,caseId});
    const messagesComplete=complete&&!errors.length;
    const state=this.store.load(workspaceId);
    const sources=state.sources.filter(source=>source.projectChat?.scopeIds.some(id=>scopes.some(scope=>scope.id===id))&&source.caseChat?.chatId===chatId&&!source.caseChat.raw.deleted);
    let files=0;
    for(const source of sources){for(const file of this.domain.chatFiles(source.caseChat.raw)){
      if(files>=10){errors.push('本轮群文件已达到10份，剩余文件待续读');break;}
      const old=state.sources.find(row=>row.caseFile?.parentSourceId===source.id&&row.caseFile.fileKey===file.key&&row.caseFile.parentHash===source.caseChat.rawHash);
      if(old&&!['failed','unread'].includes(old.readStatus))continue;
      if(old?.caseFile?.failures>=3){errors.push(file.name+'：连续读取失败，原件已保留，可在资料中重新投递整理');continue;}
      files++;
      try{await this.readGroupFile({workspaceId,sourceId:source.id,fileKey:file.key},signal);}catch(error){errors.push(file.name+'：'+error.message);}
    }}
    this.store.setSetting('projectChatRead:'+workspaceId+':'+chatId,{at:wall,scopeBasis,through:messagesComplete?end:checkpoint.scopeBasis===scopeBasis?checkpoint.through||collectFrom:collectFrom,windowSeconds:messagesComplete?Math.min(86400,windowSeconds*2):Math.max(60,Math.floor(windowSeconds/2)),complete:messagesComplete&&end===wall&&!errors.length,count:all.length,errors});
    return {changed,errors:[...new Set(errors)]};
  }
  async readGroupFile({workspaceId,sourceId,fileKey},signal){
    const state=this.store.load(workspaceId),source=state.sources.find(row=>row.id===sourceId&&!row.archived);
    if(!source?.caseChat||!source.projectChat||!this.domain.caseEvidenceAvailable(state,source))throw fail('群文件原消息已变化');
    const file=this.domain.chatFiles(source.caseChat.raw).find(row=>row.key===fileKey);if(!file)throw fail('文件不在当前消息引用内');
    const beforeIdentity=await this.client.identity({signal});if(beforeIdentity.scope!==source.caseChat.scope||beforeIdentity.userId!==source.caseChat.accountId)throw fail('文件读取账号与原消息来源不一致');
    const [remote]=await verifiedGroupMessages(this.client,[source.caseChat.raw],source.caseChat.chatId,{signal});
    if(groupMessageFingerprint(remote)!==groupMessageFingerprint(source.caseChat.raw)){
      const identity=await this.client.identity({signal});if(identity.scope!==beforeIdentity.scope||identity.userId!==beforeIdentity.userId)throw fail('文件核对期间账号变化');
      signal.throwIfAborted();
      this.save(workspaceId,s=>{const parent=s.sources.find(row=>row.id===sourceId);if(parent?.caseChat?.rawHash!==source.caseChat.rawHash)throw fail('群消息依据已变化');parent.caseChat.history.push({raw:parent.caseChat.raw,collectedAt:parent.collectedAt});parent.caseChat.raw=remote;parent.caseChat.rawHash=groupMessageFingerprint(remote);parent.excerpt=remote.deleted?'消息已撤回，历史版本保留。':remote.content;parent.version++;parent.collectedAt=this.clock();});
      throw fail('文件所据原消息已变化或撤回，已保存新消息，请重新核对');
    }
    const folder=await mkdtemp(path.join(this.store.dir,'project-chat-file-'));
    try{
      const target=path.join(folder,'original'),download=await this.client.run(['im','+messages-resources-download','--message-id',source.caseChat.messageId,'--file-key',file.key,'--type','file','--output',target,'--as','user'],{signal});
      if(path.resolve(download?.saved_path||'')!==target)throw fail('群文件下载位置不一致');
      const size=(await stat(target)).size;if(size>20*1024*1024)throw fail('文件超过20MB，原消息保留，需另行处理');
      const bytes=await readFile(target);
      const id='case-file-'+hash([source.id,fileKey]).slice(0,36),sha256=createHash('sha256').update(bytes).digest('hex'),at=this.clock();
      const identity=await this.client.identity({signal});if(identity.scope!==source.caseChat.scope||identity.userId!==source.caseChat.accountId)throw fail('文件读取账号与原消息来源不一致');
      const latest=this.store.load(workspaceId).sources.find(row=>row.id===sourceId);if(signal.aborted||latest?.caseChat?.rawHash!==source.caseChat.rawHash)throw fail('下载期间原消息已有变化');
      const previous=this.store.load(workspaceId).sources.find(row=>row.id===id);
      const attachment=previous?.caseFile?.sha256===sha256&&previous.attachments?.[0]||this.store.attach(workspaceId,{name:file.name,mime:'application/octet-stream',base64:bytes.toString('base64')});
      this.save(workspaceId,s=>{const parent=s.sources.find(row=>row.id===sourceId);if(signal.aborted||parent?.caseChat?.rawHash!==source.caseChat.rawHash||!parent.projectChat?.scopeIds.some(scopeId=>s.sources.some(scope=>scope.id===scopeId&&scope.chatScope?.state==='active')))throw fail('群消息依据或采集范围已变化');const old=s.sources.find(row=>row.id===id);
        const value={...(old||{}),id,title:file.name,type:'群文件原件',projectIds:source.projectIds,caseIds:source.caseIds||[],objectIds:source.objectIds,sourceIds:[source.id],version:(old?.version||0)+1,confirmed:false,excerpt:old?.excerpt||'',readStatus:'unread',occurredAt:source.occurredAt,collectedAt:at,attachments:[attachment],projectChat:source.projectChat,caseFile:{schemaVersion:1,parentSourceId:source.id,parentHash:source.caseChat.rawHash,fileKey,name:file.name,sha256,textSha256:'',format:path.extname(file.name),limitations:'原件已保存，正文尚未读取',failures:old?.caseFile?.parentHash===source.caseChat.rawHash?old.caseFile.failures||0:0,history:old?[...(old.caseFile?.history||[]),{version:old.version,excerpt:old.excerpt,attachments:old.attachments,readAt:old.collectedAt}]:[]}};
        if(old)Object.assign(old,value);else s.sources.push(value);});
      let parsed;
      try{parsed=await this.readFile({name:file.name,bytes},{signal});}catch(error){
        this.save(workspaceId,s=>{const row=s.sources.find(row=>row.id===id),parent=s.sources.find(row=>row.id===sourceId);if(row?.caseFile?.parentHash!==source.caseChat.rawHash||parent?.caseChat?.rawHash!==source.caseChat.rawHash)return false;row.readStatus='failed';row.caseFile.failures++;row.caseFile.limitations=error.message;row.version++;});
        throw error;
      }
      signal.throwIfAborted();
      this.save(workspaceId,s=>{const parent=s.sources.find(row=>row.id===sourceId);if(signal.aborted||parent?.caseChat?.rawHash!==source.caseChat.rawHash||!parent.projectChat?.scopeIds.some(scopeId=>s.sources.some(scope=>scope.id===scopeId&&scope.chatScope?.state==='active')))throw fail('群消息依据或采集范围已变化');const old=s.sources.find(row=>row.id===id);
        const value={...(old||{}),id,title:file.name,type:'群文件正文',projectIds:source.projectIds,caseIds:source.caseIds||[],objectIds:source.objectIds,sourceIds:[source.id],version:(old?.version||0)+1,confirmed:false,excerpt:parsed.text,readStatus:parsed.complete?'ready':'partial',occurredAt:source.occurredAt,collectedAt:at,attachments:[attachment],projectChat:source.projectChat,caseFile:{schemaVersion:1,parentSourceId:source.id,parentHash:source.caseChat.rawHash,fileKey,name:file.name,sha256,textSha256:hash(parsed.text),format:path.extname(file.name),limitations:(parsed.limitations||[]).join('；'),failures:0,readAt:at,history:old?.caseFile?.history||[]}};
        if(old)Object.assign(old,value);else s.sources.push(value);});
    }finally{await rm(folder,{recursive:true,force:true});}
  }
  start(){this.timer=setInterval(()=>{for(const w of this.store.list().filter(w=>w.type!=='restored')){const c=this.control(w.id);if(c.enabled&&!this.jobs.has(w.id)&&(!c.nextReadAt||Date.parse(c.nextReadAt)<=Date.parse(this.clock())))void this.poll(w.id);}},10000);this.timer.unref();}
  async close(){this.closed=true;clearInterval(this.timer);for(const job of this.jobs.values())job.controller.abort();await Promise.allSettled([...this.jobs.values()].map(job=>job.promise));}
}
