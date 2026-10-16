import {resolveMeegleCli} from './cli-runtime.mjs';
import {createHash,randomUUID} from 'node:crypto';
import {MeegleSyncAdapter} from './feishu-sync-cli.mjs';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const fail=(message,status=409)=>Object.assign(Error(message),{status});
const root=value=>value?.data??value;
const text=value=>typeof value==='string'?value:'';
const idOf=row=>String(row?.comment_id??row?.id??'');
const userKeys=value=>Array.isArray(value)?value.flatMap(userKeys):value&&typeof value==='object'?[value.user_key??value.userKey??value.key??value.id].filter(v=>v!==undefined).map(String):typeof value==='string'&&value.trim()?[value]:[];
const stableTarget=object=>({id:object.id,remoteId:String(object.remoteId),spaceKey:object.spaceKey,host:object.host,remoteKind:object.remoteKind,localObjectId:object.localObjectId,workItemType:object.workItemType||object.raw?.workItemType});
const approved=run=>hash([run.workspaceId,run.deliverableId,run.target,run.actor,run.owner,run.body,run.content,run.localBasis,run.remoteBasis,run.createdAt]);
const bodyOf=row=>text(row.content)||text(row.text)||text(row.body)||text(row.markdown)||text(row.content?.text);
const authorOf=row=>String(row.author?.user_key??row.author?.key??row.author?.id??row.creator?.user_key??row.creator?.key??row.creator?.id??row.created_by?.user_key??row.created_by?.key??row.user_key??row.author_key??row.operator?.user_key??(typeof row.author==='string'?row.author:typeof row.creator==='string'?row.creator:typeof row.created_by==='string'?row.created_by:''));
const plain=value=>String(value).replace(/<!--[^]*?-->/g,'').replace(/\r\n/g,'\n').trim();

export class DeliverableComments {
  constructor({store,adapter=new MeegleSyncAdapter({cli:resolveMeegleCli(),profile:process.env.PM_MEEGLE_PROFILE,host:'project.feishu.cn'}),testMode=false,allowTestWrites=false,clock=()=>Date.now()}={}){
    Object.assign(this,{store,adapter,testMode,allowTestWrites,clock});this.jobs=new Map();this.fingerprints=new Map();this.controllers=new Set();this.closed=false;
  }
  stamp(){return new Date(this.clock()).toISOString();}
  target(workspaceId,deliverableId){
    const state=this.store.load(workspaceId),record=state.deliverables.find(row=>row.id===deliverableId&&!row.archived);
    if(!record)throw fail('请先定位具体交付物，不能把节点直接当成评论目标',404);
    const objects=state.externalObjects.filter(row=>!row.archived&&row.localObjectId===record.id&&row.system==='meegle'&&row.remoteKind==='deliverable'&&row.verificationStatus==='verified'&&row.mappingStatus==='mapped');
    if(objects.length!==1)throw fail('交付物的飞书对象尚未唯一核对，不能猜测评论位置');
    const object=objects[0];if(!object.spaceKey||!/^\d+$/.test(String(object.remoteId)))throw fail('交付物缺少有效的空间或远端ID');
    return {state,record,object,localBasis:hash([record,stableTarget(object)])};
  }
  async context(input,signal){
    const before=this.target(input.workspaceId,input.deliverableId),actor=await this.adapter.auth({signal}),read=await this.adapter.readObject(before.object,{signal});
    if(read.complete!==true||String(read.remoteId)!==String(before.object.remoteId)||read.spaceKey!==before.object.spaceKey)throw fail('没有完整读到同一交付物，不能确认负责人或提交情况');
    const fields=read.fieldMetadata||[];
    // Meegle's system "owner" is the creator in this workspace, not the delivery owner.
    const ownerFields=['交付负责人','责任人','负责人'].map(name=>fields.filter(f=>f.name===name)).find(matches=>matches.length)||[];
    if(ownerFields.length!==1||!Object.hasOwn(read.fields,ownerFields[0].key))throw fail('本次读取未明确返回唯一交付负责人，请先核对负责人字段');
    const keys=[...new Set(userKeys(read.fields[ownerFields[0].key]))];if(keys.length!==1)throw fail('交付物负责人为空或不唯一，先核对后再评论');
    const users=await this.adapter.lookupUsers(before.object,keys,{signal});
    const matches=users.filter(user=>String(user.user_key)===keys[0]||String(user.lark_user_id)===keys[0]||user.email===keys[0]);
    if(matches.length!==1)throw fail('负责人身份没有唯一匹配，不能用同名人员代替');
    const user=matches[0],larkId=String(user.lark_user_id||''),name=user.name_cn||user.name||user.name_en||user.username;
    if(!/^\d+$/.test(larkId)||!name||['inactive','disabled','resigned','离职'].includes(String(user.status)))throw fail('负责人缺少有效的飞书提及身份或已离职');
    if(/[\r\n<>]/.test(name))throw fail('负责人名称格式需要核对');
    const owner={userKey:String(user.user_key),larkUserId:larkId,name,email:user.email||''},identity={host:actor.host,userKey:actor.userKey,name:actor.identity?.name_cn||actor.identity?.name||actor.identity?.username||actor.userKey,profile:actor.profile||''};
    const current=this.target(input.workspaceId,input.deliverableId);if(current.localBasis!==before.localBasis)throw fail('读取期间交付物发生变化，请重新准备');
    return {deliverableId:before.record.id,title:before.record.title,target:stableTarget(before.object),actor:identity,owner,localBasis:before.localBasis,remoteBasis:hash([read.fields,owner,identity]),contextHash:hash([before.localBasis,read.fields,owner,identity])};
  }
  job(key,fn,fingerprint=''){
    if(this.closed)throw fail('服务正在停止');if(this.jobs.has(key)){if(this.fingerprints.get(key)!==fingerprint)throw fail('相同请求正在处理，不能更换内容');return this.jobs.get(key);}
    const controller=new AbortController();this.controllers.add(controller);
    this.fingerprints.set(key,fingerprint);const task=fn(controller.signal).finally(()=>{this.jobs.delete(key);this.fingerprints.delete(key);this.controllers.delete(controller);});this.jobs.set(key,task);return task;
  }
  inspect(input){return this.job(input.workspaceId+':inspect:'+input.deliverableId,signal=>this.context(input,signal));}
  prepare(input){return this.job(input.workspaceId+':prepare:'+input.requestId,async signal=>{
    if(typeof input.body!=='string'||!input.body.trim()||input.body.length>4000||/<!--\s*mention\s*:|AT_USER_BLOCK/i.test(input.body))throw fail('请填写普通评论正文；@身份由已核对的负责人生成',422);
    if(typeof input.requestId!=='string'||!/^[\w-]{10,120}$/.test(input.requestId))throw fail('评论缺少稳定请求标识',422);
    const state=this.store.load(input.workspaceId),previous=state.sources.find(s=>s.commentDispatch?.requestId===input.requestId);
    if(previous){if(previous.commentDispatch.body!==input.body.trim()||previous.commentDispatch.deliverableId!==input.deliverableId)throw fail('同一请求不能更换评论内容或交付物');return {state,source:previous};}
    if(state.sources.some(s=>s.commentDispatch?.deliverableId===input.deliverableId&&['sending','sent','needs_reconcile'].includes(s.commentDispatch.status)))throw fail('该交付物仍有评论结果待核对，请先回读原请求');
    const context=await this.context(input,signal);if(input.contextHash!==context.contextHash)throw fail('交付物、负责人或材料已变化，请重新核对评论预览');
    const content=`@${context.owner.name}<!-- mention:${JSON.stringify({id:'lark_user_id_'+context.owner.larkUserId,cn_name:context.owner.name,blockType:'AT_USER_BLOCK'})} -->\n${input.body.trim()}`;
    const run={schemaVersion:1,workspaceId:input.workspaceId,...context,requestId:input.requestId,body:input.body.trim(),content,status:'pending_review',createdAt:this.stamp(),error:'',commentId:'',beforeIds:[],approvalHash:''};run.approvalHash=approved(run);
    const source={id:'comment-'+randomUUID(),title:'交付物评论 · '+context.title,projectIds:this.target(input.workspaceId,input.deliverableId).record.projectIds,sourceIds:[],objectIds:[input.deliverableId],type:'交付物评论执行记录',excerpt:run.body,collectedAt:this.stamp(),version:1,commentDispatch:run};
    this.store.transaction(()=>{const before=this.store.load(input.workspaceId),next=structuredClone(before);if(this.target(input.workspaceId,input.deliverableId).localBasis!==run.localBasis)throw fail('评论目标已变化');next.sources.push(source);next.revision++;this.store.save(next,before.revision);});
    return {state:this.store.load(input.workspaceId),source};
  },hash(input));}
  patch(workspaceId,sourceId,fn){return this.store.transaction(()=>{
    const before=this.store.load(workspaceId),next=structuredClone(before),source=next.sources.find(s=>s.id===sourceId&&s.commentDispatch);
    if(!source)throw fail('评论记录不存在',404);fn(source.commentDispatch);source.version++;source.updatedAt=this.stamp();next.revision++;
    next.audit.push({id:'comment-audit-'+randomUUID(),time:this.stamp(),operation:'deliverable.comment.'+source.commentDispatch.status,objectId:source.commentDispatch.deliverableId,actor:source.commentDispatch.actor.name,before:null,after:{sourceId,commentId:source.commentDispatch.commentId,status:source.commentDispatch.status},revision:next.revision});
    this.store.save(next,before.revision);return {state:this.store.load(workspaceId),source};
  });}
  async verify(run,signal){
    const identity=await this.adapter.auth({signal});if(identity.host!==run.actor.host||identity.userKey!==run.actor.userKey)throw fail('评论回读账号发生变化');
    const value=await this.adapter.readComments(run.target,{signal});if(value.complete!==true)throw fail('评论尚未完整回读');
    const matches=value.comments.filter(row=>{
      const id=idOf(row);if(!id||row.deleted||row.is_deleted||run.beforeIds.includes(id)||run.commentId&&id!==run.commentId)return false;
      const sameBody=plain(bodyOf(row))===plain(run.content)||plain(bodyOf(row))===run.body;
      const markers=[...bodyOf(row).matchAll(/<!--\s*mention:(\{[^]*?\})\s*-->/g)].flatMap(match=>{try{return [JSON.parse(match[1])];}catch{return [];}});
      const mentioned=markers.some(m=>m.blockType==='AT_USER_BLOCK'&&m.id==='lark_user_id_'+run.owner.larkUserId)||Array.isArray(row.mentions)&&row.mentions.some(user=>String(user.lark_user_id??user.id).replace(/^lark_user_id_/,'')===run.owner.larkUserId);
      return sameBody&&mentioned&&authorOf(row)===run.actor.userKey;
    });
    if(matches.length!==1)throw fail('未唯一回读到同一作者、正文及真实@的评论；保留当前结果，不自动重发');
    return {commentId:idOf(matches[0]),readAt:this.stamp(),author:run.actor.userKey,owner:run.owner.userKey,contentMatched:true,mentionMatched:true};
  }
  send(input){return this.job(input.workspaceId+':send:'+input.sourceId,async signal=>{
    const state=this.store.load(input.workspaceId),source=state.sources.find(s=>s.id===input.sourceId&&!s.archived),run=source?.commentDispatch;
    if(!run||run.workspaceId!==input.workspaceId||!input.approvalHash||run.approvalHash!==input.approvalHash||approved(run)!==run.approvalHash)throw fail('评论审核内容已变化，请重新准备');
    if(run.status==='readback_verified')return {state,source};
    if(state.workspaceType!=='official'&&!(this.testMode&&this.allowTestWrites))throw fail('只有正式工作区或明确的模拟适配器可发布评论',403);
    if(run.status!=='pending_review')throw fail('评论可能已执行，请先核对结果，不能重复发布');
    if(this.clock()-Date.parse(run.createdAt)>30*60000)throw fail('评论预览已超过30分钟，请重新核对');
    if(state.sources.some(s=>s.id!==source.id&&s.commentDispatch?.deliverableId===run.deliverableId&&['sending','sent','needs_reconcile'].includes(s.commentDispatch.status)))throw fail('该交付物还有评论结果待核对，请先续办原请求');
    const current=await this.context({workspaceId:input.workspaceId,deliverableId:run.deliverableId},signal);
    if(current.contextHash!==run.contextHash)throw fail('交付物、负责人或材料发生变化，原评论预览失效');
    const comments=await this.adapter.readComments(run.target,{signal});if(comments.complete!==true)throw fail('无法读取评论基线，尚未发布');
    const beforeIds=comments.comments.map(idOf).filter(Boolean);
    this.patch(input.workspaceId,input.sourceId,r=>{
      const latest=this.target(input.workspaceId,run.deliverableId);
      if(latest.localBasis!==run.localBasis||latest.state.sources.some(s=>s.id!==source.id&&s.commentDispatch?.deliverableId===run.deliverableId&&['sending','sent','needs_reconcile'].includes(s.commentDispatch.status)))throw fail('交付物已变化或另一条评论正在执行，请重新核对');
      r.status='sending';r.beforeIds=beforeIds;r.startedAt=this.stamp();
    });
    let accepted=false;
    try{
      const result=root(await this.adapter.addComment(run.target,run.content,{signal})),commentId=String(result?.comment_id??result?.id??result?.comment?.id??'');
      accepted=true;
      this.patch(input.workspaceId,input.sourceId,r=>{r.status='sent';r.commentId=commentId;});
      const currentRun=this.store.load(input.workspaceId).sources.find(s=>s.id===input.sourceId).commentDispatch;
      const readback=await this.verify(currentRun,signal);
      return this.patch(input.workspaceId,input.sourceId,r=>{r.status='readback_verified';r.commentId=readback.commentId;r.readback=readback;r.error='';r.finishedAt=this.stamp();});
    }catch(error){
      // A readback error after the write must never make the same comment retryable.
      const rejected=!accepted&&error.uncertain===false&&['AUTH_REQUIRED','PERMISSION_DENIED','NOT_FOUND','RATE_LIMITED','CLI_NOT_FOUND','INVALID_COMMENT','HOST_MISMATCH','IDENTITY_MISMATCH'].includes(error.code);
      return this.patch(input.workspaceId,input.sourceId,r=>{r.status=rejected?'failed':'needs_reconcile';r.error=error.message;if(rejected){r.approvalHash='';r.finishedAt=this.stamp();}});
    }
  });}
  reconcile(input){return this.job(input.workspaceId+':reconcile:'+input.sourceId,async signal=>{
    const state=this.store.load(input.workspaceId),run=state.sources.find(s=>s.id===input.sourceId)?.commentDispatch;
    if(!run||run.workspaceId!==input.workspaceId||!['sending','sent','needs_reconcile','readback_verified'].includes(run.status))throw fail('没有可回读的评论执行记录');
    if(this.jobs.has(input.workspaceId+':send:'+input.sourceId))throw fail('评论正在执行，请等待');
    const readback=await this.verify(run,signal);return this.patch(input.workspaceId,input.sourceId,r=>{r.status='readback_verified';r.commentId=readback.commentId;r.readback=readback;r.error='';});
  });}
  async close(){this.closed=true;for(const c of this.controllers)c.abort();await Promise.allSettled(this.jobs.values());}
}
