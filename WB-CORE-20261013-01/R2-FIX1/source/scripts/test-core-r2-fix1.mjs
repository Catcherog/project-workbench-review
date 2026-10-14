import assert from 'node:assert/strict';
import {mkdirSync,mkdtempSync,readFileSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import * as d from '../dist-local/domain.mjs';
import {LocalStore} from './local-store.mjs';
import {WorkItemCoreService} from './work-item-core-service.mjs';
import {fixtureState} from './s1p1-fixtures.mjs';
import {startCoreFixture} from './core-fixtures.mjs';

const output=path.resolve(process.env.PM_R2_OUTPUT||'output/r2-fix1');mkdirSync(output,{recursive:true});
const results=[];
async function test(id,name,fn){try{await fn();results.push({id,name,passed:true});console.log('PASS',id,name);}catch(error){results.push({id,name,passed:false,error:error.stack});console.log('FAIL',id,name,'\n'+error.stack);}}
async function until(fn){for(let i=0;i<250;i++){const v=await fn();if(v)return v;await delay(30);}throw Error('Expected product state not reached');}
const calendar={id:'r2-synthetic',revision:1,source:'合成明确日历：周三休息、周六工作；不代表公司排班',verifiedAt:'2026-10-13T00:00:00Z',from:'2026-10-13',through:'2026-10-18',synthetic:true,days:{'2026-10-13':true,'2026-10-14':false,'2026-10-15':true,'2026-10-16':true,'2026-10-17':true,'2026-10-18':false}};
function closedFixture(id){
  let {s,ids}=fixtureState(id);s.sources=s.sources.filter(r=>!r.workItem||r.id===ids.action);
  let row=s.sources.find(r=>r.id===ids.action),current=d.workItemState(s,row);
  s=d.applyWorkItemOperation(s,{workspaceId:id,sourceId:row.id,expectedVersion:row.version,expectedBasis:current.basis,requestId:id+'-close',action:'done',reason:'合成本人确认关闭'},'2026-10-12T03:00:00Z');
  row=s.sources.find(r=>r.id===ids.action);const proof=s.sources.find(r=>r.id==='src-action');proof.excerpt+=' 新的测试证据表明仍需核实后续。';proof.version++;
  d.applyNeedAssessment(s,row,{id:id+'-new-evidence',occurredAt:'2026-10-13T00:00:00Z',proof:[{sourceId:proof.id,fingerprint:d.coreProofFingerprint(proof),quote:proof.excerpt}],needKey:'r2-need',description:'核实新的合成测试证据',actor:'self',actualAction:false,substantiveProgress:false,executableArrangement:false,currentHandled:false,noIntervention:false,goalSatisfied:false,remainingActions:['核实测试证据'],priority:'P2',priorityReason:'合成后续',urgent:false,suggestP0:false,steps:[]},'2026-10-13T00:00:00Z');
  return {s,row,proof};
}
async function runtime(id,fn){
  const store=new LocalStore(mkdtempSync(path.join(output,'runtime-')),{testMode:true});await store.initialize(null);
  const {s,row}=closedFixture(id);store.insert(s);let time='2026-10-13T00:59:00Z';const sends=[];
  const adapter=name=>({identity:async()=>({channel:name,selfId:'ou_self'}),send:async value=>{sends.push({channel:name,at:time,...value});return {id:value.key,selfId:value.selfId,basis:value.basis};},readback:async value=>({...value,delivery:name==='desktop'?'submitted':'message_readback_verified'})});
  const service=new WorkItemCoreService({store,domain:d,clock:()=>Date.parse(time),testMode:true,client:{identity:async()=>({scope:'synthetic',userId:'ou_self'})},notifications:{desktop:adapter('desktop'),feishu_self:adapter('feishu_self')},refresh:async()=>{}});
  service.configure({workspaceId:id,revision:0,calendar});store.setSetting('coreAutomation:'+id,{revision:1,enabled:true,lastTick:'2026-10-12T01:00:00Z'});
  const read=()=>store.load(id).sources.find(r=>r.id===row.id);
  const modify=fn=>{const state=store.load(id);fn(state,state.sources.find(r=>r.id===row.id));state.revision++;store.save(state,state.revision-1);};
  try{await fn({store,service,read,modify,sends,setTime:v=>time=v,id,sourceId:row.id});}finally{await service.close();store.close();}
}

await test('B01-domain','closed + new evidence enters review on actual workday at 09:00; no business count',()=>{
  const {s,row}=closedFixture('b01-domain'),c=d.ensureCore(row);assert.ok(c.reopenProposal);
  assert.equal(d.coreNotice(s,row,calendar,'2026-10-13T00:59:00Z').eligible,false);
  const n=d.coreNotice(s,row,calendar,'2026-10-13T01:00:00Z');assert.equal(n.eligible,true);assert.equal(n.kind,'review');assert.equal(n.counts,false);
  d.countCoreNotice(row,n,n.at);assert.equal(d.coreNotice(s,row,calendar,n.at).eligible,false);
  assert.equal(d.coreNotice(s,row,calendar,'2026-10-14T01:00:00Z').eligible,false);
  assert.equal(d.coreNotice(s,row,calendar,'2026-10-15T01:00:00Z').kind,'review');assert.equal(row.workItem.p1.lifecycle.state,'closed');assert.equal(c.cycle.count,0);assert.equal(c.cycle.escalated,false);
});
await test('B01-runtime','tick/notify sends both simulated channels once per workday, survives recovery and keeps closure',()=>runtime('b01-runtime',async({service,read,sends,setTime,id,sourceId})=>{
  await service.tick();assert.equal(sends.length,0);setTime('2026-10-13T01:00:00Z');await service.tick();assert.equal(sends.length,2);
  await service.notify(id,sourceId);await service.tick();assert.equal(sends.length,2);
  setTime('2026-10-14T01:00:00Z');await service.tick();assert.equal(sends.length,2);
  setTime('2026-10-15T01:00:00Z');await service.tick();assert.equal(sends.length,4);
  setTime('2026-10-17T01:00:00Z');await service.tick();assert.equal(sends.length,6);
  const row=read();assert.equal(row.workItem.p1.lifecycle.state,'closed');assert.ok(row.workItem.core.reopenProposal);assert.equal(row.workItem.core.cycle.count,0);assert.equal(row.workItem.core.cycle.escalated,false);
  assert.equal(row.workItem.core.deliveryHistory.length,3);assert.ok(row.workItem.core.deliveryHistory.every(n=>!n.counted));
  const view=service.view(id,sourceId);assert.ok(view.items[0].core.reopenProposal);assert.ok(view.notices.every(n=>n.notice.kind==='review'&&Object.values(n.channels).every(c=>c.stage==='readback_verified')));
}));
await test('B01-pause','manual pause, explicit postponement, missing calendar and quiet hours retain review until allowed',()=>runtime('b01-pause',async({service,modify,read,sends,setTime,id,sourceId})=>{
  modify((s,row)=>d.applyCoreDecision(s,row,{action:'core-pause',manualResume:true},'2026-10-13T00:30:00Z',calendar));setTime('2026-10-13T01:00:00Z');await service.tick();assert.equal(sends.length,0);
  modify((s,row)=>d.applyCoreDecision(s,row,{action:'core-resume'},'2026-10-13T01:00:00Z',calendar));await service.tick();assert.equal(sends.length,2);
  modify((s,row)=>d.applyCoreDecision(s,row,{action:'core-pause',until:'2026-10-15T01:00:00Z'},'2026-10-13T02:00:00Z',calendar));setTime('2026-10-14T01:00:00Z');await service.tick();assert.equal(sends.length,2);
  setTime('2026-10-15T01:00:00Z');await service.tick();assert.equal(sends.length,4);assert.equal(read().workItem.core.pause,null);
  setTime('2026-10-16T10:01:00Z');await service.notify(id,sourceId);assert.equal(sends.length,4);setTime('2026-10-17T01:00:00Z');await service.tick();assert.equal(sends.length,6);
  const state=service.store.load(id);assert.equal(d.coreNotice(state,read(),undefined,'2026-10-16T01:00:00Z').calendarGap,true);
}));
await test('B01-closed-controls','closed review cannot revive old explicit checks, P0 urgency, deferred business slots or recovery reminders',()=>{
  for(const variant of ['explicit','urgent','focused','deferred','recovery']){
    const {s,row}=closedFixture('b01-'+variant),c=d.ensureCore(row);
    if(variant==='explicit')row.workItem.p1.check={state:'scheduled',effectiveAt:'2026-10-13T00:00:00Z',date:'2026-10-13',time:'08:00'};
    if(variant==='urgent'){c.assessment.urgent=true;c.assessment.suggestP0=true;}
    if(variant==='focused'){c.priority.base='P0';c.fullFocus=true;c.p0Event={key:'old',at:'2026-10-12T02:00:00Z'};}
    if(variant==='deferred')c.deferredNotification={slot:'old-regular',kind:'regular',cycleId:c.cycle.id,cycleEpoch:c.cycle.epoch,priorityEpoch:c.priority.epoch,until:'2026-10-13T01:00:00Z'};
    if(variant==='recovery')c.priority.base='P1';
    assert.equal(d.coreNotice(s,row,calendar,'2026-10-13T00:30:00Z',{recovery:true}).eligible,false,variant);
    const n=d.coreNotice(s,row,calendar,'2026-10-13T01:00:00Z',{recovery:true});assert.equal(n.kind,'review',variant);assert.equal(n.counts,false);assert.equal(n.checkKey,'');
    d.countCoreNotice(row,n,n.at);assert.equal(d.coreNotice(s,row,calendar,'2026-10-13T06:00:00Z',{recovery:true}).eligible,false,variant);
  }
});
await test('B01-invalid','no pending decision, withdrawn proof, completed decision and later manual close stay quiet',()=>{
  for(const mode of ['none','withdrawn','reopen','reclose','resolved']){
    let {s,row,proof}=closedFixture('b01-invalid-'+mode);
    if(mode==='none')row.workItem.core.reopenProposal=null;
    if(mode==='withdrawn'){proof.inputEnvelope={effectWithdrawn:true};d.invalidateCoreDerivations(s,row,'2026-10-13T00:30:00Z','合成证据撤回');}
    if(mode==='reopen'||mode==='reclose'){const c=d.workItemState(s,row);s=d.applyWorkItemOperation(s,{workspaceId:s.workspaceId,sourceId:row.id,expectedVersion:row.version,expectedBasis:c.basis,requestId:'decision',action:mode==='reopen'?'reopen':'done',addOwnEvidence:true,reason:'本人核对后的明确决定'},'2026-10-13T00:30:00Z');row=s.sources.find(r=>r.id===row.id);}
    if(mode==='resolved'){proof.excerpt+=' 新核验确认目标满足且无剩余动作。';proof.version++;d.applyNeedAssessment(s,row,{...row.workItem.core.assessment,id:'resolved',occurredAt:'2026-10-13T00:30:00Z',proof:[{sourceId:proof.id,fingerprint:d.coreProofFingerprint(proof),quote:proof.excerpt}],goalSatisfied:true,remainingActions:[],steps:[],noIntervention:true},'2026-10-13T00:30:00Z');}
    assert.ok(!row.workItem.core.reopenProposal,mode+' must retire the proposal');
    if(mode==='reopen')assert.notEqual(d.coreNotice(s,row,calendar,'2026-10-13T01:00:00Z').kind,'review');else assert.equal(d.coreNotice(s,row,calendar,'2026-10-13T01:00:00Z').eligible,false,mode);
  }
});
await test('B01-channel-race','evidence withdrawal between channel receipts stops the unsent channel and removes current review projection',()=>runtime('b01-channel-race',async({service,modify,sends,setTime,id,sourceId})=>{
  const send=service.notifications.desktop.send;service.notifications.desktop.send=async input=>{const receipt=await send(input);modify(s=>{s.sources.find(r=>r.id==='src-action').inputEnvelope={effectWithdrawn:true};});return receipt;};
  setTime('2026-10-13T01:00:00Z');await service.tick();assert.equal(sends.length,1);const view=service.view(id,sourceId);assert.equal(view.items[0].core.reopenProposal,null);assert.equal(view.notices[0].channels.feishu_self.stage,'stopped');assert.equal(view.items[0].notice.eligible,false);
}));
await test('B01-proposal-race','a replacement proposal during channel identity verification cannot send the previous decision text',()=>runtime('b01-proposal-race',async({service,modify,sends,setTime,id,sourceId})=>{
  const identity=service.notifications.desktop.identity;let changed=false;
  service.notifications.desktop.identity=async()=>{if(!changed){changed=true;modify((_s,row)=>{row.workItem.core.reopenProposal={...row.workItem.core.reopenProposal,id:'replacement-proposal',reason:'需要审核另一条新证据',at:'2026-10-13T01:00:00Z'};});}return identity();};
  setTime('2026-10-13T01:00:00Z');await service.notify(id,sourceId);assert.equal(sends.length,0);
  await service.notify(id,sourceId);assert.equal(sends.length,2);assert.ok(sends.every(s=>s.body.includes('另一条新证据')));
}));

async function inbox(fn,{workAnalyse,modelMode}={}){
  const identity={scope:'tenant/app',userId:'ou_self',appId:'app',tenantKey:'tenant'},incoming=new Map(),writes=[];
  const client={simulation:true,identity:async()=>identity,run:async args=>{
    if(args[0]==='api'&&args[1]==='GET'){const p=JSON.parse(args[args.indexOf('--params')+1]);return {items:p.message_ids.map(id=>incoming.get(id)?.raw).filter(Boolean)};}
    if(args[1]==='+messages-mget')return {messages:[incoming.get(args[args.indexOf('--message-ids')+1])?.readable].filter(Boolean)};
    writes.push(args);throw Error('R2 colleague test forbids external sends');
  }};
  const app=await startCoreFixture({client,workAnalyse});
  if(modelMode){const f=app.assistant.codexBin;writeFileSync(f,readFileSync(f,'utf8').replace('JSON.stringify(syntheticModel(text,context))',`JSON.stringify((()=>{const r=syntheticModel(text,context);r.coreInput.records=[];r.coreInput.ambiguities=${JSON.stringify(modelMode==='clarify'?['合成信息缺口：需要确认哪项测试结果']:[])};return r;})())`));}
  let s=app.state();
  if(workAnalyse){const row=s.sources.find(r=>r.id===app.ids.action),source=s.sources.find(r=>r.id==='src-action'),proof=[{sourceId:source.id,fingerprint:d.coreProofFingerprint(source),quote:source.excerpt}];d.saveDependencyWindow(s,row,{dependency:{id:'synthetic-existing-edge',upstreamId:app.ids.risk,downstreamId:row.id,input:'合成测试输入',affectedWork:'测试准备',impact:'合成评审',proof,resolved:false},readStatus:'partial',planConfirmed:false,planProof:[],duration:null,sharedProof:[],availableHours:null,windowProof:[],calendarSource:'合成未知窗口',coordination:'not-tried',coordinationProof:[],knownByAffected:false,awarenessProof:[],arrangementDecided:false,closingWindow:false,closingProof:[],options:[]},'2026-10-13T01:00:00Z');}
  s.sources.push({id:'old-reminder',title:'合成历史本人提醒',projectIds:['p'],sourceIds:[],version:1,followupNotification:{core:true,workItemId:app.ids.action,channels:{feishu_self:{receipt:{id:'om_prior'}}}}});s.revision++;app.store.save(s,s.revision-1);
  const control=app.agentMonitor.control(app.workspaceId);Object.assign(control,{enabled:true,startedAt:'2026-10-13T00:00:00Z',identity,eventPush:{enabled:true,revision:1}});app.agentMonitor.save(app.workspaceId,control);
  async function receive(id,text='已收到合成测试反馈，设为P1'){
    const raw={message_id:id,chat_id:'oc_test',parent_id:'om_prior',create_time:String(Date.parse('2026-10-13T02:00:00Z')),msg_type:'text',sender:{id:'ou_colleague'},body:{content:JSON.stringify({text})}};
    incoming.set(id,{raw,readable:{...raw,content:text}});await app.eventBridge.ingest(app.workspaceId,'im.message.receive_v1',{message_id:id,chat_id:'oc_test',chat_type:'group',sender_id:'ou_colleague',parent_id:'om_prior'});
    return until(()=>app.state().sources.find(r=>r.personalMessage?.messageId===id&&r.inputEnvelope?.jobId));
  }
  const job=input=>app.assistant.get(app.state().sources.find(r=>r.id===input.id).inputEnvelope.jobId,app.workspaceId);
  const done=input=>until(()=>{const j=job(input);return j.status!=='running'&&j;});
  const receipt=input=>app.api('/api/v2/core',{workspaceId:app.workspaceId,action:'input-receipt',sourceId:input.id});
  const progress=()=>app.state().sources.find(r=>r.id===app.ids.action).workItem.p1?.progress||[];
  try{await fn({app,receive,job,done,receipt,progress,incoming,writes});assert.equal(writes.length,0,'No third-party or self outbound message');}finally{await app.close();}
}
await test('B02-budget','AI_BUDGET via event bridge reports waiting, then reuses original input and saves once',()=>inbox(async({app,receive,done,receipt,progress,incoming})=>{
  let b=app.assistant.aiUsage.budgetStatus();app.assistant.aiUsage.configureBudget({revision:b.revision,enabled:true,dailyTokens:10000});
  const input=await receive('om_budget'),j=await done(input);assert.equal(j.status,'failed');assert.equal(j.failureCode,'AI_BUDGET');
  let r=await receipt(input);assert.equal(r.status,'budget_wait');assert.equal(r.save.status,'not_saved');assert.equal(progress().length,0);assert.ok(app.state().sources.find(v=>v.id===input.id).excerpt);
  await app.coreInbox.resumeBudgetQueue(app.workspaceId);assert.equal((await receipt(input)).status,'budget_wait');
  b=app.assistant.aiUsage.budgetStatus();app.assistant.aiUsage.configureBudget({revision:b.revision,enabled:true,dailyTokens:500000});app.coreInbox.reader={verifyMessage:async()=>incoming.get('om_budget').raw};await app.coreInbox.resumeBudgetQueue(app.workspaceId);await done(input);
  r=await receipt(input);assert.equal(r.status,'saved');assert.equal(r.save.status,'saved');assert.equal(progress().length,1);await app.coreInbox.resumeBudgetQueue(app.workspaceId);assert.equal(progress().length,1);assert.equal(app.state().sources.filter(v=>v.personalMessage?.messageId==='om_budget').length,1);
}));
await test('B02-cancel','real cancellation before commit reports cancelled and preserves input without saved state',()=>inbox(async({app,receive,receipt,progress})=>{
  const input=await receive('om_cancel');assert.equal((await receipt(input)).status,'processing');await app.api('/api/v2/codex/jobs/'+input.inputEnvelope.jobId+'/cancel',{workspaceId:app.workspaceId});
  const r=await receipt(input);assert.equal(r.status,'cancelled');assert.equal(r.save.status,'not_saved');assert.equal(progress().length,0);assert.ok(app.state().sources.find(v=>v.id===input.id));
}));
await test('B02-clarify','completed understanding with an ambiguity is not a saved business update',()=>inbox(async({receive,done,receipt,progress})=>{
  const input=await receive('om_clarify');assert.equal((await done(input)).status,'completed');const r=await receipt(input);assert.equal(r.status,'clarify');assert.equal(r.save.status,'not_saved');assert.equal(progress().length,0);assert.ok(r.outcome.ambiguities.length);
},{modelMode:'clarify'}));
await test('B02-discuss','completed discussion with no business write stays discussion',()=>inbox(async({receive,done,receipt,progress})=>{
  const input=await receive('om_discuss');await done(input);const r=await receipt(input);assert.equal(r.status,'discuss');assert.equal(r.save.status,'not_saved');assert.equal(progress().length,0);
},{modelMode:'discuss'}));
for(const mode of ['fail','budget','cancel'])await test('B02-stage-'+mode,'persisted first stage survives later '+mode+' with separate unfinished preparation',async()=>{
  let release;
  await inbox(async({app,receive,done,receipt,progress})=>{
    const input=await receive('om_stage_'+mode);await until(()=>release);let r=await receipt(input);assert.equal(r.status,'saved');assert.equal(r.jobStatus,'running');assert.equal(r.preparation.status,'running');assert.equal(progress().length,1);
    if(mode==='cancel')await app.api('/api/v2/codex/jobs/'+input.inputEnvelope.jobId+'/cancel',{workspaceId:app.workspaceId});release();await done(input);
    r=await until(async()=>{const v=await receipt(input);return v.preparation?.status==='incomplete'&&v;});assert.equal(r.status,'saved');assert.equal(r.save.status,'saved');assert.equal(r.preparation.status,'incomplete');assert.ok(r.preparation.reason);assert.equal(progress().length,1);
    if(mode==='budget'){
      let b=app.assistant.aiUsage.budgetStatus();app.assistant.aiUsage.configureBudget({revision:b.revision,enabled:true,dailyTokens:500000});app.coreInbox.reader={verifyMessage:async()=>({})};app.assistant.coreWorkAnalyse=async context=>{const p=context.evidence.find(e=>e.text);return {dependencies:[],deliveries:[],messages:[],citations:[{citationId:p.citationId,quote:p.text,interpretation:'已核对合成来源，无新增准备动作'}]};};
      await app.coreInbox.resumeBudgetQueue(app.workspaceId);await done(input);r=await receipt(input);assert.equal(r.status,'saved');assert.equal(r.preparation.status,'prepared');assert.equal(progress().length,1);assert.equal(app.state().sources.filter(v=>v.personalMessage?.messageId==='om_stage_budget').length,1);
    }
  },{workAnalyse:async(_context,{signal})=>{await new Promise(resolve=>{release=resolve;signal.addEventListener('abort',resolve,{once:true});});throw Object.assign(Error(mode==='budget'?'合成后续准备预算不足':'合成后续分析超时'),{status:429,code:mode==='budget'?'AI_BUDGET':'TEST_TIMEOUT'});}});
});
await test('B02-persistence','unpersisted saved outcome cannot assert success; durable receipt survives job cache loss and undo is distinguished',()=>inbox(async({app,receive,done,receipt})=>{
  const input=await receive('om_durable'),j=await done(input),original=app.assistant.get.bind(app.assistant);
  app.assistant.get=(id,w)=>({...original(id,w),coreOutcome:undefined,p1Outcome:undefined});assert.equal((await receipt(input)).status,'saved');app.assistant.get=original;
  const r=await receipt(input);await app.api('/api/v2/work-items',{workspaceId:app.workspaceId,sourceId:app.ids.action,requestId:crypto.randomUUID(),action:'p1-undo',operationId:r.save.receipt.operationId});assert.notEqual((await receipt(input)).status,'saved');
  const state=app.state();delete state.receipts['core-input:'+j.id];delete state.receipts['work-item:'+j.p1Outcome.receipt.operationId];state.sources.find(v=>v.id===input.id).inputEnvelope.effectWithdrawn=false;state.revision++;app.store.save(state,state.revision-1);
  const missing=await receipt(input);assert.equal(missing.save.status,'not_saved');assert.notEqual(missing.status,'saved');
}));

writeFileSync(path.join(output,'targeted-results.json'),JSON.stringify({scope:'Original compiled product domain, real WorkItemCoreService tick/notify, real HTTP input-receipt, event bridge, assistant and SQLite; synthetic calendar/model/transport only',results},null,2));
if(results.some(r=>!r.passed))process.exitCode=1;
