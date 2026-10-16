import {createHash} from 'node:crypto';

const fail=(message,status=422)=>Object.assign(new Error(message),{status});
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const active=(rows,id)=>rows.find(row=>row.id===id&&!row.archived);
const scalarFields=['kind','title','description','targetKind','targetId','projectId','caseId','assigneeId','dueDate','start','end','calendarId'];
const listFields=['attendeeIds','sourceIds','missingInfo'];
export const assistantActionSchema={type:'array',maxItems:4,items:{type:'object',properties:{
  ...Object.fromEntries(scalarFields.map(key=>[key,{type:'string',...(key==='kind'?{enum:['task','meeting']}:{})}])),
  ...Object.fromEntries(listFields.map(key=>[key,{type:'array',items:{type:'string'}}])),notify:{type:'boolean'},
},required:[...scalarFields,...listFields,'notify'],additionalProperties:false}};

/** A model proposes typed data only. No command, recipient open_id, approval or execution flag is accepted. */
export function validateAssistantActions(values,state,job,{model=false}={}) {
  if(values===undefined)return [];
  if(!Array.isArray(values)||values.length>4)throw fail('最多同时准备四项任务或会议');
  return values.map(value=>{
    if(!value||Object.keys(value).some(key=>![...scalarFields,...listFields,'notify'].includes(key)))throw fail('助手操作包含不支持的字段');
    if(scalarFields.some(key=>typeof value[key]!=='string'||value[key].length>(key==='description'?2000:key==='title'?200:180))||listFields.some(key=>!Array.isArray(value[key])||value[key].length>20||value[key].some(v=>typeof v!=='string'||v.length>300))||typeof value.notify!=='boolean'||!['task','meeting'].includes(value.kind))throw fail('任务或会议草稿格式无效');
    const v=structuredClone(value);
    for(const key of scalarFields)v[key]=v[key].trim();
    for(const key of listFields)v[key]=[...new Set(v[key])];
    if(v.projectId&&!active(state.projects,v.projectId)||v.caseId&&!active(state.cases,v.caseId))throw fail('项目或专项不在当前工作区');
    if(job.projectId&&v.projectId&&job.projectId!==v.projectId||job.contextRef?.kind==='cases'&&v.caseId&&v.caseId!==job.contextRef.id)throw fail('操作超出当前对话范围',409);
    if(v.targetId){
      if(!['actions','deliverables'].includes(v.targetKind))throw fail('任务只能关联具体工作或交付物');
      const target=active(state[v.targetKind],v.targetId);
      if(!target||job.projectId&&!target.projectIds.includes(job.projectId)||model&&!job.selectedObjectIds?.includes(v.targetId))throw fail('任务事项不在当前对话范围',409);
      if(v.projectId&&!target.projectIds.includes(v.projectId)||v.caseId&&target.caseId!==v.caseId)throw fail('事项与所选项目或专项不一致',409);
    } else if(v.targetKind)throw fail('关联事项缺少身份');
    if(v.assigneeId&&!active(state.people,v.assigneeId)||v.attendeeIds.some(id=>!active(state.people,id)))throw fail('人员不在当前工作区');
    if(v.sourceIds.some(id=>!active(state.sources,id)||model&&!job.sourceIds.includes(id)))throw fail('会议资料未经本轮读取或已经撤回',409);
    if(v.dueDate&&(!/^\d{4}-\d{2}-\d{2}$/.test(v.dueDate)||!Number.isFinite(Date.parse(v.dueDate))||new Date(v.dueDate).toISOString().slice(0,10)!==v.dueDate))throw fail('任务期限需要有效日期');
    for(const key of ['start','end'])if(v[key]&&(!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v[key])||!Number.isFinite(Date.parse(v[key]))))throw fail('会议时间需要明确日期和时区');
    return v;
  });
}

export class AssistantActions {
  constructor({assistant,reminders,meetings,mode='disabled'}) {
    Object.assign(this,{assistant,reminders,meetings,mode,store:assistant.store,domain:assistant.domain});
    this.running=new Map();this.closed=false;
    if(mode==='simulation'&&(!reminders.client.simulation||!meetings.client.simulation))throw fail('隔离助手必须使用模拟任务与会议适配器',403);
  }
  job(workspaceId,jobId,{current=false}={}) {
    const job=this.assistant.get(jobId,workspaceId);
    if(job.status!=='completed'||!job.sessionId)throw fail('请等待当前对话完成',409);
    if(current&&(job.restored||job.evidenceStatus==='stale'))throw fail('原依据已变化或来自恢复记录，请重新提问后准备操作',409);
    return job;
  }
  patch(workspaceId,jobId,index,plan) {
    const job=this.job(workspaceId,jobId);
    job.actionPlans={...job.actionPlans,[index]:plan};this.assistant.save(job);return plan;
  }
  source(plan,state) {return plan?.sourceId?state.sources.find(s=>s.id===plan.sourceId):null;}
  card(job,index,state) {
    const proposed=job.actionRequests[index],plan=job.actionPlans?.[index],source=this.source(plan,state);
    const run=source?.reminderRun,w=source?.meetingWorkflow;
    const historical=!!job.restored;
    const running=this.running.has(job.workspaceId+':'+job.id+':'+index);
    const remoteStatus=run?.status||w?.status;
    const inProgress=running&&plan?.status==='preparing'?'preparing':running&&plan?.status==='executing'&&!['scheduled','readback_verified','unknown','needs_reconcile','partial'].includes(remoteStatus)?'executing':'';
    const interrupted=!running&&plan?.status==='preparing';
    return {index,draft:plan?.draft||proposed,revision:plan?.revision||0,fingerprint:historical?'':plan?.fingerprint||'',
      status:historical?'historical':inProgress||remoteStatus||(interrupted?'draft':plan?.status)||'draft',error:interrupted?'上次准备中断，草稿已保留，请重新准备。':plan?.error||run?.error||w?.error||'',
      preview:plan?.preview||null,sourceId:historical?'':plan?.sourceId||'',
      task:historical?null:run?.items[0]?.taskReadback||plan?.reusedTask||null,
      taskUrl:historical?'':run?.items[0]?.taskUrl||plan?.reusedTask?.url||'',
      meeting:historical?null:w?.event||null,meetingPreview:historical?null:w?.preview||null,
      steps:historical?{}:w?.execution?.steps||{},stale:job.evidenceStatus==='stale',mode:this.mode};
  }
  list({workspaceId,jobId}) {
    const job=this.job(workspaceId,jobId),state=this.store.load(workspaceId);
    const targets=['actions','deliverables'].flatMap(kind=>state[kind].filter(r=>!r.archived&&(!job.projectId||r.projectIds.includes(job.projectId))&&(!job.contextRef||job.contextRef.kind!=='cases'||r.caseId===job.contextRef.id)).map(r=>({kind,id:r.id,title:r.title,scopeLabel:r.projectIds.map(id=>{const p=active(state.projects,id);return p?.code||p?.title||'';}).join('、'),projectIds:r.projectIds,caseId:r.caseId||'',assigneeId:r.executorId||r.ownerId||''})));
    return {cards:(job.actionRequests||[]).map((_,i)=>this.card(job,i,state)),options:{personalScope:job.contextRef?.kind==='sources'&&state.sources.find(s=>s.id===job.contextRef.id)?.workItem?.association.kind==='personal',
      projects:state.projects.filter(p=>!p.archived&&(!job.projectId||p.id===job.projectId)).map(p=>({id:p.id,title:p.title})),
      people:state.people.filter(p=>!p.archived&&p.identityVerified).map(p=>({id:p.id,title:p.title})),targets,
      sources:state.sources.filter(s=>!s.archived&&job.sourceIds.includes(s.id)).map(s=>({id:s.id,title:s.title})),
    },mode:this.mode};
  }
  async resolvePerson(input){return this.lock({...input,index:'person'},async()=>{
    const {workspaceId,jobId}=input,query=String(input.query||'').trim();
    this.job(workspaceId,jobId,{current:true});
    if(this.mode==='disabled'||!this.reminders.client.resolveOwner)throw fail('人员查询服务尚未接线',503);
    if(query.length<2||query.length>50)throw fail('请输入完整姓名或工作邮箱');
    const identity=await this.reminders.client.identity({signal:AbortSignal.timeout(35000)});
    const proof=await this.reminders.client.resolveOwner(query.includes('@')?{email:query}:{name:query},{signal:AbortSignal.timeout(35000)});
    if(!/^ou_\w+$/.test(proof.userId||''))throw fail('未核对到有效的飞书身份',409);
    let personId;
    this.store.transaction(()=>{
      const before=this.store.load(workspaceId),matches=before.people.filter(p=>!p.archived&&p.title===query&&!p.feishuUserId);
      const existing=before.people.find(p=>!p.archived&&p.feishuUserId===proof.userId&&p.feishuAppId===identity.appId&&p.feishuTenantKey===identity.tenantKey)||(matches.length===1?matches[0]:null);
      personId=existing?.id||'person-feishu-'+hash([identity.scope,proof.userId]).slice(0,28);
      const after={title:existing?.title||proof.name||query,projectIds:existing?.projectIds||[],identityVerified:true,feishuUserId:proof.userId,feishuIdType:'open_id',feishuAppId:identity.appId,feishuTenantKey:identity.tenantKey};
      const next=this.domain.manualEdit(before,{kind:'people',targetId:personId,action:existing?'update':'create',before:existing?Object.fromEntries(Object.keys(after).map(k=>[k,existing[k]??null])):{},after,requestId:'assistant-person-'+hash([personId,after,before.revision])});
      this.store.save(next,before.revision);
    });
    return {...this.list(input),resolvedPersonId:personId};
  });}
  lock(input,fn) {
    const key=input.workspaceId+':'+input.jobId+':'+input.index;
    if(this.closed||this.assistant.closed)throw fail('助手服务正在停止',503);
    if(this.assistant.suspendedWorkspaces.has(input.workspaceId))throw fail('工作区正在恢复，请稍后重新核对',409);
    if(this.running.has(key))throw fail('当前操作正在处理，请等待结果',409);
    const promise=Promise.resolve().then(fn).finally(()=>this.running.delete(key));this.running.set(key,promise);return promise;
  }
  person(state,id,identity) {
    const p=active(state.people,id);
    if(!p?.identityVerified||p.feishuIdType!=='open_id'||!/^ou_\w+$/.test(p.feishuUserId)||p.feishuAppId!==identity.appId||p.feishuTenantKey!==identity.tenantKey)throw fail('负责人或参会人的当前飞书身份需要核对',409);
    return p;
  }
  async prepare(input) {return this.lock(input,async()=>{
    const {workspaceId,jobId,index,draft,requestId,expectedVersion}=input;
    if(!Number.isInteger(index)||index<0||typeof requestId!=='string'||!requestId||requestId.length>180)throw fail('操作请求无效');
    const job=this.job(workspaceId,jobId,{current:true}),state=this.store.load(workspaceId),old=job.actionPlans?.[index];
    if(this.mode==='disabled')throw fail('任务与会议执行服务尚未接线',503);
    if(!job.actionRequests?.[index]||draft?.kind!==job.actionRequests[index].kind)throw fail('本轮没有这项操作',404);
    const d=validateAssistantActions([draft],state,job)[0],inputHash=hash(d);
    if(old?.requestId===requestId){if(old.inputHash!==inputHash)throw fail('同一请求不能修改内容',409);return this.list(input);}
    if((old?.revision||0)!==expectedVersion)throw fail('操作卡已被修改，请刷新后核对',409);
    const priorSource=this.source(old,state),priorRun=priorSource?.reminderRun,priorMeeting=priorSource?.meetingWorkflow;
    if(old?.executionStarted||old?.status==='reused'||priorRun&&!['pending_review'].includes(priorRun.status)||priorMeeting&&(priorMeeting.event||['unknown','executing','partial','scheduled'].includes(priorMeeting.status)))throw fail('已有执行记录，请先核对原结果，不重复创建',409);
    if(!d.title||!d.description)throw fail('请补充标题和工作说明或会议议题');
    if(old?.localGroupId&&state.changeGroups.find(g=>g.id===old.localGroupId)?.status==='accepted')throw fail('原本地任务已接受，请继续处理原操作',409);
    // Changed content withdraws both the previous local draft and its executable preview.
    this.store.transaction(()=>{
      const before=this.store.load(workspaceId),next=structuredClone(before);let changed=false;
      const group=next.changeGroups.find(g=>g.id===old?.localGroupId);
      if(group&&['pending','partial','conflict'].includes(group.status)){group.status='withdrawn';changed=true;}
      const source=this.source(old,next);
      if(source?.reminderRun?.status==='pending_review'){source.archived=true;source.version++;changed=true;}
      if(changed){next.revision++;this.store.save(next,before.revision);}
    });
    const plan={draft:d,revision:(old?.revision||0)+1,requestId,inputHash,status:'preparing',createdAt:new Date().toISOString(),sourceId:old?.sourceId||'',error:''};
    this.patch(workspaceId,jobId,index,plan);
    try {
      if(d.kind==='task')await this.prepareTask(input,job,plan);
      else await this.prepareMeeting(input,job,plan);
      plan.status=plan.reusedTask?'reused':'prepared';
      plan.fingerprint=hash([jobId,index,plan.revision,plan.preview,plan.localGroupId,plan.sourceId]);
      this.patch(workspaceId,jobId,index,plan);
    } catch(error){plan.status='draft';plan.error=error.message;this.patch(workspaceId,jobId,index,plan);throw error;}
    return this.list(input);
  });}
  async prepareTask(input,job,plan) {
    const {workspaceId,jobId,index}=input,d=plan.draft;
    const {identity,items}=await this.reminders.propose({workspaceId,targetIds:d.targetId?[d.targetId]:[]});
    const state=this.store.load(workspaceId);
    let person,assignee,targetId=d.targetId;
    if(targetId){
      const candidate=items.find(i=>i.targetId===targetId&&i.kind===d.targetKind);
      if(!candidate?.taskEligible)throw fail(candidate?.remoteIssue||'当前事项的负责人或任务关联需要核对',409);
      assignee=candidate.assignee;
      person=d.assigneeId?this.person(state,d.assigneeId,identity):null;
      if(person&&person.feishuUserId!==assignee)throw fail('任务负责人须与原事项一致；变更职责请先在原事项核对',409);
      const name=person?.title||candidate.recipients.find(p=>p.id===assignee)?.name;
      plan.preview={title:d.title,description:d.description,dueDate:d.dueDate,assignee:name,identity:identity.name,newItem:false,targetTitle:candidate.title};
      if(candidate.taskLinks.length){
        const link=candidate.taskLinks[0],remote=state.externalLinks.find(l=>l.id===link.id)?.taskContext;
        plan.reusedTask={...link,summary:link.title};plan.sourceId='';
        plan.preview={...plan.preview,title:remote?.summary||link.title,description:remote?.description||'已有对应任务，请打开原任务查看工作说明。',dueDate:remote?.due?.timestamp?new Date(Number(remote.due.timestamp)+8*3600000).toISOString().slice(0,10):'原任务未设置期限'};return;
      }
      if(!d.dueDate)throw fail('请补充任务期限');
      const result=await this.reminders.prepare({workspaceId,items:[{...candidate,recipientIds:[assignee],sendMessage:false,createTask:true,taskTitle:d.title,message:d.description,dueDate:d.dueDate}]});
      plan.sourceId=result.source.id;
      plan.taskApprovalHash=result.source.reminderRun.approvalHash;
    } else {
      if(!d.dueDate)throw fail('请补充任务期限');
      person=this.person(state,d.assigneeId,identity);assignee=person.feishuUserId;
      const topic=job.contextRef?.kind==='sources'?state.sources.find(r=>r.id===job.contextRef.id&&r.workItem&&!r.archived):null;
      if(!d.projectId&&!d.caseId&&topic?.workItem.association.kind!=='personal')throw fail('请选择任务所属项目、专项或已确认的个人事项');
      const special=d.caseId?active(state.cases,d.caseId):null;
      if(special&&(special.status==='已关闭'||special.myRole==='关注'))throw fail('该专项当前职责或状态不允许派发任务，请先核对专项职责',409);
      if([...state.actions,...state.deliverables].some(r=>!r.archived&&r.title===d.title&&(d.projectId?r.projectIds.includes(d.projectId):r.caseId===d.caseId)))throw fail('已有同名事项，请选择原事项并核对是否已有 Tasks',409);
      targetId='assistant-task-'+hash([workspaceId,jobId,index]).slice(0,28);
      const after={...(topic?{workItemId:topic.id}:{}),title:d.title,description:d.description,projectIds:d.projectId?[d.projectId]:[],...(d.caseId?{caseId:d.caseId}:{}),executorId:person.id,executor:person.title,dueAt:d.dueDate,executionChannel:'feishu_task',executionStatus:'待确认',acceptanceStatus:'待验收',status:'近期跟进'};
      const result=this.store.command({type:'submitDraft',workspaceId,draft:{workspaceId,request:job.text,purpose:'本人核对后新增独立任务并关联飞书 Tasks',creator:'智能助手任务卡',baseRevision:state.revision,idempotencyKey:'assistant-action-'+jobId+'-'+index+'-'+plan.revision,operations:[{id:'new-task',kind:'actions',targetId,action:'create',before:{},after,reason:'独立飞书任务，保留原事项关联，交付标记另行读取',sourceIds:topic?[topic.id]:[],classification:'fact',missingInfo:[]}]}});
      plan.localGroupId=result.group.id;plan.groupFingerprint=result.group.fingerprint;plan.sourceId='';
      plan.preview={title:d.title,description:d.description,dueDate:d.dueDate,assignee:person.title,identity:identity.name,newItem:true,targetTitle:d.title};
    }
    plan.identity=identity;plan.assignee=assignee;plan.targetId=targetId;
  }
  async prepareMeeting(input,job,plan) {
    const {workspaceId,jobId,index}=input,d=plan.draft;
    if(!d.calendarId||!d.start||!d.end||Date.parse(d.end)<=Date.parse(d.start))throw fail('请选择日历并补充有效的开始和结束时间');
    const sourceId='assistant-meeting-note-'+hash([jobId,index]).slice(0,28);
    this.store.transaction(()=>{
      const before=this.store.load(workspaceId),s=structuredClone(before),old=s.sources.find(r=>r.id===sourceId);
      const note={id:sourceId,title:'本人会议议题 · '+d.title,projectIds:d.projectId?[d.projectId]:[],caseIds:d.caseId?[d.caseId]:[],sourceIds:[],excerpt:d.description,type:'本人会议要求',version:(old?.version||0)+1,confirmed:false};
      if(old)Object.assign(old,note);else s.sources.push(note);s.revision++;this.store.save(s,before.revision);
    });
    const intent={projectId:d.projectId,caseId:d.caseId,title:d.title,calendarId:d.calendarId,start:d.start,end:d.end,attendeeIds:d.attendeeIds,sourceIds:[sourceId,...d.sourceIds],notify:d.notify,mainNodeId:job.contextRef.kind==='flowNodes'?job.contextRef.id:'',referenceNodeIds:[],...(job.contextRef.kind==='workspace'?{}:{contextRef:job.contextRef})};
    let result;
    if(plan.sourceId){const current=this.meetings.record(workspaceId,plan.sourceId);result=this.meetings.save({workspaceId,sourceId:plan.sourceId,expectedVersion:current.w.draftVersion,intent});}
    else result=this.meetings.create({workspaceId,intent,requestId:'assistant-'+jobId+'-'+index,initiatedBy:'user'});
    plan.sourceId=result.source.id;this.patch(workspaceId,jobId,index,plan);
    result=await this.meetings.prepareMaterials({workspaceId,sourceId:plan.sourceId,expectedVersion:result.source.meetingWorkflow.draftVersion});
    result=await this.meetings.prepare({workspaceId,sourceId:plan.sourceId,expectedVersion:result.source.meetingWorkflow.draftVersion,kind:'create'});
    const preview=result.source.meetingWorkflow.preview;
    plan.preview={title:d.title,description:preview.description,start:d.start,end:d.end,attendees:preview.attendees.map(p=>p.name),identity:preview.identity.name,notify:d.notify,files:preview.files.map(f=>({name:f.name,size:f.size})),project:preview.labels.project};
    plan.meetingFingerprint=preview.fingerprint;
  }
  async execute(input) {return this.lock(input,async()=>{
    const {workspaceId,jobId,index,fingerprint}=input,job=this.job(workspaceId,jobId),plan=job.actionPlans?.[index];
    if(job.restored||!plan?.fingerprint||plan.fingerprint!==fingerprint)throw fail('操作预览已变化，请重新核对',409);
    if(this.mode==='disabled')throw fail('助手操作服务尚未接入执行适配器',503);
    if(this.mode==='live'&&this.store.load(workspaceId).workspaceType!=='official')throw fail('此工作区未允许真实业务执行',403);
    const card=this.card(job,index,this.store.load(workspaceId));
    if(['reused','readback_verified','scheduled'].includes(card.status))return this.list(input);
    if(job.evidenceStatus==='stale'&&!plan.executionStarted)throw fail('原依据已变化，请重新准备',409);
    if(Date.now()-Date.parse(plan.createdAt)>30*60*1000&&!plan.executionStarted)throw fail('预览已超过30分钟，请重新准备',409);
    plan.executionStarted=true;plan.status='executing';plan.error='';this.patch(workspaceId,jobId,index,plan);
    try {
      if(plan.draft.kind==='task'){
        if(!plan.sourceId){
          const identity=await this.reminders.client.identity({signal:AbortSignal.timeout(35000)});
          if(identity.scope!==plan.identity.scope||identity.userId!==plan.identity.userId)throw fail('飞书执行账号已变化，请重新核对',409);
          const state=this.store.load(workspaceId),person=this.person(state,plan.draft.assigneeId,identity),group=state.changeGroups.find(g=>g.id===plan.localGroupId);
          if(person.feishuUserId!==plan.assignee||!group||group.fingerprint!==plan.groupFingerprint)throw fail('本地任务草稿或负责人已变化，请重新核对',409);
          if(group.status!=='accepted')this.store.command({workspaceId,type:'review',groupId:group.id,draftVersion:group.draftVersion,decision:'accept',requestId:'assistant-task-review-'+group.id});
          const current=active(this.store.load(workspaceId).actions,plan.targetId),expected=group.operations.find(op=>op.kind==='actions'&&op.targetId===plan.targetId)?.after;
          if(!current||!expected||Object.entries(expected).some(([key,value])=>JSON.stringify(current[key])!==JSON.stringify(value)))throw fail('任务内容在核对后已变化，请先查看原事项',409);
          if(current.workItemId)this.store.transaction(()=>{
            const before=this.store.load(workspaceId),next=structuredClone(before),topic=next.sources.find(row=>row.id===current.workItemId&&row.workItem&&!row.archived);
            if(!topic||topic.workItem.actionTargets?.some(ref=>ref.id===current.id))return;
            const ref={kind:'actions',id:current.id};topic.workItem.actionTargets=[...(topic.workItem.actionTargets||[]),ref];
            if(!['deliverables','actions'].includes(topic.workItem.businessTarget?.kind))topic.workItem.businessTarget=ref;
            topic.workItem.history.push({at:new Date().toISOString(),operation:'task-linked',reason:'已确认的 Tasks 操作沿用本事项，执行结果在同一处回读',targetId:current.id});topic.version++;next.revision++;
            next.audit.push({id:'link-task-'+current.id,time:new Date().toISOString(),operation:'work-item.task-link',objectId:topic.id,actor:'本人已确认操作',before:null,after:ref,revision:next.revision});this.store.save(next,before.revision);
          });
          const {items}=await this.reminders.propose({workspaceId,targetIds:[plan.targetId]}),candidate=items.find(i=>i.targetId===plan.targetId);
          if(!candidate||candidate.assignee!==plan.assignee)throw fail('任务事项的负责人已变化',409);
          if(candidate.taskLinks.length)throw fail('已经存在关联任务，请核对原结果',409);
          const result=await this.reminders.prepare({workspaceId,items:[{...candidate,recipientIds:[plan.assignee],sendMessage:false,createTask:true,taskTitle:plan.draft.title,message:plan.draft.description,dueDate:plan.draft.dueDate}]});
          plan.sourceId=result.source.id;this.patch(workspaceId,jobId,index,plan);
          plan.taskApprovalHash=result.source.reminderRun.approvalHash;this.patch(workspaceId,jobId,index,plan);
        }
        const run=this.source(plan,this.store.load(workspaceId))?.reminderRun;
        if(!run||run.approvalHash!==plan.taskApprovalHash)throw fail('原任务执行预览已变化，请重新核对',409);
        await this.reminders.send({workspaceId,sourceId:plan.sourceId,approvalHash:plan.taskApprovalHash});
      } else {
        const {w}=this.meetings.record(workspaceId,plan.sourceId);
        if(w.status==='prepared')await this.meetings.review({workspaceId,sourceId:plan.sourceId,fingerprint:plan.meetingFingerprint});
        await this.meetings.execute({workspaceId,sourceId:plan.sourceId,fingerprint:plan.meetingFingerprint});
      }
    }catch(error){plan.status='prepared';plan.error=error.message;this.patch(workspaceId,jobId,index,plan);throw error;}
    return this.list(input);
  });}
  async reconcile(input){return this.lock(input,async()=>{
    const job=this.job(input.workspaceId,input.jobId),plan=job.actionPlans?.[input.index];
    if(job.restored||!plan?.sourceId)throw fail('没有可回读的原执行记录',409);
    const args={workspaceId:input.workspaceId,sourceId:plan.sourceId};
    if(plan.draft.kind==='task')await this.reminders.reconcile(args);
    else await this.meetings.reconcile({...args,eventId:input.eventId||'',fileToken:input.fileToken||''});
    plan.error='';this.patch(input.workspaceId,input.jobId,input.index,plan);return this.list(input);
  });}
  async close(){this.closed=true;await Promise.allSettled(this.running.values());}
}
