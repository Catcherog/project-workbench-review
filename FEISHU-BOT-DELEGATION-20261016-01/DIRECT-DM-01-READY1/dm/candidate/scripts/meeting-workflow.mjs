import {randomUUID} from 'node:crypto';
import {FeishuMeetingClient} from './feishu-meeting-client.mjs';
import {meetingHash as hash, meetingError as fail, sourceBasis, fileHash} from './meeting-materials.mjs';

const copy = value => structuredClone(value);
const unique = values => [...new Set(values)];
const activeAttendees = event => (event.attendees || []).filter(a => !a.is_organizer && a.rsvp_status !== 'removed');
const attachmentTokens = event => (event.attachments || []).filter(a => !a.is_deleted).map(a => a.file_token).sort();
export const meetingEventFingerprint = e => hash({id:e.event_id,title:e.summary,description:e.description_rich,start:e.start_time,end:e.end_time,status:e.status,attendeeAbility:e.attendee_ability,attendees:activeAttendees(e).map(a=>[a.type,a.user_id,a.attendee_id]).sort(),attachments:(e.attachments||[]).map(a=>[a.file_token,a.name,a.file_size]).sort(),vchat:e.vchat,visibility:e.visibility});
const intentFingerprint = w => hash([w.draftVersion,w.intent,w.materials]);
const sameAccount = (a,b) => a?.scope === b?.scope && a?.userId === b?.userId;
const time = value => typeof value === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const sourceOf = (s,id) => s.sources.find(r => r.id === id && r.meetingWorkflow?.schemaVersion === 1);
const minutesFingerprint = m => hash([m.status,m.meetingId,m.documents?.map(d=>[d.token,d.revision,d.sha256,d.stale])]);
const statusFromSteps = steps => Object.values(steps).some(s=>['unknown','running'].includes(s.status)) ? 'unknown' : 'partial';

/** Integrates through LocalStore and V2 ChangeGroup, never a separate business database. */
export class MeetingWorkflow {
  constructor({store,domain,materials,client=new FeishuMeetingClient(),deliverables,mode='disabled',authorizeExternal,clock=()=>new Date().toISOString()}) {
    Object.assign(this,{store,domain,materials,client,deliverables,mode,authorizeExternal,clock});
    this.jobs=new Map();this.closed=false;
  }
  record(workspaceId,id,allowArchived=false) {
    const state=this.store.load(workspaceId),source=sourceOf(state,id);
    if(!source || source.archived&&!allowArchived)throw fail('会议准备记录不可用',404);
    return {state,source,w:source.meetingWorkflow};
  }
  result(workspaceId,id) {const {state,source}=this.record(workspaceId,id,true);return {state,source};}
  mutate(workspaceId,id,operation,fn) {
    return this.store.transaction(()=>{
      const before=this.store.load(workspaceId),next=copy(before),source=sourceOf(next,id);
      if(!source)throw fail('会议准备记录不存在',404);
      const detail=fn(source.meetingWorkflow,next,source);source.version++;source.updatedAt=this.clock();next.revision++;
      source.excerpt='会议：'+source.meetingWorkflow.intent.title+'\n当前记录：'+(this.domain.meetingWorkflowLabels?.[source.meetingWorkflow.status]||source.meetingWorkflow.status);
      next.audit.push({id:'meeting-workflow-'+randomUUID(),time:this.clock(),operation,objectId:id,actor:'本人',before:null,after:detail||null,revision:next.revision});
      const errors=this.domain.validateState(next);if(errors.length)throw fail(errors.map(e=>e.message).join('；'));
      this.store.save(next,before.revision);return this.result(workspaceId,id);
    });
  }
  job(workspaceId,id,action,fn) {
    const key=workspaceId+':'+id,existing=this.jobs.get(key);
    if(this.closed)throw fail('会议服务已停止',503);
    if(existing){if(existing.action===action)return existing.promise;throw fail('该会议正在处理，请等待当前步骤完成',409);}
    const controller=new AbortController();
    const promise=Promise.resolve().then(()=>fn(AbortSignal.any([controller.signal,AbortSignal.timeout(120000)]))).finally(()=>this.jobs.delete(key));
    this.jobs.set(key,{action,promise,controller});return promise;
  }
  assertEditable(workspaceId,id,w,expectedVersion) {
    if(w.draftVersion!==expectedVersion)throw fail('草稿版本已变化，请重新打开',409);
    if(this.jobs.has(workspaceId+':'+id)||['executing','unknown'].includes(w.status)||Object.values(w.execution?.steps||{}).some(s=>['unknown','running'].includes(s.status)))throw fail('请先核对当前执行，原输入和外部结果已保留',409);
  }
  normalize(input={}) {
    for(const key of ['referenceNodeIds','attendeeIds','sourceIds'])if(input[key]!==undefined&&(!Array.isArray(input[key])||input[key].length>100||input[key].some(id=>typeof id!=='string'||!id||id.length>180)))throw fail('会议列表字段无效：'+key);
    return {projectId:String(input.projectId||''),caseId:String(input.caseId||''),mainNodeId:String(input.mainNodeId||''),referenceNodeIds:unique(input.referenceNodeIds||[]),title:String(input.title||'未命名会议').trim(),calendarId:String(input.calendarId||''),start:String(input.start||''),end:String(input.end||''),attendeeIds:unique(input.attendeeIds||[]),sourceIds:unique(input.sourceIds||[]),notify:input.notify===true,...(input.contextRef?{contextRef:{kind:String(input.contextRef.kind||''),id:String(input.contextRef.id||'')}}:{})};
  }
  create({workspaceId,requestId,intent,initiatedBy}) {
    if(initiatedBy!=='user')throw fail('会议须由本人主动发起',403);
    if(typeof requestId!=='string'||!requestId||requestId.length>180)throw fail('缺少稳定发起请求ID');
    const normalized=this.normalize(intent),id='meeting-workflow-'+hash([workspaceId,requestId]).slice(0,32);
    const initial=this.store.load(workspaceId),existing=sourceOf(initial,id);
    if(existing){if(existing.meetingWorkflow.initialHash!==hash(normalized))throw fail('同一发起请求不能用于不同内容',409);return this.result(workspaceId,id);}
    this.store.transaction(()=>{
      const before=this.store.load(workspaceId),s=copy(before);if(sourceOf(s,id))throw fail('会议发起请求正在处理',409);
      if(normalized.projectId&&!s.projects.some(p=>p.id===normalized.projectId&&!p.archived))throw fail('项目不可用');
      if(normalized.caseId&&!s.cases.some(p=>p.id===normalized.caseId&&!p.archived))throw fail('专项不可用');
      if(normalized.contextRef&&this.domain.kindOf(s,normalized.contextRef.id)!==normalized.contextRef.kind)throw fail('会议发起事项不在当前工作区',409);
      s.sources.push({id,title:normalized.title,projectIds:normalized.projectId?[normalized.projectId]:[],caseIds:normalized.caseId?[normalized.caseId]:[],objectIds:normalized.contextRef?[normalized.contextRef.id]:[],sourceIds:[],type:'会议准备',excerpt:'本人主动发起，尚未创建飞书日程。',version:1,confirmed:false,collectedAt:this.clock(),meetingWorkflow:{schemaVersion:1,draftVersion:1,initialHash:hash(normalized),intent:normalized,identity:null,status:'draft',assets:{},history:[]}});
      s.revision++;s.audit.push({id:'meeting-start-'+randomUUID(),time:this.clock(),operation:'meeting.workflow.start',objectId:id,actor:'本人',before:null,after:{externalWrite:false},revision:s.revision});
      const errors=this.domain.validateState(s);if(errors.length)throw fail(errors.map(e=>e.message).join('；'));this.store.save(s,before.revision);
    });return this.result(workspaceId,id);
  }
  save({workspaceId,sourceId,expectedVersion,intent}) {
    const {w}=this.record(workspaceId,sourceId);this.assertEditable(workspaceId,sourceId,w,expectedVersion);
    return this.mutate(workspaceId,sourceId,'meeting.workflow.edit',(next,s,row)=>{
      this.invalidate(next,s);next.intent=this.normalize(intent);next.draftVersion++;next.materials=null;next.status='draft';row.title=next.intent.title;
      row.projectIds=next.intent.projectId?[next.intent.projectId]:[];row.caseIds=next.intent.caseId?[next.intent.caseId]:[];row.objectIds=next.intent.contextRef?[next.intent.contextRef.id]:[];return {draftVersion:next.draftVersion};
    });
  }
  invalidate(w,s) {
    if(w.preview){w.history.push({preview:copy(w.preview),execution:copy(w.execution||null),status:w.status,at:this.clock()});const group=s.changeGroups.find(g=>g.id===w.preview.groupId);if(group&&['pending','partial','conflict'].includes(group.status))group.status='withdrawn';}
    w.preview=null;w.execution=null;w.approvedFingerprint='';w.error='';
  }
  prepareMaterials({workspaceId,sourceId,expectedVersion}) {
    const {w}=this.record(workspaceId,sourceId);this.assertEditable(workspaceId,sourceId,w,expectedVersion);
    return this.job(workspaceId,sourceId,'materials',async signal=>{
      const {state,w:initial}=this.record(workspaceId,sourceId),basis=intentFingerprint(initial);
      const materials=await this.materials.prepare({state,intent:initial.intent,signal});
      return this.mutate(workspaceId,sourceId,'meeting.materials.prepare',(current,s,row)=>{
        if(intentFingerprint(current)!==basis||hash(sourceBasis(s,current.intent.sourceIds))!==materials.basis)throw fail('资料在整理期间变化，请重新准备',409);
        this.invalidate(current,s);current.materials=materials;current.draftVersion++;current.status='draft';
        row.attachments=[...new Map(materials.files.filter(f=>f.managedAttachmentId).map(f=>[f.managedAttachmentId,{id:f.managedAttachmentId,name:f.name,mime:this.store.attachment(workspaceId,f.managedAttachmentId).mime,size:f.size,sha256:f.sha256,url:'/api/v2/attachments/'+f.managedAttachmentId+'?workspaceId='+encodeURIComponent(workspaceId)}])).values()];
        return {fileCount:materials.files.length};
      });
    });
  }
  validateIntent(s,w,identity,kind) {
    const i=w.intent,project=s.projects.find(p=>p.id===i.projectId&&!p.archived),special=s.cases.find(c=>c.id===i.caseId&&!c.archived);
    if(kind==='cancel')return {attendees:[],labels:{project:project?.title||special?.title||'原业务对象',mainNode:s.flowNodes.find(n=>n.id===i.mainNodeId)?.title||'原主节点',references:[]}};
    if(!project&&!special)throw fail('请选择当前项目或专项');
    const nodes=[i.mainNodeId,...i.referenceNodeIds].filter(Boolean);
    if(nodes.some(id=>!s.flowNodes.some(n=>n.id===id&&!n.archived&&n.projectIds.includes(i.projectId)))||i.referenceNodeIds.includes(i.mainNodeId))throw fail('主节点或引用节点不属于当前项目',409);
    if(kind==='minutes'&&(!project||!i.mainNodeId))throw fail('纪要先暂存在会议记录中；确认项目及主节点后才能归档');
    if(kind!=='minutes'&&(!i.calendarId||!time(i.start)||!time(i.end)||Date.parse(i.start)>=Date.parse(i.end)||!i.title||i.title.length>200))throw fail('请填写日历、标题和带时区的有效起止时间');
    const attendees=i.attendeeIds.map(id=>{
      const p=s.people.find(p=>p.id===id&&!p.archived&&p.identityVerified&&p.feishuIdType==='open_id'&&p.feishuAppId===identity.appId&&p.feishuTenantKey===identity.tenantKey&&/^ou_\w+$/.test(p.feishuUserId));
      if(!p)throw fail('参会人的当前飞书身份待核对：'+id,409);return {id:p.feishuUserId,name:p.title,localId:id};
    });
    if(unique(attendees.map(a=>a.id)).length!==attendees.length)throw fail('参会人身份重复');
    return {attendees,labels:{project:project?.title||special.title,mainNode:s.flowNodes.find(n=>n.id===i.mainNodeId)?.title||'待本人确认主节点',references:i.referenceNodeIds.map(id=>s.flowNodes.find(n=>n.id===id).title)}};
  }
  async checkBasis(workspaceId,id,preview,{files=true}={}) {
    const {state,w}=this.record(workspaceId,id);
    if(!preview||w.preview?.fingerprint!==preview.fingerprint||w.draftVersion!==preview.draftVersion||intentFingerprint(w)!==preview.localBasis)throw fail('旧预览已失效，请重新准备并审阅',409);
    if(preview.kind!=='cancel'&&hash(sourceBasis(state,w.intent.sourceIds))!==hash(preview.sources))throw fail('来源版本已变化或撤回，旧预览已失效',409);
    const check=this.validateIntent(state,w,preview.identity,preview.kind);
    if(hash(check)!==preview.contextBasis)throw fail('节点或参会人身份已变化，旧预览已失效',409);
    if(files)for(const file of preview.files)await this.materials.resolve(file,{state});
    if(preview.kind==='minutes'&&minutesFingerprint(w.minutes)!==preview.minutesBasis)throw fail('纪要版本已变化，须重新核对内容及节点',409);
    if(preview.kind==='minutes'&&hash(state.deliverables.find(r=>r.id===preview.delivery.previous?.id)||null)!==preview.delivery.localBasis)throw fail('交付物的验收或版本在审阅后变化，须重新核对',409);
    return {state,w};
  }
  prepare({workspaceId,sourceId,expectedVersion,kind='create',removeFileTokens=[]}) {
    const {w}=this.record(workspaceId,sourceId);this.assertEditable(workspaceId,sourceId,w,expectedVersion);
    return this.job(workspaceId,sourceId,'prepare',async signal=>{
      if(!['create','update','cancel','minutes'].includes(kind))throw fail('会议操作类型无效');
      const {state,w:initial}=this.record(workspaceId,sourceId),basis=intentFingerprint(initial),identity=await this.client.identity({signal});
      if(initial.identity&&!sameAccount(initial.identity,identity))throw fail('当前飞书账号与此会议不一致',409);
      const context=this.validateIntent(state,initial,identity,kind),sources=kind==='cancel'?[]:sourceBasis(state,initial.intent.sourceIds);
      if(['create','update'].includes(kind)&&(!initial.materials||initial.materials.basis!==hash(sources)))throw fail('请先准备与当前资料版本一致的讨论材料',409);
      if(kind==='create'&&initial.event)throw fail('已有日程身份，请选择更新',409);
      if(kind!=='create'&&!initial.event)throw fail('尚未创建日程，不能执行此操作');
      if(initial.event&&initial.event.calendarId!==initial.intent.calendarId)throw fail('已有日程不能切换日历',409);
      const remote=initial.event?await this.client.event(initial.event.calendarId,initial.event.eventId,{signal}):null;
      if(remote?.status==='cancelled'&&kind!=='cancel')throw fail('日程已取消，不能继续更新或归档',409);
      if(remote&&activeAttendees(remote).some(a=>a.type!=='user'||!a.user_id||!a.attendee_id))throw fail('日程含未核对的群组、会议室或外部参与人，请先在飞书核对',409);
      if(!Array.isArray(removeFileTokens)||removeFileTokens.some(t=>!attachmentTokens(remote||{}).includes(t)))throw fail('待移除的附件不在当前日程中',409);
      const files=['create','update'].includes(kind)?copy(initial.materials.files):[];
      if(files.some(f=>removeFileTokens.includes(initial.assets[f.id+':'+f.sha256]?.file_token)))throw fail('待移除附件仍用于本次讨论材料；请先调整所选资料或重新整理材料',409);
      for(const file of files)await this.materials.resolve(file,{state,signal});
      const retained=(remote?.attachments||[]).filter(a=>!removeFileTokens.includes(a.file_token));
      if(retained.some(a=>!Number.isFinite(Number(a.file_size))||Number(a.file_size)<0))throw fail('现有附件大小未返回，请先核对');
      if(retained.reduce((sum,a)=>sum+Number(a.file_size||0),0)+files.filter(f=>!retained.some(a=>a.file_token===initial.assets[f.id+':'+f.sha256]?.file_token)).reduce((sum,f)=>sum+f.size,0)>25*1024*1024)throw fail('保留附件与新增文件总大小超过25 MB');
      let delivery;
      if(kind==='minutes'){
        if(initial.minutes?.status!=='ready'||initial.minutes.documents.length!==1)throw fail('纪要尚不可归档，请核对生成、权限、版本或混入其他会议的问题',409);
        if(!this.deliverables)throw fail('纪要交付物适配器尚未接线；纪要内容已保留',503);
        const document=initial.minutes.documents[0];
        if(typeof document.content!=='string'||!document.content.trim()||fileHash(Buffer.from(document.content))!==document.sha256)throw fail('纪要正文为空或内容校验不一致，请重新读取后核对',409);
        const target=await this.deliverables.inspect({workspaceId,intent:initial.intent,identity,signal});
        if(!target.verified||target.remoteKind!=='film'||target.documentField!=='field_d06ce2'||target.relation!=='node_sub_workitems')throw fail('交付物类型、文档字段或节点子工作项关系未核对',409);
        if(this.mode==='live'&&target.protectedSpace)throw fail('TH2 写入保护仍启用；需总控接入具体受控路径',403);
        if((initial.delivery||initial.pendingDelivery)?.mainNodeId&&(initial.delivery||initial.pendingDelivery).mainNodeId!==initial.intent.mainNodeId)throw fail('已创建纪要的主节点不自动迁移，请保留原归档并交总控核对',409);
        const previous=initial.delivery||initial.pendingDelivery;
        const local=state.deliverables.find(r=>r.id===previous?.id);
        const accepted=local?.acceptanceStatus==='已验收';
        delivery={title:initial.intent.title+' · 会议纪要',target,document:copy(document),operation:previous?(previous.documentHash===document.sha256?'reuse':accepted?'revision':'update'):'create',previous:copy(previous||null),localBasis:hash(local||null)};
      }
      const id=randomUUID(),preview={id,kind,mode:this.mode,at:this.clock(),identity,intent:copy(initial.intent),draftVersion:initial.draftVersion,localBasis:basis,sources,contextBasis:hash(context),...context,description:initial.materials?.description||'',files,removedFiles:(remote?.attachments||[]).filter(a=>removeFileTokens.includes(a.file_token)),retainedFiles:retained,remoteBasis:remote?meetingEventFingerprint(remote):'',remote,minutesBasis:kind==='minutes'?minutesFingerprint(initial.minutes):'',delivery,warnings:['参会人配置为只阅读；第三人实际访问和其他附件格式仍待真实验收。',...(initial.intent.mainNodeId?[]:['主节点尚未确认，纪要只暂存，不创建交付物。'])]};
      const existingPeople=activeAttendees(remote||{}).map(a=>({id:a.user_id,name:a.display_name||state.people.find(person=>person.feishuUserId===a.user_id)?.title||a.user_id}));
      preview.removedAttendees=kind==='update'?existingPeople.filter(a=>!preview.attendees.some(b=>b.id===a.id)):[];
      preview.notificationRecipients=initial.intent.notify?Array.from(new Map([...existingPeople,...preview.attendees].map(a=>[a.id,a])).values()):[];
      if(kind==='cancel')preview.attendees=existingPeople;
      preview.fingerprint=hash(preview);
      this.store.transaction(()=>{
        const before=this.store.load(workspaceId),s=copy(before),row=sourceOf(s,sourceId),current=row.meetingWorkflow;
        if(intentFingerprint(current)!==basis||kind!=='cancel'&&hash(sourceBasis(s,current.intent.sourceIds))!==hash(sources))throw fail('资料在准备预览期间发生变化',409);
        this.invalidate(current,s);current.preview=preview;current.status='prepared';current.identity=identity;row.confirmed=false;row.version++;s.revision++;
        const draft={workspaceId,request:'本人审阅会议操作 '+kind,purpose:JSON.stringify({kind,previewId:id,fingerprint:preview.fingerprint}),creator:'会议准备',baseRevision:s.revision,idempotencyKey:'meeting-review-'+id,operations:[{id:'meeting-operation-'+id,kind:'sources',targetId:sourceId,action:'update',before:{meetingApprovalHash:row.meetingApprovalHash||'',confirmed:false},after:{meetingApprovalHash:preview.fingerprint,confirmed:true},reason:'审阅会议信息、文件、接收人及依据版本；执行另行回读',sourceIds:kind==='cancel'?[]:initial.intent.sourceIds,classification:'fact',missingInfo:[]}]};
        // Missing optional approval hashes have an explicit empty value for before-value checking.
        row.meetingApprovalHash ||= '';
        const submitted=this.domain.submitDraft(s,draft),saved=sourceOf(submitted.state,sourceId).meetingWorkflow;
        saved.preview.groupId=submitted.group.id;saved.groupFingerprint=submitted.group.fingerprint;
        this.store.save(submitted.state,before.revision);
      });return this.result(workspaceId,sourceId);
    });
  }
  review({workspaceId,sourceId,fingerprint,decision='accept'}) {
    return this.job(workspaceId,sourceId,'review',async()=>{
      const {w}=this.record(workspaceId,sourceId),p=w.preview;
      if(!p||p.fingerprint!==fingerprint)throw fail('审阅预览已变化',409);
      await this.checkBasis(workspaceId,sourceId,p);
      this.store.transaction(()=>{
        const before=this.store.load(workspaceId),group=before.changeGroups.find(g=>g.id===p.groupId);
        if(!group||group.fingerprint!==w.groupFingerprint||group.draftVersion!==1)throw fail('审核草稿已变化',409);
        const next=this.domain.reviewDraft(before,{groupId:group.id,draftVersion:1,decision,requestId:'meeting-approve-'+p.id+'-'+decision}),current=sourceOf(next,sourceId).meetingWorkflow;
        const accepted=next.changeGroups.find(g=>g.id===group.id)?.status==='accepted';
        current.status=accepted?'approved':decision==='reject'?'draft':'conflict';current.approvedFingerprint=accepted?fingerprint:'';
        this.store.save(next,before.revision);
      });return this.result(workspaceId,sourceId);
    });
  }
  async step(workspaceId,id,name,fn,{readOnly=false}={}) {
    let {w}=this.record(workspaceId,id,true),old=w.execution.steps[name];
    if(old?.status==='done')return old.result;
    if(old&&['running','unknown'].includes(old.status))throw fail('结果待核对：'+name+'；不能重复发送或换请求ID',409);
    if(!readOnly)await this.checkBasis(workspaceId,id,w.preview,{files:w.preview.kind!=='cancel'});
    this.mutate(workspaceId,id,'meeting.step.start',current=>{const prior=current.execution.steps[name];if(prior&&['running','unknown'].includes(prior.status))throw fail('另一执行尚未核对',409);current.execution.steps[name]={...prior,key:prior?.key||randomUUID(),status:'running',startedAt:this.clock(),readOnly};return {step:name};});
    try{
      const key=this.record(workspaceId,id,true).w.execution.steps[name].key,result=await fn(key);
      this.mutate(workspaceId,id,'meeting.step.receipt',current=>{Object.assign(current.execution.steps[name],{status:'done',result:result??null,error:'',finishedAt:this.clock()});return {step:name};});return result;
    }catch(error){
      this.mutate(workspaceId,id,'meeting.step.error',current=>{Object.assign(current.execution.steps[name],{status:readOnly||error.definiteFailure?'failed':'unknown',error:String(error.message).slice(0,700)});current.status=statusFromSteps(current.execution.steps);current.error=error.message;return {step:name,status:current.status};});throw error;
    }
  }
  eventBody(p,key) {
    return {summary:p.intent.title,description_rich:p.description,start_time:{timestamp:String(Math.floor(Date.parse(p.intent.start)/1000)),timezone:'Asia/Shanghai'},end_time:{timestamp:String(Math.floor(Date.parse(p.intent.end)/1000)),timezone:'Asia/Shanghai'},attendee_ability:'can_see_others',visibility:'private',need_notification:p.intent.notify,...(p.kind==='create'&&key?{source:'pm-meeting:'+key,vchat:{vc_type:'vc',meeting_settings:{auto_record:false,join_meeting_permission:'only_event_attendees'}},reminders:[]}: {})};
  }
  checkEvent(p,event,{attachments,attendees=false}={}) {
    if(event.status==='cancelled'||event.summary!==p.intent.title||event.description_rich!==p.description||event.attendee_ability!=='can_see_others'||event.visibility!=='private'||String(event.start_time?.timestamp)!==String(Date.parse(p.intent.start)/1000)||String(event.end_time?.timestamp)!==String(Date.parse(p.intent.end)/1000)||event.vchat?.vc_type!=='vc'||!/^https:\/\/vc\.feishu\.cn\//.test(event.vchat?.meeting_url||''))throw fail('日程内容、只读配置或会议入口与预览不一致',409);
    if(p.remote?.vchat?.meeting_url&&p.remote.vchat.meeting_url!==event.vchat.meeting_url)throw fail('原会议入口发生变化',409);
    if(attachments&&hash(attachmentTokens(event))!==hash([...attachments].sort()))throw fail('日程原生附件回读不一致',409);
    if(attendees&&hash(activeAttendees(event).map(a=>a.user_id).sort())!==hash(p.attendees.map(a=>a.id).sort()))throw fail('参会人回读不一致',409);
  }
  async readEvent(workspaceId,id,signal) {
    const {w}=this.record(workspaceId,id,true),event=await this.client.event(w.event.calendarId,w.event.eventId,{signal});
    this.mutate(workspaceId,id,'meeting.event.readback',current=>{current.event.snapshot=event;current.event.fingerprint=meetingEventFingerprint(event);return {eventId:event.event_id,status:event.status};});return event;
  }
  execute({workspaceId,sourceId,fingerprint}) {
    return this.job(workspaceId,sourceId,'execute',async signal=>{
      const {w}=this.record(workspaceId,sourceId),p=w.preview;
      if(w.restoredAt||this.store.load(workspaceId).workspaceType==='restored')throw fail('恢复工作区只保留会议历史，不能复用原执行授权',403);
      if(!p||p.fingerprint!==fingerprint)throw fail('旧预览已失效',409);
      if(w.execution?.status==='complete')return this.result(workspaceId,sourceId);
      const current=await this.checkBasis(workspaceId,sourceId,p,{files:p.kind!=='cancel'}),group=current.state.changeGroups.find(g=>g.id===p.groupId);
      if(w.approvedFingerprint!==fingerprint||group?.status!=='accepted'||group.fingerprint!==w.groupFingerprint||group.draftVersion!==1||current.state.sources.find(r=>r.id===sourceId)?.meetingApprovalHash!==fingerprint)throw fail('请先由本人审阅具体预览',403);
      if(Object.values(w.execution?.steps||{}).some(s=>['unknown','running'].includes(s.status)))throw fail('存在结果待核对的步骤，请先回读，不能重复执行',409);
      if(this.mode==='disabled')throw fail('外部执行尚未启用；草稿和审阅已保存',403);
      if(this.mode!==p.mode||this.mode==='simulation'&&this.client.simulation!==true)throw fail('预览与执行环境不一致，请重新准备；模拟模式必须使用模拟客户端',403);
      const identity=await this.client.identity({signal});if(!sameAccount(identity,p.identity))throw fail('飞书账号变化，已停止执行',409);
      if(this.mode==='live'&&(!this.authorizeExternal||!await this.authorizeExternal({workspaceId,sourceId,preview:copy(p)})))throw fail('此预览尚无具体真实写入授权',403);
      if(!w.execution){
        if(p.remote&&meetingEventFingerprint(await this.client.event(w.event.calendarId,w.event.eventId,{signal}))!==p.remoteBasis)throw fail('飞书日程在审阅后已变化，请重新准备',409);
        this.mutate(workspaceId,sourceId,'meeting.execution.start',current=>{if(current.execution)throw fail('会议执行已启动',409);current.execution={previewId:p.id,status:'running',steps:{}};current.status='executing';});
      }else this.mutate(workspaceId,sourceId,'meeting.execution.resume',current=>{current.status='executing';current.error='';});
      try{
        if(p.kind==='minutes')await this.executeMinutes(workspaceId,sourceId,p,signal);
        else await this.executeCalendar(workspaceId,sourceId,p,signal);
        return this.mutate(workspaceId,sourceId,'meeting.execution.complete',current=>{current.execution.status='complete';current.status=p.kind==='minutes'?'delivered':p.kind==='cancel'?'cancelled':'scheduled';current.error='';return {mode:this.mode,kind:p.kind};});
      }catch(error){
        this.mutate(workspaceId,sourceId,'meeting.execution.stopped',current=>{current.status=statusFromSteps(current.execution.steps);current.execution.status=current.status;current.error=String(error.message).slice(0,700);});throw error;
      }
    });
  }
  async executeCalendar(workspaceId,id,p,signal) {
    const step=(name,fn,options)=>this.step(workspaceId,id,name,fn,options),calendarId=p.intent.calendarId;
    if(p.kind==='create'){
      const created=await step('create-event',key=>this.client.createEvent(calendarId,this.eventBody(p,key),key,{signal}));
      this.mutate(workspaceId,id,'meeting.event.identity',w=>{w.event ||= {calendarId,eventId:created.event_id,snapshot:created,fingerprint:meetingEventFingerprint(created)};return {eventId:w.event.eventId};});
    }
    const eventId=this.record(workspaceId,id).w.event.eventId;
    if(p.kind==='cancel'){
      await step('cancel-event',()=>this.client.cancelEvent(calendarId,eventId,p.intent.notify,{signal}));
      const event=await this.readEvent(workspaceId,id,signal);if(event.status!=='cancelled')throw fail('取消尚未回读确认',409);return;
    }
    const tokens=[];
    for(const file of p.files){
      const assetKey=file.id+':'+file.sha256,existing=this.record(workspaceId,id).w.assets[assetKey];
      const uploaded=existing||await step('upload:'+file.id,async()=>this.client.upload(calendarId,file,await this.materials.resolve(file,{state:this.store.load(workspaceId),signal}),{signal}));
      this.mutate(workspaceId,id,'meeting.material.identity',w=>{w.assets[assetKey]=uploaded;return {fileId:file.id};});
      await step('verify:'+file.id,()=>this.client.verifyMedia(uploaded.file_token,file,{signal}),{readOnly:true});tokens.push(uploaded.file_token);
    }
    const expectedTokens=unique([...p.retainedFiles.map(a=>a.file_token),...tokens]);
    await step('save-event',async()=>{
      const before=await this.client.event(calendarId,eventId,{signal});
      if(p.kind==='update'&&meetingEventFingerprint(before)!==p.remoteBasis)throw fail('日程在执行过程中变化，停止覆盖',409,{definiteFailure:true});
      if(p.kind==='create'){this.checkEvent(p,before);if(attachmentTokens(before).length)throw fail('新日程出现未审阅附件，停止覆盖',409,{definiteFailure:true});}
      return this.client.patchEvent(calendarId,eventId,{...this.eventBody(p),attachments:[...expectedTokens.map(file_token=>({file_token})),...p.removedFiles.map(a=>({file_token:a.file_token,is_deleted:true}))]},{signal});
    });
    let event=await this.readEvent(workspaceId,id,signal);this.checkEvent(p,event,{attachments:expectedTokens});
    for(const old of activeAttendees(p.remote||{}).filter(a=>!p.attendees.some(b=>b.id===a.user_id))){
      await step('remove-attendee:'+old.user_id,()=>this.client.removeAttendee(calendarId,eventId,old.attendee_id,p.intent.notify,{signal}));
    }
    for(const attendee of p.attendees){
      // On resume, complete read-back allows us to skip people who are already invited.
      event=await this.client.event(calendarId,eventId,{signal});
      if(activeAttendees(event).some(a=>a.user_id===attendee.id))continue;
      await step('invite:'+attendee.id,()=>this.client.addAttendee(calendarId,eventId,attendee.id,p.intent.notify,{signal}));
    }
    event=await this.readEvent(workspaceId,id,signal);this.checkEvent(p,event,{attachments:expectedTokens,attendees:true});
  }
  readMinutes({workspaceId,sourceId}) {
    return this.job(workspaceId,sourceId,'minutes-read',async signal=>{
      const {w}=this.record(workspaceId,sourceId);if(!w.event)throw fail('尚无日程身份');
      if(['executing','unknown'].includes(w.status))throw fail('先完成或核对当前执行步骤',409);
      const identity=await this.client.identity({signal});if(!sameAccount(identity,w.identity))throw fail('飞书账号与日程不一致',409);
      const event=await this.client.event(w.event.calendarId,w.event.eventId,{signal});let result;
      if(event.status==='cancelled')result={status:'cancelled',documents:[],errors:[]};
      else try{
        result=await this.client.minutes(w.event.calendarId,w.event.eventId,{signal});
        if(result.status==='unavailable'&&result.errors?.some(e=>/permission|无权|权限/i.test(e)))result.status='permission_denied';
        if(result.documents.some(d=>d.stale))result.status='stale';
        if(result.documents.length>1||result.documents.some(d=>d.eventId&&d.eventId!==w.event.eventId||d.meetingId&&d.meetingId!==result.meetingId||d.meetingIds?.some(id=>id!==result.meetingId)))result.status='mixed';
        if(result.status==='ready'&&(!result.meetingId||result.documents.length!==1))result.status='unverified';
        if(result.status==='ready'&&result.documents.some(d=>typeof d.content!=='string'||!d.content.trim())){result.status='unavailable';result.errors=[...(result.errors||[]),'本次纪要没有返回正文，暂不能归档。'];}
      }catch(error){result={status:/permission|无权|权限/i.test(error.message)?'permission_denied':'unavailable',documents:[],errors:[error.message]};}
      return this.mutate(workspaceId,sourceId,'meeting.minutes.refresh',(current,s)=>{
        if(current.minutes&&minutesFingerprint(current.minutes)!==minutesFingerprint(result)){current.history.push({minutes:copy(current.minutes),at:this.clock()});if(current.preview?.kind==='minutes'){this.invalidate(current,s);current.status='scheduled';}}
        if(!result.documents.length&&current.minutes?.documents.length)result.previousDocuments=current.minutes.documents.map(d=>({...d,stale:true}));
        current.minutes={...result,readAt:this.clock()};return {status:result.status};
      });
    });
  }
  async executeMinutes(workspaceId,id,p,signal) {
    const step=(name,fn,options)=>this.step(workspaceId,id,name,fn,options),d=p.delivery,adapter=this.deliverables;
    if(this.mode==='simulation'&&adapter.simulation!==true)throw fail('模拟模式必须使用模拟交付物适配器',403);
    const latest=await this.client.minutes(p.intent.calendarId,this.record(workspaceId,id).w.event.eventId,{signal});
    if(minutesFingerprint(latest)!==p.minutesBasis)throw fail('纪要内容或版本已变化，须重新核对',409);
    const target=await adapter.inspect({workspaceId,intent:p.intent,identity:p.identity,signal});
    if(hash(target)!==hash(d.target)||this.mode==='live'&&target.protectedSpace)throw fail('交付物字段或节点映射已变化',409);
    const payload={title:d.title,remoteKind:'film',projectId:p.intent.projectId,mainNodeId:p.intent.mainNodeId,document:d.document,target,revisionOf:d.operation==='revision'?d.previous.remoteId:null};
    let remoteId=d.previous?.remoteId;
    if(['create','revision'].includes(d.operation))remoteId=(await step('create-deliverable',key=>adapter.create({...payload,idempotencyKey:key,signal}))).id;
    if(!remoteId)throw fail('交付物创建结果缺少身份，不能视为成功');
    this.mutate(workspaceId,id,'meeting.deliverable.identity',w=>{w.pendingDelivery={remoteId,documentHash:d.operation==='update'?d.previous.documentHash:d.document.sha256,mainNodeId:p.intent.mainNodeId,referenceNodeIds:[],status:'created_unverified'};return {remoteId,nodeBound:false};});
    if(d.operation==='update')await step('update-document',key=>adapter.update({remoteId,document:d.document,idempotencyKey:key,expectedHash:d.previous.documentHash,target,signal}));
    const remote=await adapter.get({remoteId,target,signal});
    if(remote.id!==remoteId||remote.remoteKind!=='film'||remote.projectId!==p.intent.projectId||remote.document?.sha256!==d.document.sha256||remote.document?.token!==d.document.token)throw fail('交付物身份、文档版本或项目回读不一致',409);
    await step('attach-main',key=>adapter.attachMain({remoteId,nodeId:p.intent.mainNodeId,target,idempotencyKey:key,signal}));
    if(!await adapter.hasMain({remoteId,nodeId:p.intent.mainNodeId,target,signal}))throw fail('交付物已创建，主节点子工作项挂接待回读；不能以项目级关联代替',409);
    for(const nodeId of p.intent.referenceNodeIds){
      await step('reference:'+nodeId,key=>adapter.reference({remoteId,nodeId,target,idempotencyKey:key,signal}));
      if(!await adapter.hasReference({remoteId,nodeId,target,signal}))throw fail('引用节点尚未回读确认：'+nodeId,409);
    }
    this.mutate(workspaceId,id,'meeting.minutes.delivered',(w,s)=>{
      const localId=d.operation==='revision'||!w.delivery?'meeting-deliverable-'+hash([workspaceId,remoteId]).slice(0,24):w.delivery.id;
      let row=s.deliverables.find(r=>r.id===localId);
      const values={title:d.title,projectIds:[p.intent.projectId],sourceIds:[id],flowNodeIds:[p.intent.mainNodeId],meetingSourceId:id,meetingDocument:{...copy(d.document),readAt:d.document.readAt||w.minutes?.readAt},meetingRemoteId:remoteId};
      if(!row){row={id:localId,...values,status:'未开始',acceptanceStatus:'待验收',submissionStatus:'已提交',version:1};s.deliverables.push(row);}else{Object.assign(row,values);row.version++;}
      for(const nodeId of p.intent.referenceNodeIds)if(!s.relations.some(r=>!r.archived&&r.type==='会议纪要引用'&&r.fromId===nodeId&&r.toId===localId))s.relations.push({id:'meeting-reference-'+hash([nodeId,localId]).slice(0,24),title:'引用同一份会议纪要',projectIds:[p.intent.projectId],sourceIds:[id],type:'会议纪要引用',fromId:nodeId,toId:localId,version:1});
      w.delivery={id:localId,remoteId,documentHash:d.document.sha256,mainNodeId:p.intent.mainNodeId,referenceNodeIds:copy(p.intent.referenceNodeIds)};w.pendingDelivery=null;return {remoteId,mainNodeVerified:true,referenceNodeIds:p.intent.referenceNodeIds};
    });
  }
  reconcile({workspaceId,sourceId,eventId,fileToken}) {
    return this.job(workspaceId,sourceId,'reconcile',async signal=>{
      const {w}=this.record(workspaceId,sourceId),p=w.preview;if(!p||!w.execution)throw fail('没有待核对的执行');
      const identity=await this.client.identity({signal});if(!sameAccount(identity,p.identity))throw fail('飞书账号变化',409);
      const pending=Object.entries(w.execution.steps).filter(([,s])=>['running','unknown'].includes(s.status));
      for(const [name,step] of pending){
        let result;
        if(name==='create-event'){
          if(!eventId)throw fail('创建结果未知；请提供核对到的日程ID，不能重新创建',409);
          const event=await this.client.event(p.intent.calendarId,eventId,{signal});
          if(event.source!=='pm-meeting:'+step.key)throw fail('日程不含本次稳定请求标记，不能按标题认领',409);
          this.checkEvent(p,event);result=event;
          this.mutate(workspaceId,sourceId,'meeting.event.reconcile',next=>{next.event={calendarId:p.intent.calendarId,eventId,snapshot:event,fingerprint:meetingEventFingerprint(event)};});
        }else if(name.startsWith('upload:')){
          if(!fileToken)throw fail('上传结果未知；需要原上传文件Token并核对内容，不能盲目重传',409);
          const file=p.files.find(f=>'upload:'+f.id===name);await this.client.verifyMedia(fileToken,file,{signal});result={file_token:fileToken};
        }else if(['save-event','cancel-event'].includes(name)||name.startsWith('invite:')||name.startsWith('remove-attendee:')){
          const event=await this.readEvent(workspaceId,sourceId,signal);
          if(name==='cancel-event'&&event.status!=='cancelled')throw fail('取消结果仍未确认，保留待核对',409);
          if(name==='save-event'){
            const current=this.record(workspaceId,sourceId).w,tokens=unique([...p.retainedFiles.map(a=>a.file_token),...p.files.map(f=>current.assets[f.id+':'+f.sha256]?.file_token)]);
            if(tokens.includes(undefined))throw fail('附件身份尚未齐全',409);this.checkEvent(p,event,{attachments:tokens});
          }
          if(name.startsWith('invite:')&&!activeAttendees(event).some(a=>a.user_id===name.slice(7)))throw fail('邀请结果仍未确认，不能重复邀请',409);
          if(name.startsWith('remove-attendee:')&&activeAttendees(event).some(a=>a.user_id===name.slice(16)))throw fail('移除参与人结果仍未确认',409);
          result=name==='cancel-event'?{eventId:event.event_id}:event;
        }else{
          // The adapter must reconcile by the original request key; never mint a replacement key.
          result=await this.deliverables?.reconcile?.({step:name,key:step.key,preview:p,signal});
          if(!result)throw fail('交付物结果仍未知，需要按原请求及节点关系核对',409);
        }
        this.mutate(workspaceId,sourceId,'meeting.step.reconciled',current=>{Object.assign(current.execution.steps[name],{status:'done',result,error:'',reconciledAt:this.clock()});return {step:name};});
      }
      return this.mutate(workspaceId,sourceId,'meeting.reconcile.complete',current=>{current.status=statusFromSteps(current.execution.steps);current.error='';});
    });
  }
  start() {
    for(const workspace of this.store.list())for(const row of this.store.load(workspace.id).sources.filter(s=>s.meetingWorkflow?.execution)){
      if(row.meetingWorkflow.execution.status!=='complete'&&(row.meetingWorkflow.status==='executing'||Object.values(row.meetingWorkflow.execution.steps).some(s=>s.status==='running')))this.mutate(workspace.id,row.id,'meeting.execution.recover',w=>{for(const step of Object.values(w.execution.steps))if(step.status==='running')step.status=step.readOnly?'failed':'unknown';w.status=statusFromSteps(w.execution.steps);w.error='上次执行中断；已保存的外部身份和原请求ID保留，先核对再续办。';});
    }
  }
  async close(){this.closed=true;for(const job of this.jobs.values())job.controller.abort();await Promise.allSettled([...this.jobs.values()].map(j=>j.promise));}
}
