import {mkdirSync,readFileSync,writeFileSync,existsSync,chmodSync} from 'node:fs';
import {createServer} from 'node:http';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import {startServer} from '../../../scripts/local-http.mjs';
import {fixtureState} from '../../../scripts/s1p1-fixtures.mjs';
import {fakeCoreCodex} from '../../../scripts/core-fixtures.mjs';
import * as d from '../../../dist-local/domain.mjs';
const folder=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),root=path.resolve(folder,'../..');
const port=5188,cardPort=5189,cardOrigin='http://127.0.0.1:'+cardPort,dataDir=path.join(folder,'data');mkdirSync(dataDir,{recursive:true});
const secret=randomUUID(),main='uat-prep1',smoke='uat-prep1-smoke',allowed=[main,smoke];
const deny=path.join(folder,'runtime/blocked-external');writeFileSync(deny,'#!/bin/sh\nprintf \'%s\\n\' \'{"ok":false,"error":{"type":"validation","message":"UAT-PREP1 隔离预览禁止真实外部调用"}}\'\nexit 2\n');chmodSync(deny,0o700);
process.env.PM_MEEGLE_BIN=deny;process.env.PM_MEEGLE_CLI=deny;process.env.PM_LARK_CLI=deny;process.env.PM_CODEX_BIN=deny;
const incoming=new Map(),outgoing=new Map(),transportLog=[];let clock='2026-10-14T00:59:00Z';
const identity={scope:'uat-synthetic/app',userId:'ou_uat_self',appId:'app',tenantKey:'uat-synthetic',name:'合成本人'};
const client={simulation:true,identity:async()=>identity,run:async args=>{
 if(args[0]==='api'&&args[1]==='GET'){const p=JSON.parse(args[args.indexOf('--params')+1]);return {items:(p.message_ids||[]).map(id=>incoming.get(id)?.raw).filter(Boolean)};}
 if(args[1]==='+messages-mget')return {messages:[incoming.get(args[args.indexOf('--message-ids')+1])?.readable||outgoing.get(args[args.indexOf('--message-ids')+1])].filter(Boolean)};
 if(args[1]==='+messages-send'){const id='om_uat_mock_'+randomUUID().replaceAll('-',''),text=args[args.indexOf('--text')+1];outgoing.set(id,{message_id:id,msg_type:'text',content:text,sender:{id:identity.userId}});transportLog.push({kind:'simulated-message',id,at:new Date().toISOString()});return {message_id:id};}
 throw Object.assign(Error('本预览不调用真实飞书服务'),{definitelyNotSent:true,status:403});
}};
const notification=name=>({identity:async()=>({channel:name,selfId:identity.userId}),send:async x=>{transportLog.push({kind:'simulated-notice',channel:name,at:clock,title:x.title});return {id:'mock-'+x.key,selfId:x.selfId,basis:x.basis};},readback:async r=>({...r,delivery:name==='desktop'?'submitted':'message_readback_verified'})});
const fake=fakeCoreCodex(path.join(folder,'runtime'));
// Slow the first simulated stage enough for a person to exercise Cancel.
writeFileSync(fake,readFileSync(fake,'utf8').replace("if(text.includes('延迟'))await new Promise(r=>setTimeout(r,1200));","await new Promise(r=>setTimeout(r,700));"));
const analyse=async(context,{signal})=>{
 await delay(700,undefined,{signal});
 if(context.request.includes('后段失败'))throw Object.assign(Error('合成场景：后段准备超时，前段保存保留'),{status:504});
 const p=context.evidence.find(e=>e.sourceId==='uat-proof')||context.evidence.find(e=>e.text),id=p.citationId;
 const work=context.request.includes('依赖');
 return {dependencies:work?[{dependency:{id:'uat-edge',upstreamId:'p1-action',downstreamId:'p1-risk',input:'合成测试输入',affectedWork:'评审前测试',impact:'缺少合成测试结论将影响评审判断',proof:[id],resolved:false},readStatus:'verified',planConfirmed:true,planProof:[id],duration:{min:2,max:6,unit:'hours',remaining:true,includesPreparation:true,includesRetest:false,conditions:'包含准备、不包含额外复测',proof:[id]},sharedProof:[id],availableHours:1,windowProof:[id],calendarSource:'合成证据明确可用1小时',coordination:'impossible',coordinationProof:[id],knownByAffected:false,awarenessProof:[],arrangementDecided:false,closingWindow:false,closingProof:[],options:[]}]:[],deliveries:[],messages:[],citations:[{citationId:id,quote:p.text,interpretation:'固定合成模型输出，只验证原产品处理链'}]};
};
const app=await startServer({port,dataDir,testMode:true,legacy:null,assistantOptions:{codexBin:fake,timeoutMs:15000,retrievalOptions:{library:null}},coreWorkOptions:{analyse},feedbackOptions:{taskClient:client},coreOptions:{client,mode:'simulation',clock:()=>Date.parse(clock),notifications:{desktop:notification('desktop'),feishu_self:notification('feishu_self')}},eventBridgeOptions:{client}});
// Only manual scenario buttons exercise the clock; there is no periodic notice or input retry.
clearInterval(app.core.timer);clearInterval(app.coreInbox.timer);
const cal={id:'uat-calendar',revision:1,source:'UAT-PREP1 合成日历：10月15日休息，14/16/17日工作，不代表实际公司排班',verifiedAt:'2026-10-14T00:00:00Z',from:'2026-10-14',through:'2026-10-18',synthetic:true,days:{'2026-10-14':true,'2026-10-15':false,'2026-10-16':true,'2026-10-17':true,'2026-10-18':false}};
function seed(id){
 const {s,ids}=fixtureState(id);s.workspaceName=id===main?'UAT-PREP1 · 合成验收（模拟模型与通道）':'UAT-PREP1 · 自检留档（非用户验收）';
 s.projects[0].title='合成样件评审项目';s.sources.find(r=>r.id===ids.action).title='01 统一输入／部分保存';s.sources.find(r=>r.id===ids.risk).title='04 依赖与评审影响';
 const row=(id,title,extra={})=>({id,title,projectIds:['p'],sourceIds:[],version:1,...extra});
 s.people=[row('uat-owner','合成报告责任人',{identityVerified:true,feishuUserId:'ou_uat_owner',feishuIdType:'open_id',feishuAppId:'app',feishuTenantKey:'uat-synthetic'})];
 s.flowNodes=[row('uat-node','合成评审节点',{nodeStatus:'进行中'})];s.deliverables=[row('uat-report','合成测试报告',{flowNodeIds:['uat-node'],reviewStatus:'未审核',deliveryReview:'未审核',submissionStatus:'已提交',workItemId:ids.action,ownerId:'uat-owner'})];
 s.sources.push(row('uat-proof','合成依赖与责任原文',{excerpt:'合成测试输入影响评审前测试；缺少测试结论将影响评审判断。剩余最短2小时、最长6小时，包含准备、不含额外复测，已共享。当前有效工作窗口只有1小时，已确认无法并行压缩。受影响人是否知晓风险影响尚未核实。合成测试报告已提交并关联合成评审节点，审核值仍为未审核；由合成报告责任人推动审核。',occurredAt:'2026-10-14T00:00:00Z'}));
 const action=s.sources.find(r=>r.id===ids.action);action.sourceIds.push('uat-proof');action.workItem.evidence.push({sourceId:'uat-proof',key:d.workSourceKey(s,s.sources.find(r=>r.id==='uat-proof')),fingerprint:d.workSourceFingerprint(s,s.sources.find(r=>r.id==='uat-proof'))});
 d.applyWorkItemFindings(s,[{id:'uat-closed',title:'02 已关闭事项／重开待审核',nature:'action',summary:'已关闭的合成测试事项',nextStep:'需要审核是否重新打开',urgency:'normal',sourceIds:['uat-proof'],association:{kind:'project',id:'p',reason:'合成项目',confirmed:true}}],'2026-10-13T02:00:00Z');
 const closed=s.sources.find(r=>r.id==='uat-closed');d.ensureCore(closed).admission='managed';closed.workItem.p1={lifecycle:{state:'closed',owner:'manual',at:'2026-10-13T03:00:00Z',reason:'合成本人已关闭'}};
 const proof={sourceId:'uat-proof',fingerprint:d.coreProofFingerprint(s.sources.find(r=>r.id==='uat-proof')),quote:s.sources.find(r=>r.id==='uat-proof').excerpt};
 d.applyNeedAssessment(s,closed,{id:'uat-reopen-evidence',occurredAt:'2026-10-14T00:00:00Z',proof:[proof],needKey:'uat-reopen',description:'新证据表明仍有后续，待本人决定是否重开',actor:'self',actualAction:false,substantiveProgress:false,executableArrangement:false,currentHandled:false,noIntervention:false,goalSatisfied:false,remainingActions:['判断是否重开'],priority:'P2',priorityReason:'合成待审',urgent:false,suggestP0:false,steps:[]},'2026-10-14T00:00:00Z');
 s.sources.push(row('uat-old-notice','合成原消息关联',{followupNotification:{core:true,workItemId:ids.action,channels:{feishu_self:{receipt:{id:'om_uat_root_'+id}}}}}));
 app.store.insert(s);app.core.configure({workspaceId:id,revision:0,calendar:cal});return ids;
}
for(const id of allowed)if(!app.store.list().some(w=>w.id===id))seed(id);
for(const id of ['official','demo']){const s=app.store.load(id);if(s.workspaceName==='正式工作区'||id==='demo'&&s.workspaceName!=='内置合成示例（非正式数据）'){s.workspaceName=id==='official'?'隔离空白工作区（非正式数据）':'内置合成示例（非正式数据）';s.workspaceType='demo';s.revision++;app.store.save(s,s.revision-1);}}
for(const w of app.store.list()){app.store.setSetting('coreAutomation:'+w.id,{revision:0,enabled:false,lastTick:'',error:''});}
app.runtimeSettings.update({revision:app.runtimeSettings.get().revision,chat:{model:'gpt-6-astra',effort:'max'},background:{model:'gpt-6-astra',effort:'max'}});
const api=async(endpoint,body)=>{const r=await fetch(app.origin+endpoint,{method:body?'POST':'GET',headers:{'X-Workbench-Token':app.token,'X-Workbench-Client':'ui',...(body?{'content-type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw Error(j.error);return j;};
const state=id=>app.store.load(id);
function view(id){const s=state(id),closed=s.sources.find(r=>r.id==='uat-closed'),c=app.core.view(id,'uat-closed');return {workspaceId:id,release:JSON.parse(readFileSync(path.join(root,'release.json'))),testMode:true,modelMode:'synthetic',transportMode:'simulation-only',clock,calendar:cal.source,productUrl:app.origin+'/?workspaceId='+id+'&view=attention',closure:{state:closed.workItem.p1.lifecycle.state,proposal:!!d.coreReopenProposal(s,closed),count:d.coreState(closed).cycle.count,notice:c.items[0].notice,receipts:c.notices.filter(n=>n.notice).map(n=>({id:n.id,kind:n.notice.kind,channels:Object.fromEntries(Object.entries(n.channels).map(([k,v])=>[k,v.stage]))}))},lastInput:s.sources.filter(r=>r.inputEnvelope?.origin==='feishu').at(-1)?.id||'',messageCalls:transportLog.length,realExternalCalls:0};}
async function waitJob(id,w){for(let i=0;i<160;i++){const j=app.assistant.get(id,w);if(j.status!=='running')return j;await delay(50);}throw Error('合成任务未在预期时间内完成');}
async function scenario(name,w){
 if(['before9','at9','restday','nextday'].includes(name)){clock={before9:'2026-10-14T00:59:00Z',at9:'2026-10-14T01:00:00Z',restday:'2026-10-15T01:00:00Z',nextday:'2026-10-16T01:00:00Z'}[name];await app.core.notify(w,'uat-closed');return view(w);}
 if(name==='budget-fail'){
  const budget=app.assistant.aiUsage.budgetStatus();app.assistant.aiUsage.configureBudget({revision:budget.revision,enabled:true,dailyTokens:10000});
  const message='om_uat_in_'+randomUUID().replaceAll('-',''),s=state(w),sourceId='source-'+message,text='已收到合成样件，等待完成验证。';
  const raw={message_id:message,chat_id:'oc_uat',parent_id:'om_uat_root_'+w,create_time:String(Date.parse('2026-10-14T02:00:00Z')),msg_type:'text',sender:{id:'ou_uat_colleague'},body:{content:JSON.stringify({text})}};incoming.set(message,{raw,readable:{...raw,content:text}});
  s.sources.push({id:sourceId,title:'03 合成同事原始输入',projectIds:['p'],sourceIds:[],version:1,excerpt:text,occurredAt:'2026-10-14T02:00:00Z',personalMessage:{scope:identity.scope,accountId:identity.userId,messageId:message,senderId:'ou_uat_colleague',chatId:'oc_uat'}});s.revision++;app.store.save(s,s.revision-1);
  const r=await app.coreInbox.receive({workspaceId:w,sourceId,identity,parentId:'om_uat_root_'+w,senderId:'ou_uat_colleague'});await waitJob(r.jobId,w);return {label:'合成同事预算失败',receipt:await api('/api/v2/core',{workspaceId:w,action:'input-receipt',sourceId}),originalPreserved:!!state(w).sources.find(r=>r.id===sourceId)?.excerpt};
 }
 if(name==='budget-resume'){
  const budget=app.assistant.aiUsage.budgetStatus();app.assistant.aiUsage.configureBudget({revision:budget.revision,enabled:false,dailyTokens:500000});app.coreInbox.reader={verifyMessage:async source=>incoming.get(source.personalMessage.messageId)?.raw||{message_id:source.personalMessage.messageId}};
  await app.coreInbox.resumeBudgetQueue(w);const source=state(w).sources.filter(r=>r.inputEnvelope?.origin==='feishu').at(-1);if(!source)throw Error('先运行一次合成同事失败场景');await waitJob(source.inputEnvelope.jobId,w);return {label:'原输入恢复处理',receipt:await api('/api/v2/core',{workspaceId:w,action:'input-receipt',sourceId:source.id})};
 }
 if(name==='prepare'){
  const s=state(w),source=s.sources.find(r=>r.id==='p1-action'),p=s.sources.find(r=>r.id==='uat-proof'),proof=[{sourceId:p.id,fingerprint:d.coreProofFingerprint(p),quote:p.excerpt}];
  const result=await api('/api/v2/core',{workspaceId:w,action:'delivery',sourceId:source.id,expectedVersion:source.version,context:{targetId:'uat-report',nodeId:'uat-node',ownerId:'uat-owner',providerId:'',fileOwnerId:'',teamOwnerId:'',verified:true,proof,requirement:'合成测试报告由责任人推动审核',requirementConflict:false,exceptionProof:[],templates:[],templateUncertain:false,materialSourceIds:['uat-proof'],missing:[],accessDenied:false,linked:true,submitted:true,reviewValue:'未审核'}});
  return {label:'资料与协作已准备，未批准或发送',messages:result.messages||result.items?.[0]?.core?.delivery?.messages||d.coreState(state(w).sources.find(r=>r.id==='p1-action')).delivery?.messages,externalMessages:transportLog.filter(l=>l.kind==='simulated-message').length};
 }
 throw Error('未知验收动作');
}
const card=createServer(async(req,res)=>{try{
 if(!['127.0.0.1:'+cardPort,'localhost:'+cardPort].includes(req.headers.host))throw Error('仅限本机访问');const u=new URL(req.url,cardOrigin),w=u.searchParams.get('workspaceId')||main;if(!allowed.includes(w))throw Error('不是本次合成工作区');
 if(req.method==='POST'){if(req.headers['x-uat-token']!==secret||req.headers.origin&&![cardOrigin,'http://localhost:'+cardPort].includes(req.headers.origin))throw Error('验收页面请求来源不符');let input='';for await(const part of req){input+=part;if(input.length>16000)throw Error('记录过长');}const b=JSON.parse(input||'{}');let result;
  if(u.pathname==='/scenario')result=await scenario(b.action,w);else if(u.pathname==='/acceptance'){writeFileSync(path.join(folder,w==='uat-prep1'?'用户验收记录.json':'evidence/smoke-acceptance.json'),JSON.stringify({recordedAt:new Date().toISOString(),userOperated:w===main,origin:w===main?'user-ui':'preparation-smoke',entries:b.entries},null,2));result={saved:true};}else throw Error('未知操作');res.setHeader('content-type','application/json');res.end(JSON.stringify(result));return;}
 if(u.pathname==='/acceptance'){const file=path.join(folder,w===main?'用户验收记录.json':'evidence/smoke-acceptance.json');res.setHeader('content-type','application/json');res.end(existsSync(file)?readFileSync(file):JSON.stringify({entries:[]}));return;}
 if(u.pathname==='/status'){res.setHeader('content-type','application/json');res.end(JSON.stringify(view(w)));return;}
 if(u.pathname==='/sample.png'){res.setHeader('content-type','image/png');res.setHeader('content-disposition',"attachment; filename=synthetic-feedback.png");res.end(readFileSync(path.join(folder,'samples/合成样件反馈.png')));return;}
 if(u.pathname!=='/')throw Error('页面不存在');res.setHeader('content-type','text/html; charset=utf-8');res.end(readFileSync(path.join(folder,'runtime/card.html'),'utf8').replaceAll('__WORKSPACE__',w).replaceAll('__PRODUCT__',app.origin).replace('__SECRET__',secret));
 }catch(e){res.statusCode=400;res.setHeader('content-type','application/json');res.end(JSON.stringify({error:e.message}));}});
await new Promise((resolve,reject)=>{card.on('error',reject);card.listen(cardPort,'127.0.0.1',resolve)});
writeFileSync(path.join(folder,'runtime.json'),JSON.stringify({pid:process.pid,startedAt:new Date().toISOString(),product:app.origin,card:cardOrigin,workspaceId:main,dataDir,release:JSON.parse(readFileSync(path.join(root,'release.json'))),sourceCommit:'9a10f212166fe6f6a2f495705aa682bd52b0b747',testMode:true,realExternalExecution:false,realModel:false,automaticNoticeTimer:false},null,2));
console.log('UAT-PREP1 ready '+cardOrigin+' product '+app.origin);
let stopping=false;async function close(){if(stopping)return;stopping=true;card.close();await app.close();process.exit(0);}process.on('SIGINT',close);process.on('SIGTERM',close);
