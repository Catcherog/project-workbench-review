import {attachDirectDmIsolation} from './direct-dm-activation.mjs';
import {WorkbenchRules} from './workbench-rules.mjs';
import {WorkItems} from './work-items.mjs';
import {connectAssistantActions} from './assistant-actions-integration.mjs';
import {ManagementSignals} from './management-signals.mjs';
import {DiscoverySubjects} from './discovery-subjects.mjs';
import {ProjectChatIntake} from './project-chat-intake.mjs';
import {RiskAgent} from './risk-agent.mjs';
import {AIUsage} from './ai-usage.mjs';
import {RiskEvidenceReader} from './risk-evidence-reader.mjs';
import {FeishuEventBridge} from './feishu-event-bridge.mjs';
import { createServer } from 'node:http';
import { readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { LocalStore, findLegacy, kinds, hash } from './local-store.mjs';
import * as domain from '../dist-local/domain.mjs';
import { CodexAssistant } from './codex-assistant.mjs';
import { assistantRoute } from './assistant-http.mjs';
import { petSnapshot } from './pet-snapshot.mjs';
import { FeishuSync } from './feishu-sync.mjs';
import { DeliverableDocumentReader } from './deliverable-document-reader.mjs';
import { FeedbackIntake } from './feedback-intake.mjs';
import { TaskFeedbackBindings } from './task-feedback-bindings.mjs';
import { ResultReview } from './result-review.mjs';
import { ReminderExecution } from './reminder-execution.mjs';
import {DeliverableComments} from './deliverable-comments.mjs';
import { TaskContextIntake } from './task-context-intake.mjs';
import { MeetingIntake } from './meeting-intake.mjs';
import { CaseChatIntake } from './case-chat-intake.mjs';
import { ApprovalEvidence } from './approval-evidence.mjs';
import { MaterialIntake } from './material-intake.mjs';
import {DataCenterPublication} from './data-center-publication.mjs';
import {DataCenterFeishuPort} from './data-center-feishu.mjs';
import { FollowupService } from './followup-service.mjs';
import {MeetingWorkflow} from './meeting-workflow.mjs';
import {meetingWorkflowAction} from './meeting-routes.mjs';
import {managedMeetingMaterials, meetingFiles} from './meeting-integration.mjs';
import {MeetingDeliverableAdapter} from './meeting-deliverable-adapter.mjs';
import {DesktopNotificationQueue,feishuSelfNotification,FollowupNotificationPump} from './followup-notifications.mjs';
import {AIRuntimeSettings} from './ai-runtime.mjs';
import {analyseFeedbackWithCodex} from './feedback-ai.mjs';
import {AgentMonitor} from './agent-monitor.mjs';
import {WorkItemCoreService} from './work-item-core-service.mjs';
import {CoreFeishuInput} from './core-feishu-input.mjs';
import {scheduleCorePreparation} from './core-work-agent.mjs';
import {readCoreMaterial} from './core-material-reader.mjs';

const root=fileURLToPath(new URL('..',import.meta.url));
const release=JSON.parse(readFileSync(path.join(root,'release.json'),'utf8'));
export async function startServer(options={}) {
  const port=Number(options.port||process.env.PM_PORT||5173);
  if(!Number.isInteger(port)||port<1024||port>65535)throw Error('本地端口无效');
  const dataDir=path.resolve(options.dataDir||process.env.PM_DATA_DIR||path.join(root,'.local-workbench'));
  const production=path.join(root,'.local-workbench');
  const testMode=(options.testMode||process.env.PM_TEST_MODE==='1')&&dataDir!==production;
  const legacy=options.legacy!==undefined?options.legacy:process.env.PM_LEGACY_DB??(dataDir===production?findLegacy(root):null);
  const token=randomUUID(),origin='http://127.0.0.1:'+port;
  const store=new LocalStore(dataDir,{testMode,failMigration:options.failMigration});
  // No consumers/timers start until the persistent isolation binding is checked.
  try{
    await store.initialize(legacy);
    attachDirectDmIsolation({...options.directDmIsolationOptions,store,configuredFile:options.directDmLedger||process.env.PM_DIRECT_DM_ISOLATION_FILE});
  }catch(e){store.directDmIsolation?.close();store.close();throw e;}
  const workItems=new WorkItems({store,domain});
  const runtimeSettings=new AIRuntimeSettings(store);
  const aiUsage=new AIUsage(store);
  const backgroundAnalyse=(context,settings)=>aiUsage.run(context,{...settings,runtime:runtimeSettings.profile('background')},analyseFeedbackWithCodex);
  const assistant=new CodexAssistant({...options.assistantOptions,store,domain,runtimeSettings,aiUsage});
  const agentMonitor=new AgentMonitor({...options.agentMonitorOptions,store,domain,testMode});
  const blockedRiskRead=async()=>{throw Error('隔离环境尚未配置风险补查适配器');};
  const riskAgent=new RiskAgent({store,domain,monitor:agentMonitor,budgetStatus:()=>aiUsage.budgetStatus(),analyse:testMode?blockedRiskRead:backgroundAnalyse,reader:new RiskEvidenceReader({store,domain,...(testMode?{client:{identity:blockedRiskRead,run:blockedRiskRead}}:{})}),runtime:()=>runtimeSettings.profile('background'),...options.riskAgentOptions});
  const eventBridge=new FeishuEventBridge({store,domain,monitor:agentMonitor,testMode,...options.eventBridgeOptions});
  const feishuSync=new FeishuSync({...options.feishuSyncOptions,store,domain:options.feishuSyncOptions?.domain||domain});
  const documentReader=new DeliverableDocumentReader({...options.documentReaderOptions,store,domain:options.documentReaderOptions?.domain||domain,dataDir});
  const materialIntake=new MaterialIntake({store,domain,analyse:backgroundAnalyse,budgetStatus:()=>aiUsage.budgetStatus(),...options.intakeOptions});
  const feedbackIntake=new FeedbackIntake({analyse:backgroundAnalyse,...options.feedbackOptions,materialIntake,store,domain:options.feedbackOptions?.domain||domain});
  const taskBindings=new TaskFeedbackBindings({store,domain:options.feedbackOptions?.domain||domain,client:feedbackIntake.taskClient});
  const taskContext=new TaskContextIntake({store,domain,client:feedbackIntake.taskClient,analyse:backgroundAnalyse,...options.taskContextOptions});
  const meetingIntake=new MeetingIntake({store,domain,materialIntake,analyse:backgroundAnalyse,...options.meetingOptions});
  const caseChat=new CaseChatIntake({store,domain,materialIntake,analyse:backgroundAnalyse,...options.caseChatOptions});
  const blockedGroupRead=async()=>{throw Object.assign(Error('隔离环境尚未配置项目群模拟适配器'),{status:503});};
  const projectChats=new ProjectChatIntake({store,domain,materialIntake,client:testMode?{identity:blockedGroupRead,run:blockedGroupRead}:feedbackIntake.taskClient,metadata:testMode?{auth:blockedGroupRead,group:blockedGroupRead}:undefined,onCaseChanged:input=>caseChat.scheduleSuggest(input).catch(()=>{}),...options.projectChatOptions});
  const approvalEvidence=new ApprovalEvidence({store,domain,...options.approvalOptions});
  const resultReview=new ResultReview({analyse:backgroundAnalyse,...options.resultReviewOptions,store,domain:options.resultReviewOptions?.domain||domain,reader:documentReader});
  const desktopNotifications=new DesktopNotificationQueue({store,domain,client:feedbackIntake.taskClient});
  const notifications=options.followupOptions?.notifications||(testMode?{}:{desktop:desktopNotifications,feishu_self:feishuSelfNotification(feedbackIntake.taskClient)});
  const followups=new FollowupService({...options.followupOptions,notifications,store,domain});
  const notificationPump=new FollowupNotificationPump({store,followups,client:feedbackIntake.taskClient});
  const reminders=new ReminderExecution({analyse:backgroundAnalyse,...options.reminderOptions,store,domain,client:feedbackIntake.taskClient,bindings:taskBindings,followups});
  const core=new WorkItemCoreService({store,domain,client:feedbackIntake.taskClient,notifications,testMode,analyse:testMode?undefined:backgroundAnalyse,budgetStatus:()=>aiUsage.budgetStatus(),mode:testMode?'disabled':'live',refresh:testMode?undefined:async({workspaceId,sourceIds,targetIds=[]})=>{
    const latest=store.load(workspaceId),remoteTargets=targetIds.filter(id=>latest.deliverables.some(r=>r.id===id)||latest.externalObjects.some(r=>r.localObjectId===id&&r.system==='meegle'));
    if(remoteTargets.length)await feishuSync.refreshTargets(workspaceId,remoteTargets);
    const control=agentMonitor.control(workspaceId);if(control.enabled)await agentMonitor.poll(workspaceId);
    const current=store.load(workspaceId);for(const id of sourceIds){const source=current.sources.find(r=>r.id===id);if(source?.personalMessage||source?.caseChat)await riskAgent.reader.verifyMessage(source,AbortSignal.timeout(30000));}
  },...options.coreOptions});
  assistant.core=core;
  assistant.coreWorkAnalyse=options.coreWorkOptions?.analyse||(testMode&&!options.coreWorkOptions?.allowRealModel?undefined:(context,settings)=>aiUsage.run(context,{...settings,runtime:settings.runtime||runtimeSettings.profile('chat'),usageChannel:settings.usageChannel||'conversation'},analyseFeedbackWithCodex));
  core.readImages=async({state,row})=>{if(!state.sources.some(s=>row.sourceIds.includes(s.id)&&(s.attachments?.length||s.intakeDocument?.images?.length)))return [];const packet=await assistant.retrieval.retrieve({state,contextRef:{kind:'sources',id:row.id},projectId:'',query:row.title,sourceIds:row.sourceIds.slice(-20),history:[]});return packet.images.map(image=>{const p=packet.passages.find(p=>p.citationId===image.citationId);return {...image,sourceId:p.sourceId,attachmentId:p.locator.attachmentId};});};
  core.prepareDerived=input=>scheduleCorePreparation(assistant,input);
  assistant.onCoreWorkFinished=job=>{const state=store.load(job.workspaceId),row=state.sources.find(r=>r.workItem?.core?.preparation?.requestId===job.requestId);if(row)core.mutate(job.workspaceId,row.id,(_s,current)=>{const prep=current.workItem.core.preparation;prep.status=job.coreWorkOutcome?.failureCode==='AI_BUDGET'?'budget_wait':job.coreWorkOutcome?.status==='incomplete'?'blocked':job.coreWorkOutcome?.status||'blocked';prep.reason=job.coreWorkOutcome?.reason||'后续准备已核对';prep.jobId=job.id;});};
  followups.core=core;
  const coreInbox=new CoreFeishuInput({assistant,store,domain,client:feedbackIntake.taskClient,reader:riskAgent.reader});
  eventBridge.onMessage=input=>coreInbox.receive(input);coreInbox.start(()=>eventBridge.enabled());
  assistant.onCoreInputSaved=async(job)=>{const input=store.load(job.workspaceId).sources.find(r=>r.id===job.coreInputSourceId);if(input?.inputEnvelope?.origin==='feishu')await coreInbox.receipt({workspaceId:job.workspaceId,sourceId:input.id});};
  const comments=new DeliverableComments({...options.commentOptions,store,testMode,allowTestWrites:testMode&&!!options.commentOptions?.adapter});
  if(!testMode&&!reminders.resolveOwner)reminders.resolveOwner=async({workspaceId,deliverableId})=>{const context=await comments.inspect({workspaceId,deliverableId});return feedbackIntake.taskClient.resolveOwner(context.owner,{signal:AbortSignal.timeout(35000)});};
  const meetingOptions=options.meetingWorkflowOptions||{};
  const meetingMaterials=managedMeetingMaterials({store,domain,analyse:meetingOptions.analyse||backgroundAnalyse,readFile:meetingOptions.readFile});
  const meetingWorkflow=new MeetingWorkflow({...meetingOptions,store,domain,materials:meetingMaterials,
    mode:meetingOptions.mode||(testMode?'disabled':'live'),deliverables:meetingOptions.deliverables||new MeetingDeliverableAdapter({port:meetingOptions.deliverablePort}),
    authorizeExternal:async input=>store.load(input.workspaceId).workspaceType==='official'&&(!meetingOptions.authorizeExternal||await meetingOptions.authorizeExternal(input))});
  connectAssistantActions({assistant,reminders,meetingWorkflow,agentMonitor,riskAgent,runtimeSettings,mode:testMode?(reminders.client.simulation&&meetingWorkflow.client.simulation?'simulation':'disabled'):'live'});
  const rules=new WorkbenchRules({store,domain});
  const managementSignals=new ManagementSignals({store,domain});
  const discoverySubjects=new DiscoverySubjects({store,domain});
  const publicationOptions=options.dataPublicationOptions||{};
  const dataPublication=new DataCenterPublication({store,domain,mode:publicationOptions.mode||(testMode?'disabled':'live'),port:publicationOptions.port||(testMode?null:new DataCenterFeishuPort({readAttachment:(workspaceId,id)=>store.attachment(workspaceId,id)})),...publicationOptions});
  let restoreInFlight=null;
  async function restoreWorkspace(body) {
    const fingerprint=hash({token:body.token,mode:body.mode,workspaceId:body.workspaceId||null,confirmed:body.confirmed});
    if(restoreInFlight){if(restoreInFlight.fingerprint===fingerprint)return restoreInFlight.promise;throw Object.assign(Error('另一项恢复正在进行，请等待完成后重新预览'),{status:409});}
    const plan=store.checkRestore(body);
    if(plan.result)return plan.result;
    if(body.mode==='replace'&&[...meetingWorkflow.jobs.keys()].some(key=>key.startsWith(body.workspaceId+':')))throw Object.assign(Error('目标工作区的会议仍在处理，请先核对当前步骤再恢复'),{status:409});
    if(body.mode==='replace'){
      const target=store.load(body.workspaceId),id=body.workspaceId;
      const busy=!!core.pending||[...core.collaboration.jobs.keys()].some(key=>key.startsWith(id+':'))||riskAgent.jobs.has(id)||projectChats.jobs.has(id)||agentMonitor.jobs.has(id)||[...comments.jobs.keys()].some(key=>key.startsWith(id+':'))||[...dataPublication.jobs.keys()].some(key=>key.startsWith(id+':'))||[...reminders.jobs.keys()].some(key=>target.sources.some(source=>source.id===key))||[...followups.jobs.keys()].some(key=>key.startsWith(id+':'))||materialIntake.active?.workspaceId===id||materialIntake.queue.some(job=>job.workspaceId===id)||feedbackIntake.jobs.has(id)||feedbackIntake.analysisRuns.has(id)||meetingIntake.scans.has(id)||meetingIntake.queues.has(id)||taskContext.queues.has(id)||[...resultReview.pending.keys(),...taskContext.jobs.keys()].some(key=>key.startsWith(id+':'))||[...meetingIntake.jobs.keys(),...caseChat.jobs.keys()].some(key=>key.includes(':'+id+':'));
      if(busy)throw Object.assign(Error('目标工作区仍有资料、审核或提醒任务在处理，请完成或取消后重新预览恢复范围'),{status:409});
    }
    const restore=async()=>{
      const target=body.mode==='replace'?body.workspaceId:null;
      try {
        if(target)await agentMonitor.suspendWorkspace(target);
        if(target)await assistant.suspendWorkspace(target);
        const internal=target?{assistantFingerprint:store.assistantFingerprint(target)}:{};
        const result=await feishuSync.withSuspended(()=>store.restore(body,internal));
        if(target){const setting=core.settings(target);store.setSetting('coreAutomation:'+target,{...setting,enabled:false,revision:setting.revision+1,error:'恢复后需重新核对来源与运行范围；未重放外发'});}
        return result;
      } finally {if(target){assistant.resumeWorkspace(target);agentMonitor.resumeWorkspace(target);eventBridge.sync();}}
    };
    const promise=restore().finally(()=>{restoreInFlight=null;});
    restoreInFlight={fingerprint,promise,workspaceId:body.mode==='replace'?body.workspaceId:null};return promise;
  }
  const fail=(message,status=400,errors=[])=>Object.assign(new Error(message),{status,errors});
  const headers={
    'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
    'Content-Security-Policy':"default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
  };
  function json(res,value,status=200) {res.writeHead(status,{...headers,'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(value));}
  async function readBody(req) {
    if(!req.headers['content-type']?.startsWith('application/json'))throw fail('仅接受 application/json',415);
    const chunks=[];let length=0;
    for await(const chunk of req){length+=chunk.length;if(length>160*1024*1024)throw fail('请求过大',413);chunks.push(chunk);}
    try{return JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{throw fail('JSON 格式无效');}
  }
  function authorize(req,uiOnly=false) {
    if(req.headers['x-workbench-token']!==token)throw fail('本地请求令牌无效，请刷新工作台',403);
    const from=req.headers.origin,client=req.headers['x-workbench-client'];
    if(from&&from!==origin&&from!=='http://localhost:'+port)throw fail('拒绝跨源写入本地台账',403);
    if(!from&&client!=='codex'&&client!=='ui')throw fail('请求来源不明：需同源界面或声明 Codex CLI',403);
    if(uiOnly&&client==='codex')throw fail('Codex CLI 只允许读取、校验与提交草稿；业务接受请在审核台完成',403);
  }
  async function handle(req,res) {
    const host=req.headers.host;
    if(host!=='127.0.0.1:'+port&&host!=='localhost:'+port)throw fail('仅接受回环地址请求',403);
    const url=new URL(req.url,origin),p=url.pathname,w=url.searchParams.get('workspaceId');
    if(req.method==='OPTIONS')throw fail('不允许跨源调用',403);
    if(p==='/api/v2/core/material'){
      authorize(req,true);
      if(req.method!=='GET')throw fail('资料阅读仅支持只读请求',405);
      return json(res,readCoreMaterial({assistant,workspaceId:w,sourceId:url.searchParams.get('sourceId'),jobId:url.searchParams.get('jobId'),materialId:url.searchParams.get('materialId')}));
    }
    if(p==='/api/v2/core'){
      authorize(req,true);
      if(req.method==='GET')return json(res,core.view(w,url.searchParams.get('sourceId')));
      if(req.method!=='POST')throw fail('不支持的推进操作',405);
      if(restoreInFlight)throw fail('工作区正在恢复，请稍后继续',409);
      const body=await readBody(req);
      if(body.action==='configure')return json(res,core.configure(body));
      if(body.action==='check')return json(res,await core.check(body.workspaceId,body.sourceId));
      if(body.action==='dependency')return json(res,core.dependency(body));
      if(body.action==='delivery')return json(res,core.delivery(body));
      if(body.action==='prepare-messages')return json(res,await core.collaboration.prepare(body));
      if(body.action==='resolve-recipient')return json(res,await core.collaboration.resolveRecipient(body));
      if(body.action==='decide-messages')return json(res,core.collaboration.decide(body));
      if(body.action==='execute-messages')return json(res,await core.collaboration.execute(body));
      if(body.action==='reconcile-messages')return json(res,await core.collaboration.reconcile(body));
      if(body.action==='message-authority')return json(res,core.collaboration.authority({...body,action:body.authorityAction}));
      if(body.action==='reconcile-notice')return json(res,await core.reconcileNotice(body));
      if(body.action==='input-receipt')return json(res,await coreInbox.receipt(body));
      if(body.action==='associate-input')return json(res,await coreInbox.associate(body));
      throw fail('不支持的推进操作',422);
    }
    if(p==='/api/v2/work-items'){
      authorize(req,true);
      if(req.method==='GET')return json(res,url.searchParams.has('requestId')?{receipt:store.load(w).receipts['work-item:'+url.searchParams.get('requestId')]||null}:workItems.status(w));
      if(req.method!=='POST')throw fail('请从事项处理入口操作',405);
      if(restoreInFlight)throw fail('工作区正在恢复，请稍后核对',409);
      return json(res,workItems.operate(await readBody(req)));
    }
    if(p==='/api/v2/project-chats'){
      authorize(req,true);
      if(req.method==='GET')return json(res,projectChats.status(w));
      if(req.method!=='POST')throw fail('群采集操作类型无效',405);
      if(restoreInFlight)throw fail('正在恢复工作区，请稍后重新核对',409);
      const body=await readBody(req);
      if(body.action==='configure')return json(res,projectChats.configure(body));
      if(body.action==='bind')return json(res,await projectChats.bind(body));
      if(body.action==='unbind')return json(res,projectChats.unbind(body));
      if(body.action==='poll')return json(res,await projectChats.poll(body.workspaceId));
      throw fail('群采集操作类型无效');
    }
    if(p==='/api/v2/discovery-subjects'){
      authorize(req,true);
      if(req.method!=='POST')throw fail('请通过待定事项入口确认归属',405);
      if(restoreInFlight)throw fail('工作区正在恢复，请稍后核对',409);
      return json(res,discoverySubjects.classify(await readBody(req)));
    }
    if(p==='/api/v2/management-signals'){
      authorize(req,true);
      if(req.method!=='POST')throw fail('请通过事项处理入口保存判断',405);
      if(restoreInFlight)throw fail('工作区正在恢复，请稍后重新打开事项',409);
      return json(res,managementSignals.review(await readBody(req)));
    }
    if(p==='/api/v2/rules'){
      authorize(req,true);
      if(req.method==='GET')return json(res,rules.view(w));
      if(req.method!=='POST')throw fail('不支持的规则操作',405);
      const b=await readBody(req);if(restoreInFlight)throw fail('工作区正在恢复',409);
      if(b.action==='check')return json(res,rules.run(b));
      if(b.action==='register')return json(res,rules.register(b));
      throw fail('不支持的规则操作');
    }
    if(p==='/api/v2/data-center'){
      authorize(req,true);
      if(req.method==='GET'){store.load(w);return json(res,dataPublication.capabilities());}
      if(req.method!=='POST')throw fail('不支持的数据中心操作',405);
      if(req.headers.origin!==origin&&req.headers.origin!=='http://localhost:'+port)throw fail('挂载须由工作台界面审核提交',403);
      const body=await readBody(req);
      if(restoreInFlight?.workspaceId===body.workspaceId)throw fail('工作区正在恢复，请稍后重试',409);
      if(!['prepare','publish','reconcile','cancel'].includes(body.action))throw fail('不支持的挂载操作');
      return json(res,await dataPublication[body.action](body));
    }
    if(p==='/api/v2/ai-settings') {
      authorize(req,true);
      if(req.method==='GET')return json(res,runtimeSettings.view());
      if(req.method==='POST')return json(res,runtimeSettings.update(await readBody(req)));
      throw fail('不支持的模型设置操作',405);
    }
    if(p==='/api/v2/agent-monitor') {
      authorize(req,true);
      if(req.method==='GET')return json(res,agentMonitor.status(w));
      if(req.method!=='POST')throw fail('不支持的关注操作',405);
      const b=await readBody(req);
      if(restoreInFlight)throw fail('正在恢复工作区，请稍后重试',409);
      if(b.action==='configure')return json(res,agentMonitor.configure(b.workspaceId,b));
      if(b.action==='poll')return json(res,await agentMonitor.poll(b.workspaceId));
      throw fail('不支持的关注操作');
    }
    if(p==='/api/v2/ai-usage'){authorize(req);if(req.method==='GET')return json(res,aiUsage.status());if(req.method==='POST'){authorize(req,true);const input=await readBody(req);store.load(input.workspaceId);const result=aiUsage.configureBudget(input);for(const workspace of store.list())riskAgent.notify(workspace.id);void materialIntake.pump();return json(res,result);}throw fail('不支持的用量操作',405);}
    if(p==='/api/v2/risk-agent'){
      authorize(req);
      if(req.method==='GET')return json(res,riskAgent.status(w));
      if(req.method!=='POST')throw fail('不支持的风险研判操作',405);
      if(restoreInFlight)throw fail('工作区正在恢复，请稍后再研判',409);
      const b=await readBody(req);
      if(b.action==='configure'){authorize(req,true);return json(res,riskAgent.configure(b.workspaceId,b));}
      if(b.action==='run')return json(res,{job:riskAgent.start(b)},202);
      if(b.action==='cancel')return json(res,riskAgent.cancel(b.workspaceId));
      throw fail('风险研判操作无效');
    }
    if(p==='/api/v2/event-push'){
      authorize(req);
      if(req.method==='GET')return json(res,eventBridge.status(w));
      if(req.method!=='POST')throw fail('不支持的事件接入操作',405);
      authorize(req,true);if(restoreInFlight)throw fail('工作区正在恢复',409);
      const b=await readBody(req);return json(res,eventBridge.configure(b.workspaceId,b));
    }
    if(p==='/api/v2/agent-feed') {
      authorize(req);
      if(req.method!=='GET')throw fail('增量资料入口只支持读取',405);
      return json(res,agentMonitor.feed(w,{after:Number(url.searchParams.get('after')||0),generation:url.searchParams.get('generation')||'',limit:Number(url.searchParams.get('limit')||30)}));
    }
    if(p==='/api/v2/agent-analysis') {
      authorize(req);
      if(req.method!=='POST')throw fail('分析回执只支持提交',405);
      if(restoreInFlight)throw fail('正在恢复工作区，请稍后重试',409);
      const b=await readBody(req);return json(res,agentMonitor.completeAnalysis(b.workspaceId,b));
    }
    if(p==='/api/v2/agent-advice') {
      authorize(req);
      if(req.method!=='POST')throw fail('建议入口只支持提交建议',405);
      if(restoreInFlight)throw fail('正在恢复工作区，请稍后重试',409);
      const b=await readBody(req);return json(res,agentMonitor.suggest(b.workspaceId,b));
    }
    if(p==='/api/v2/desktop-notifications'){
      authorize(req,true);
      if(req.method==='GET')return json(res,{notices:desktopNotifications.list(w),status:store.getSetting('followupNotificationStatus:'+w)});
      if(req.method!=='POST')throw fail('不支持的电脑通知操作',405);
      if(req.headers.origin!==origin&&req.headers.origin!=='http://localhost:'+port)throw fail('电脑通知须从工作台或桌面客户端领取',403);
      const body=await readBody(req);if(restoreInFlight?.workspaceId&&restoreInFlight.workspaceId===body.workspaceId)throw fail('工作区正在恢复，通知已暂停',409);
      return json(res,desktopNotifications.update(body));
    }
    if(p==='/api/v2/meeting-workflows'&&req.method==='GET'){
      authorize(req,true);const state=store.load(w);
      return json(res,{mode:meetingWorkflow.mode,archiveReady:!!(meetingOptions.deliverables||meetingOptions.deliverablePort),items:state.sources.filter(s=>s.meetingWorkflow&&!s.archived).map(s=>domain.meetingWorkflowProjection(state,s.id))});
    }
    if(p==='/api/v2/meeting-calendars'&&req.method==='GET'){
      authorize(req,true);store.load(w);return json(res,{calendars:await meetingWorkflow.client.calendars({signal:AbortSignal.timeout(20000)}),mode:meetingWorkflow.mode,archiveReady:!!(meetingOptions.deliverables||meetingOptions.deliverablePort)});
    }
    if(p==='/api/v2/meeting-file'&&req.method==='GET'){
      const {source,state}=meetingWorkflow.record(w,url.searchParams.get('sourceId'),true);
      const file=meetingFiles(source).find(f=>f.id===url.searchParams.get('fileId'));
      if(!file)throw fail('当前会议没有此文件',404);
      const filename=await meetingMaterials.resolve(file,{state});
      res.writeHead(200,{...headers,'Content-Type':'application/octet-stream','Content-Disposition':"attachment; filename*=UTF-8''"+encodeURIComponent(file.name)});return res.end(readFileSync(filename));
    }
    if(p==='/api/v2/followups'){
      if(req.method==='GET')return json(res,followups.list(w));
      if(req.method!=='POST')throw fail('不支持的跟进请求',405);
      authorize(req,true);
      if(req.headers.origin!==origin&&req.headers.origin!=='http://localhost:'+port)throw fail('跟进操作须从工作台提交',403);
      const body=await readBody(req);if(restoreInFlight?.workspaceId&&restoreInFlight.workspaceId===body.workspaceId)throw fail('工作区正在恢复，请稍后重试',409);
      return json(res,followups.operate(body));
    }
    if(p==='/api/v2/deliverable-comments'){
      if(req.method!=='POST')throw fail('不支持的评论请求',405);
      authorize(req,true);if(req.headers.origin!==origin&&req.headers.origin!=='http://localhost:'+port)throw fail('评论须从工作台核对后提交',403);
      const body=await readBody(req);if(!['inspect','prepare','send','reconcile'].includes(body.action))throw fail('不支持的评论操作');
      if(restoreInFlight?.workspaceId===body.workspaceId)throw fail('工作区正在恢复，请稍后再评论',409);
      if(testMode&&!options.commentOptions?.adapter)throw fail('隔离工作区未配置模拟评论适配器，不会调用真实服务',403);
      return json(res,await comments[body.action](body));
    }
    if(p==='/api/v2/reminders'){
      if(req.method!=='POST')throw fail('不支持的提醒请求',405);
      authorize(req,true);if(req.headers.origin!==origin&&req.headers.origin!=='http://localhost:'+port)throw fail('提醒须从工作台审核提交',403);
      const body=await readBody(req);
      if(restoreInFlight?.workspaceId&&restoreInFlight.workspaceId===body.workspaceId)throw fail('工作区正在恢复，请稍后核对提醒',409);
      if(!['propose','suggest','prepare','send','reconcile'].includes(body.action))throw fail('不支持的提醒操作');
      if(testMode&&body.action==='send'&&!options.feedbackOptions?.taskClient)throw fail('隔离工作区未接入模拟发送器，不会发送真实提醒',403);
      return json(res,await reminders[body.action](body));
    }
    if(p==='/api/v2/result-review'){
      if(req.method!=='POST')throw fail('不支持的成果审核请求',405);
      const body=await readBody(req);
      authorize(req,body.action!=='prepare');if(body.action!=='prepare'&&req.headers.origin!==origin&&req.headers.origin!=='http://localhost:'+port)throw fail('成果验收须从工作台提交',403);
      if(restoreInFlight?.workspaceId&&restoreInFlight.workspaceId===body.workspaceId)throw fail('工作区正在恢复，请稍后重新核对成果',409);
      if(body.action==='prepare')return json(res,await resultReview.prepare(body));
      if(body.action==='decide')return json(res,await resultReview.decide(body));
      throw fail('不支持的成果审核操作');
    }
    if(p==='/api/v2/meetings'&&req.method==='GET')return json(res,meetingIntake.status(w));
    if(p==='/api/v2/comment-feedback'){
      if(req.method==='GET')return json(res,feedbackIntake.status(w));
      if(req.method!=='POST')throw fail('不支持的反馈请求',405);
      authorize(req,true);
      if(req.headers.origin!==origin&&req.headers.origin!=='http://localhost:'+port)throw fail('反馈处理须从工作台提交',403);
      const body=await readBody(req),id=body.workspaceId;
      if(restoreInFlight?.workspaceId&&restoreInFlight.workspaceId===id)throw fail('工作区正在恢复，请稍后重新打开事项',409);
      if(body.action?.startsWith('meeting-workflow-')){
        if(restoreInFlight?.workspaceId&&restoreInFlight.workspaceId===id)throw fail('工作区正在恢复，请完成后重新打开会议',409);
        return json(res,await meetingWorkflowAction(meetingWorkflow,body));
      }
      if(body.action==='intake-submit')return json(res,materialIntake.submit(body));
      if(body.action==='intake-status')return json(res,materialIntake.status(body));
      if(body.action==='intake-retry-collected')return json(res,materialIntake.retryCollected(body));
      if(body.action==='intake-retry')return json(res,materialIntake.retry(body));
      if(body.action==='intake-cancel')return json(res,materialIntake.cancel(body));
      if(body.action==='intake-review')return json(res,materialIntake.review(body));
      if(body.action==='intake-review-risk')return json(res,materialIntake.reviewRisk(body));
      if(body.action==='intake-undo')return json(res,materialIntake.undo(body));
      if(body.action==='case-chat-bind')return json(res,await caseChat.bind(body));
      if(body.action==='case-chat-search')return json(res,await caseChat.search(body));
      if(body.action==='case-chat-read')return json(res,await caseChat.read(body));
      if(body.action==='case-chat-suggest')return json(res,await caseChat.suggest(body));
      if(body.action==='case-chat-configure')return json(res,caseChat.configure(body));
      if(body.action==='case-file-read')return json(res,await caseChat.readFile(body));
      if(body.action==='approval-search')return json(res,await approvalEvidence.search(body));
      if(body.action==='approval-preview')return json(res,await approvalEvidence.preview(body));
      if(body.action==='approval-link')return json(res,await approvalEvidence.link(body));
      if(body.action==='approval-refresh')return json(res,await approvalEvidence.refresh(body));
      if(body.action==='meeting-scan')return json(res,await meetingIntake.scan(body));
      if(body.action==='meeting-configure')return json(res,meetingIntake.configure(body));
      if(body.action==='meeting-suggest')return json(res,await meetingIntake.suggest(body));
      if(body.action==='meeting-confirm')return json(res,meetingIntake.confirm(body));
      if(body.action==='meeting-minutes')return json(res,await meetingIntake.readMinutes(body));
      if(body.action==='task-scan')return json(res,await taskContext.scan(body));
      if(body.action==='task-suggest')return json(res,await taskContext.suggest(body));
      if(body.action==='task-associate')return json(res,taskContext.associate(body));
      if(body.action==='task-preview')return json(res,await taskBindings.preview(body));
      if(body.action==='task-link')return json(res,await taskBindings.link(body));
      if(body.action==='task-attachment')return json(res,await taskBindings.attachment(body));
      if(body.action==='configure')return json(res,feedbackIntake.configure(id,body));
      if(body.action==='collect')return json(res,await feedbackIntake.poll(id));
      if(body.action==='retry')return json(res,feedbackIntake.retry(id,body.sourceId));
      if(body.action==='review')return json(res,feedbackIntake.review(id,body.sourceId,body.contentVersion));
      throw fail('不支持的反馈处理操作');
    }
    if(p==='/api/v2/feishu-sync') {
      if(req.method==='GET')return json(res,feishuSync.status(w));
      if(req.method!=='POST')throw fail('不支持的同步请求',405);
      authorize(req,true);
      if(req.headers.origin!==origin&&req.headers.origin!=='http://localhost:'+port)throw fail('飞书同步操作须由工作台界面提交',403);
      const body=await readBody(req),id=body.workspaceId;
      if(typeof body.requestId!=='string'||!body.requestId||body.requestId.length>160)throw fail('同步请求缺少有效标识');
      if(body.action==='configure')return json(res,feishuSync.configure(id,body.config||{}));
      if(body.action==='poll')return json(res,await feishuSync.poll(id));
      if(body.action==='prepare')return json(res,await feishuSync.prepare(id,body));
      if(body.action==='adopt')return json(res,await feishuSync.adopt(id,body));
      if(body.action==='approve')return json(res,await feishuSync.approve(id,body));
      if(body.action==='reject')return json(res,feishuSync.reject(id,body.runId));
      if(body.action==='reconcile')return json(res,await feishuSync.reconcile(id,body.runId));
      if(body.action==='resolve')return json(res,await feishuSync.resolve(id,body));
      throw fail('不支持的同步操作');
    }
    if(p.startsWith('/api/v2/codex/')) {
      authorize(req,true);
      const b=req.method==='POST'?await readBody(req):undefined;
      const extra=await assistantRoute({assistant,method:req.method,pathname:p,workspaceId:b?.workspaceId||w,body:b,searchParams:url.searchParams});
      if(extra)return json(res,extra);
      if(req.method==='GET'&&p==='/api/v2/codex/status')return json(res,await assistant.status());
      if(req.method==='GET'&&p==='/api/v2/codex/jobs')return json(res,{jobs:assistant.list(w)});
      const jobRoute=/^\/api\/v2\/codex\/jobs\/([A-Za-z0-9-]+)(\/cancel)?$/.exec(p);
      if(req.method==='GET'&&jobRoute&&!jobRoute[2])return json(res,{job:assistant.get(jobRoute[1],w)});
      if(req.method==='POST') {
        if(p==='/api/v2/codex/jobs')return json(res,{job:await assistant.start(b)},202);
        if(jobRoute&&jobRoute[2])return json(res,{job:assistant.cancel(jobRoute[1],b.workspaceId)});
      }
      throw fail('助手接口不存在',404);
    }
    if(req.method==='GET'&&(p==='/api/v2/status'||p==='/api/local-status')) {
      return json(res,{application:'pm-workbench',version:2,release,mode:'local-only',testMode:!!testMode,ready:true,csrfToken:token,workspaces:store.list(),dataDir,backupSettings:store.getSetting('backupSettings'),lastRestore:store.getSetting('lastRestore')});
    }
    if(req.method==='GET'&&p==='/api/v2/workspaces')return json(res,{workspaces:store.list()});
    if(req.method==='GET'&&p==='/api/v2/snapshot'){
      const state=store.load(w),project=url.searchParams.get('projectId'),objectId=url.searchParams.get('objectId');
      if(url.searchParams.get('projection')==='pet')return json(res,petSnapshot(state,followups.list(w).allAttention.flatMap(item=>item.followup?[item.followup]:[])));
      if(project&&!state.projects.some(x=>x.id===project))throw fail('当前工作区没有该项目',404);
      if(objectId&&!domain.lookupV2(state,objectId))throw fail('当前工作区没有该对象',404);
      // CLI optional filters include a versioned focused view plus the complete workspace for reference integrity.
      if(project||objectId) {
        const ids=new Set(objectId?[objectId]:kinds.flatMap(k=>state[k].filter(x=>x.id===project||x.projectIds?.includes(project)).map(x=>x.id)));
        const edges=domain.graphEdges(state).filter(e=>ids.has(e.fromId)||ids.has(e.toId));
        for(const e of edges){ids.add(e.fromId);ids.add(e.toId);}
        const records=kinds.flatMap(kind=>state[kind].filter(x=>ids.has(x.id)).map(record=>({kind,record})));
        for(const {record} of records)for(const id of record.sourceIds||[])ids.add(id);
        return json(res,{workspaceId:w,revision:state.revision,records,edges,sources:state.sources.filter(x=>ids.has(x.id)),state});
      }
      return json(res,state);
    }
    if(req.method==='GET'&&p==='/api/v2/groups'){
      const state=store.load(w),status=url.searchParams.get('status'),id=url.searchParams.get('id');
      return json(res,{workspaceId:w,revision:state.revision,groups:state.changeGroups.filter(g=>(!status||g.status===status)&&(!id||g.id===id))});
    }
    if(req.method==='GET'&&p==='/api/v2/audit')return json(res,{workspaceId:w,audit:store.load(w).audit});
    if(req.method==='GET'&&p==='/api/v2/assistant'){
      const s=store.load(w),pid=url.searchParams.get('projectId')||undefined;
      if(pid&&!s.projects.some(x=>x.id===pid))throw fail('项目不属于当前工作区');
      return json(res,{answer:domain.legacyAnswerMock(s,url.searchParams.get('q')||'今天需要推动什么',pid),mode:'本地确定性规则'});
    }
    if(req.method==='GET'&&p==='/api/v2/backups')return json(res,{backups:store.backups(),settings:store.getSetting('backupSettings'),lastRestore:store.getSetting('lastRestore')});
    if(req.method==='GET'&&p.startsWith('/api/v2/backups/')){
      const {bytes}=store.backupFile(p.split('/').at(-1));
      res.writeHead(200,{...headers,'Content-Type':'application/json','Content-Disposition':'attachment; filename="workbench-backup.json"'});return res.end(bytes);
    }
    if(req.method==='GET'&&p.startsWith('/api/v2/attachments/')){
      const a=store.attachment(w,p.split('/').at(-1));
      const safeInline=/^(application\/pdf|image\/(png|jpeg|gif|webp)|text\/plain)$/.test(a.mime);
      res.writeHead(200,{...headers,'Content-Type':a.mime,'Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'",'Content-Disposition':(safeInline?'inline':'attachment')+"; filename*=UTF-8''"+encodeURIComponent(a.name)});
      return res.end(a.bytes);
    }
    if(req.method==='POST'){
      authorize(req,!['/api/v2/validate','/api/v2/drafts','/api/v2/document-read'].includes(p));
      const b=await readBody(req);
      if(p!=='/api/v2/restore'&&restoreInFlight?.workspaceId&&restoreInFlight.workspaceId===b.workspaceId)throw fail('工作区正在恢复，请稍后重试',409);
      if(p==='/api/v2/document-read')return json(res,await documentReader.read(b));
      if(p==='/api/v2/validate'){
        const s=store.load(b.workspaceId),draft=b.draft||b;
        const errors=domain.validateDraft(s,draft);
        return json(res,{valid:!errors.length,errors,workspaceId:s.workspaceId,revision:s.revision},errors.length?422:200);
      }
      if(p==='/api/v2/drafts'){
        const draft=b.draft||b;
        const result=store.command({type:'submitDraft',workspaceId:draft.workspaceId,draft});
        return json(res,{group:result.group,groupId:result.group.id,revision:result.state.revision,reviewUrl:origin+'/?workspaceId='+encodeURIComponent(draft.workspaceId)+'&view=review&groupId='+encodeURIComponent(result.group.id)});
      }
      if(p==='/api/v2/command'){
        if(['review','editDraft','undo'].includes(b.type)){
          const state=store.load(b.workspaceId),audit=b.type==='undo'&&b.auditId?state.audit.find(row=>row.id===b.auditId):null;
          const groupId=b.groupId||audit?.groupId,group=groupId?state.changeGroups.find(row=>row.id===groupId):null;
          const source=state.sources.find(s=>s.meetingWorkflow&&(groupId&&s.meetingWorkflow.preview?.groupId===groupId||audit?.objectId===s.id||group?.operations.some(op=>op.kind==='sources'&&op.targetId===s.id&&Object.hasOwn(op.after,'meetingApprovalHash'))));
          if(source){
            if(b.type!=='review')throw fail('会议草稿请在会议面板重新准备或审阅，不能改写执行记录',409);
            if(!source.meetingWorkflow.preview||source.meetingWorkflow.preview.groupId!==b.groupId)throw fail('会议审核已更新，请重新核对当前预览',409);
            if(restoreInFlight?.workspaceId&&restoreInFlight.workspaceId===b.workspaceId)throw fail('工作区正在恢复，请稍后核对会议',409);
            return json(res,await meetingWorkflow.review({workspaceId:b.workspaceId,sourceId:source.id,fingerprint:source.meetingWorkflow.preview.fingerprint,decision:b.decision}));
          }
        }
        if(b.type==='createWorkspace'){
          if(typeof b.name!=='string'||!b.name.trim()||b.name.length>100)throw fail('请输入 1–100 字的工作区名称');
          if(typeof b.requestId!=='string'||!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(b.requestId))throw fail('请提供工作区创建请求 ID');
          const fingerprint=hash({name:b.name.trim(),type:b.workspaceType}),receiptKey='create-workspace:'+b.requestId;
          const state=store.transaction(()=>{
            const receipt=store.getSetting(receiptKey);
            if(receipt){if(receipt.fingerprint!==fingerprint)throw fail('创建请求标识已用于不同内容',409);return store.load(receipt.workspaceId);}
            const type=b.workspaceType==='demo'?'demo':'official',id='workspace-'+randomUUID();
            const created=type==='demo'?domain.demoState(id):domain.emptyState(id,b.name.trim(),type);
            created.workspaceName=b.name.trim();store.insert(created);store.setSetting(receiptKey,{fingerprint,workspaceId:id});return created;
          });
          return json(res,{state,workspaces:store.list()});
        }
        try {return json(res,store.command(b));}
        catch(e){
          if(b.type==='review'&&e.status===409&&e.errors?.length){
            store.transaction(()=>{const state=store.load(b.workspaceId),g=state.changeGroups.find(x=>x.id===b.groupId);if(g&&['pending','partial','conflict'].includes(g.status)){g.status='conflict';g.conflicts=e.errors;state.revision++;store.save(state,state.revision-1);e.state=state;}});
          }
          throw e;
        }
      }
      if(p==='/api/v2/attachments')return json(res,{attachment:store.attach(w||b.workspaceId,b)});
      if(p==='/api/v2/backup')return json(res,await store.createBackup(b.workspaceId));
      if(p==='/api/v2/backup-settings'){
        if(typeof b.enabled!=='boolean'||!Number.isFinite(b.intervalHours)||b.intervalHours<1||b.intervalHours>720||!Number.isInteger(b.retain)||b.retain<1||b.retain>100)throw fail('周期为 1–720 小时，保留 1–100 份');
        const settings={...store.getSetting('backupSettings'),enabled:b.enabled,intervalHours:b.intervalHours,retain:b.retain};store.setSetting('backupSettings',settings);return json(res,{settings});
      }
      if(p==='/api/v2/restore/preview')return json(res,store.preview(b.backup));
      if(p==='/api/v2/restore')return json(res,await restoreWorkspace(b));
      if(p==='/api/v2/analyze'){
        let state=store.load(b.workspaceId);
        if(b.projectIds?.some(id=>!state.projects.some(p=>p.id===id)))throw fail('来源项目不属于当前工作区');
        const source=domain.legacyPrepareSource(state,b);
        const existing=state.changeGroups.find(g=>g.idempotencyKey==='rules-'+source.id);
        if(existing)return json(res,{state,group:existing,mode:'本地确定性规则',reused:true});
        if(!state.sources.some(x=>x.id===source.id)){
          const {id,...after}=source;
          state=store.command({workspaceId:b.workspaceId,type:'manual',kind:'sources',targetId:id,action:'create',before:{},after,requestId:'source-'+id}).state;
        }
        const candidates=domain.legacyAnalyzeMock(state,source);
        const operations=candidates.map(c=>{
          const target=state[c.kind].find(x=>x.id===c.targetId);
          const value=c.field==='confirmed'?c.value==='true':c.value;
          return {id:c.id,kind:c.kind,targetId:c.targetId,action:target?'update':'create',before:target?{[c.field]:target[c.field]??null}:{},after:target?{[c.field]:value}:{title:c.value,projectIds:c.projectIds,sourceIds:[source.id],confirmed:false},reason:c.evidence||'本地确定性规则根据原文提出，需逐项核实',sourceIds:[source.id],classification:'suggestion',missingInfo:c.category==='缺失信息'?[c.value]:[]};
        });
        let group;
        if(operations.length){const result=store.command({type:'submitDraft',workspaceId:b.workspaceId,draft:{workspaceId:b.workspaceId,request:b.text,purpose:'本地规则整理原文，待人工确认',creator:'本地规则',baseRevision:state.revision,idempotencyKey:'rules-'+source.id,operations}});state=result.state;group=result.group;}
        return json(res,{state,group,mode:'本地确定性规则'});
      }
      throw fail('接口不存在',404);
    }
    if(req.method!=='GET')throw fail('不支持的请求方法',405);
    if(p.startsWith('/api/'))throw fail('旧版接口已停用，请使用带工作区的本地接口',404);
    const assets=testMode&&options.assetsDir?path.resolve(options.assetsDir):path.join(root,'dist-local/client'),file=p==='/'?path.join(assets,'index.html'):path.join(assets,p.slice(1));
    if(!file.startsWith(assets+path.sep)||!existsSync(file)||!statSync(file).isFile())throw fail('页面不存在',404);
    const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml'}[path.extname(file)]||'application/octet-stream';
    res.writeHead(200,{...headers,'Content-Type':mime});res.end(readFileSync(file));
  }
  const server=createServer((req,res)=>handle(req,res).catch(e=>{
    if(!res.headersSent)json(res,{error:e.message,errors:e.errors||[],...(e.state?{state:e.state}:{})},e.status||500);
    else res.end();
  }));
  server.requestTimeout=30000;server.headersTimeout=10000;
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);}).catch(e=>{store.close();throw Error(e.code==='EADDRINUSE'?port+' 端口已被其他程序占用；请关闭旧工作台或使用隔离测试端口。':e.message);});
  const periodic=setInterval(()=>void store.periodic(),60000);periodic.unref();
  feishuSync.start();
  materialIntake.start();
  feedbackIntake.start();
  taskContext.start();
  meetingIntake.start();
  caseChat.start();
  projectChats.start();
  agentMonitor.start();
  workItems.start();core.start();
  riskAgent.listen();
  eventBridge.start();
  meetingWorkflow.start();
  if(Object.keys(notifications).length)notificationPump.start();
  const close=async()=>{workItems.close();clearInterval(periodic);await Promise.allSettled([...dataPublication.jobs.values()]);await Promise.all([coreInbox.close(),core.close(),eventBridge.close(),riskAgent.close(),projectChats.close(),agentMonitor.close(),comments.close(),assistant.close(),feishuSync.close(),documentReader.close(),feedbackIntake.close(),resultReview.close(),reminders.close(),taskContext.close(),meetingIntake.close(),caseChat.close(),approvalEvidence.close(),materialIntake.close(),meetingWorkflow.close(),notificationPump.close()]);return new Promise(resolve=>{server.close(()=>{store.directDmIsolation?.close();store.close();resolve();});server.closeIdleConnections();});};
  console.log('本地工作台 v2 已就绪：'+origin+'；SQLite：'+store.file);
  return {server,store,close,origin,token,projectChats,dataPublication,comments,assistant,feishuSync,feedbackIntake,meetingIntake,caseChat,approvalEvidence,materialIntake,followups,reminders,meetingWorkflow,meetingMaterials,desktopNotifications,notificationPump,runtimeSettings,agentMonitor,riskAgent,eventBridge,core,coreInbox};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const app=await startServer().catch(e=>{console.error('启动失败：'+e.message);process.exit(1);});
  for(const event of ['SIGTERM','SIGINT'])process.once(event,()=>void app.close().then(()=>process.exit(0)));
}
