import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdirSync,mkdtempSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import * as domain from '../dist-local/followup.mjs';
import {LocalStore} from './local-store.mjs';
import {FollowupService} from './followup-service.mjs';
import {ReminderExecution} from './reminder-execution.mjs';
import {ResultReview} from './result-review.mjs';
import {petSnapshot} from './pet-snapshot.mjs';
import {fixedNow as now,fixture,contacted,comment,clearFeedback,row,mockClient} from './followup-fixtures.mjs';
const output=path.resolve('output/parallel-B');mkdirSync(output,{recursive:true});const dir=mkdtempSync(path.join(output,'boundaries-data-'));
const tests=[],test=async(name,fn)=>{try{await fn();tests.push({name,status:'passed'});console.log('PASS',name);}catch(e){tests.push({name,status:'failed',error:e.message});throw e;}};
const ref={kind:'deliverables',targetId:'d'},p=s=>domain.buildFollowup(s,ref,now);
const store=new LocalStore(dir,{testMode:true});await store.initialize(null);
const save=(id,mutate)=>{const before=store.load(id),next=structuredClone(before);mutate(next);next.revision++;store.save(next,before.revision);};
try{
  await test('reviewing vague feedback does not remove its information gap',()=>{
    let s=comment(contacted(domain,fixture(domain)));s=domain.applyFollowupOperation(s,{...ref,workspaceId:s.workspaceId,requestId:'ack',expectedBasis:p(s).basis,action:'review_feedback'},now);assert.equal(p(s).pendingReply,false);assert.equal(p(s).handlingState,'attention');assert.equal(p(s).primaryAction,'clarify');
  });
  await test('corrected original invalidates captured text; new valid capture restores clear feedback',()=>{
    let s=clearFeedback(domain,contacted(domain,fixture(domain)));
    comment(s,{id:'original',at:'2026-09-30T09:30:00+08:00',content:s.sources.find(r=>r.id==='doc').excerpt});
    const original=s.sources.find(r=>r.id==='original'),doc=s.sources.find(r=>r.id==='doc');
    Object.assign(doc.intakeDocument,{originalSourceId:'original',originalContentKey:domain.materialSourceContentKey(original),originalIdentityKey:domain.materialSourceIdentityKey(s,original)});
    original.excerpt='样机测试报告：测试结果已复核，预计 2026-10-04 整项完成。';original.feedback.contentVersion++;original.feedback.eventAt='2026-09-30T09:40:00+08:00';assert.equal(p(s).feedbackState,'stale');
    s=clearFeedback(domain,s,{at:'2026-09-30T09:45:00+08:00',forecast:'2026-10-04',progress:'测试结果已复核',suffix:'-new'});
    const fresh=s.sources.find(r=>r.id==='doc-new');Object.assign(fresh.intakeDocument,{originalSourceId:'original',originalContentKey:domain.materialSourceContentKey(s.sources.find(r=>r.id==='original')),originalIdentityKey:domain.materialSourceIdentityKey(s,s.sources.find(r=>r.id==='original'))});
    assert.equal(p(s).feedbackState,'clear');assert.equal(p(s).reminderEligible,false);assert.ok(p(s).sources.some(r=>r.id==='doc'&&!r.available));
  });
  await test('same-day gate, missing gate and expired forecast never justify automatic hold',()=>{
    for(const mode of ['same-day','missing','expired']){let s=clearFeedback(domain,fixture(domain));if(mode==='same-day')s.flowNodes[0].plannedEnd='2026-10-03';if(mode==='missing')s.flowNodes=[];if(mode==='expired')s.deliverables[0].forecast='2026-09-29';assert.notEqual(p(s).feedbackState,'clear',mode);}
  });
  await test('a later reminder starts a new waiting cycle without treating known feedback as a new stale reply',()=>{
    const s=clearFeedback(domain,contacted(domain,fixture(domain)));contacted(domain,s,'d','2026-10-04T09:00:00+08:00');
    const current=domain.buildFollowup(s,ref,Date.parse('2026-10-04T10:00:00+08:00'));assert.equal(current.handlingState,'waiting');assert.equal(current.feedbackState,'none');
  });
  await test('delayed readback does not postpone the original follow-up deadline',()=>{
    const s=contacted(domain,fixture(domain));s.sources[0].reminderRun.finishedAt='2026-10-02T09:00:00+08:00';s.sources[0].reminderRun.messages[0].readAt='2026-10-02T09:00:00+08:00';
    assert.equal(domain.buildFollowup(s,ref,Date.parse('2026-10-02T10:00:00+08:00')).handlingState,'attention');
  });
  await test('ordinary source updates and unrelated batch targets do not change urgent notification basis',()=>{
    let s=clearFeedback(domain,fixture(domain));s.actions=[row('urgency',{status:'需要升级协调',outputIds:['d']})];const before=p(s).notificationBasis,decision=p(s).basis;s.sources.find(r=>r.id==='batch').intakeBatch.pending.push({sourceId:'unrelated',targetId:'someone-else',reason:'另一事项缺数据'});assert.equal(p(s).basis,decision);s.sources.find(r=>r.id==='doc').version++;assert.equal(p(s).notificationBasis,before);
  });
  await test('kind and workspace are part of identity even when IDs match',()=>{
    const s=contacted(domain,fixture(domain));s.risks=[row('d',{confirmed:true,impact:'高'})];const risk=domain.buildFollowup(s,{kind:'risks',targetId:'d'},now);assert.notEqual(risk.itemKey,p(s).itemKey);assert.equal(risk.nextCheckAt,'');const other={...s,workspaceId:'different'};assert.notEqual(p(other).itemKey,p(s).itemKey);assert.notEqual(p(other).handlingState,'waiting');
  });
  await test('full state and private-body-free pet projection share waiting/urgent identity',()=>{
    const s=contacted(domain,fixture(domain));s.deliverables.push(row('urgent',{status:'进行中'}));s.actions=[row('a',{outputIds:['urgent'],status:'需要升级协调'})];const overview=domain.buildWorkbenchOverview(s,'2026-09-30',now),projections=overview.allAttention.map(i=>i.followup).filter(Boolean),minimal=petSnapshot(s,projections),reminders=domain.derivePetReminders(minimal,now);
    assert.ok(!reminders.some(r=>r.itemKey===p(s).itemKey));const urgent=reminders.find(r=>r.notifyEligible);assert.equal(urgent.itemKey,domain.buildFollowup(s,{kind:'deliverables',targetId:'urgent'},now).itemKey);assert.ok(!JSON.stringify(minimal).includes('raw'));assert.deepEqual(domain.derivePetReminders(s,now).filter(r=>r.notifyEligible).map(r=>r.itemKey),reminders.filter(r=>r.notifyEligible).map(r=>r.itemKey));
  });
  await test('idempotent local operations survive an actual SQLite reopen',()=>{
    const s=contacted(domain,fixture(domain,'schedule'));store.insert(s);const service=new FollowupService({store,domain,clock:()=>now}),op={...ref,workspaceId:'schedule',requestId:'one',expectedBasis:p(s).basis,action:'reschedule',nextCheckAt:'2026-10-02T11:00:00+08:00',reason:'等待实测数据'};service.operate(op);const reopened=new LocalStore(dir,{testMode:true});try{const again=new FollowupService({store:reopened,domain,clock:()=>now}),before=reopened.load('schedule').revision;assert.equal(again.operate(op).state.revision,before);assert.equal(again.project(reopened.load('schedule'),ref).nextCheckAt,'2026-10-02T03:00:00.000Z');}finally{reopened.close();}
  });
  await test('manual time adjustment does not hide a future formal deadline or gate after it becomes due',()=>{
    let s=contacted(domain,fixture(domain));s=domain.applyFollowupOperation(s,{...ref,workspaceId:s.workspaceId,requestId:'past-gate',expectedBasis:p(s).basis,action:'reschedule',nextCheckAt:'2026-10-08T11:00:00+08:00',reason:'调整检查时间'},now);
    assert.equal(p(s).nextCheckAt,'2026-10-04T01:00:00.000Z');assert.match(p(s).reasons.join(' '),/正式期限/);assert.equal(domain.buildFollowup(s,ref,Date.parse('2026-10-04T10:00:00+08:00')).handlingState,'attention');
  });
  const client=mockClient(),followups=new FollowupService({store,domain,clock:()=>now}),reminders=new ReminderExecution({store,domain,client,followups,clock:()=>now});
  const choose=async workspaceId=>(await reminders.propose({workspaceId})).items.map(i=>({...i,recipientIds:[i.assignee],createTask:false}));
  await test('same recipient receives separate messages for distinct targets in same-name projects',async()=>{
    const s=fixture(domain,'groups');s.projects.push(row('p2',{title:s.projects[0].title}));s.deliverables.push(row('d2',{projectIds:['p2'],ownerId:'owner',status:'进行中'}));store.insert(s);const prepared=await reminders.prepare({workspaceId:'groups',items:await choose('groups')});assert.equal(prepared.source.reminderRun.messages.length,2);assert.equal(new Set(prepared.source.reminderRun.messages.map(m=>m.targetId)).size,2);assert.ok(prepared.source.reminderRun.messages.every(m=>(m.text.match(/【模拟研发项目】/g)||[]).length===1));assert.deepEqual(client.calls,{messages:0,tasks:0});
  });
  await test('editing approved outbound content invalidates its old approval',async()=>{
    const s=fixture(domain,'tamper');store.insert(s);const prepared=await reminders.prepare({workspaceId:'tamper',items:await choose('tamper')});save('tamper',s=>{s.sources.find(r=>r.id===prepared.source.id).reminderRun.messages[0].text='已经修改的消息';});await assert.rejects(()=>reminders.send({workspaceId:'tamper',sourceId:prepared.source.id,approvalHash:prepared.source.reminderRun.approvalHash}),/原批准失效/);assert.equal(client.calls.messages,0);
  });
  await test('an expired unsent preview can be replaced, while a partially executed batch blocks duplicate preparation',async()=>{
    const s=fixture(domain,'expired-preview');store.insert(s);let clock=now;const service=new ReminderExecution({store,domain,client,followups,clock:()=>clock});
    const first=await service.prepare({workspaceId:s.workspaceId,items:await choose(s.workspaceId)});clock+=31*60000;const second=await service.prepare({workspaceId:s.workspaceId,items:await choose(s.workspaceId)});assert.notEqual(first.source.id,second.source.id);
    save(s.workspaceId,state=>{const run=state.sources.find(src=>src.id===second.source.id).reminderRun;run.status='partial';run.messages[0].stage='readback_verified';run.messages.push({...run.messages[0],recipientId:'ou_other',stage:'pending'});});
    await assert.rejects(async()=>service.prepare({workspaceId:s.workspaceId,items:await choose(s.workspaceId)}),/待核对/);assert.equal(client.calls.messages,0);await service.close();
  });
  await test('two service instances cannot claim the same notification channel twice',async()=>{
    const s=fixture(domain,'dupe-notify');s.actions=[row('a',{status:'需要升级协调',outputIds:['d']})];store.insert(s);const sent={desktop:0,feishu_self:0};
    const notifications=Object.fromEntries(Object.keys(sent).map(name=>[name,{identity:async()=>({selfId:'ou_self',channel:name}),send:async input=>{sent[name]++;return {id:input.key,selfId:input.selfId,basis:input.basis};},readback:async receipt=>receipt}]));
    const a=new FollowupService({store,domain,clock:()=>now,notifications}),b=new FollowupService({store,domain,clock:()=>now,notifications});await Promise.all([a.notify({workspaceId:s.workspaceId,...ref,selfId:'ou_self'}),b.notify({workspaceId:s.workspaceId,...ref,selfId:'ou_self'})]);assert.deepEqual(sent,{desktop:1,feishu_self:1});
  });
  await test('one failed notification channel is visible; reconcile never resends either channel',async()=>{
    const s=fixture(domain,'partial-notify');s.actions=[row('a',{status:'需要升级协调',outputIds:['d']})];store.insert(s);let count=0,readFailure=true;
    const notifications=Object.fromEntries(['desktop','feishu_self'].map(name=>[name,{identity:async()=>({selfId:'ou_self',channel:name}),send:async input=>{count++;return {id:input.key,selfId:input.selfId,basis:input.basis};},readback:async receipt=>{if(name==='feishu_self'&&readFailure)throw Error('模拟通知回读失败');return receipt;}}]));
    const service=new FollowupService({store,domain,clock:()=>now,notifications});const r=await service.notify({workspaceId:s.workspaceId,...ref,selfId:'ou_self'});assert.equal(r.channels.desktop.stage,'readback_verified');assert.equal(r.channels.feishu_self.stage,'needs_reconcile');readFailure=false;await service.reconcileNotification({workspaceId:s.workspaceId,sourceId:r.sourceId});await service.notify({workspaceId:s.workspaceId,...ref,selfId:'ou_self'});assert.equal(count,2);
  });
  await test('notification timeout without an ID remains unknown after restart',async()=>{
    const s=fixture(domain,'unknown-notify');s.actions=[row('a',{status:'需要升级协调',outputIds:['d']})];store.insert(s);let count=0;
    const notifications={desktop:{identity:async()=>({selfId:'ou_self',channel:'desktop'}),send:async()=>{count++;throw Error('模拟系统通知超时');}}};let service=new FollowupService({store,domain,clock:()=>now,notifications});const r=await service.notify({workspaceId:s.workspaceId,...ref,selfId:'ou_self'});service=new FollowupService({store,domain,clock:()=>now,notifications});await service.notify({workspaceId:s.workspaceId,...ref,selfId:'ou_self'});await assert.rejects(()=>service.reconcileNotification({workspaceId:s.workspaceId,sourceId:r.sourceId}),/缺少通知 ID/);assert.equal(count,1);
  });
  await test('manager acceptance is never silently replaced by a concurrent different conclusion',async()=>{
    const s=fixture(domain,'review-race');s.externalObjects=[{id:'ext',workspaceId:s.workspaceId,system:'meegle',host:'project.feishu.cn',remoteKind:'deliverable',remoteId:'123',spaceKey:'test',tenantKey:'',parentRemoteId:'',parentNodeRemoteId:'',parentDeliverableRemoteId:'',sourceId:'',sourceHash:'simulated',localObjectId:'d',verificationStatus:'verified',mappingStatus:'mapped',collectedAt:'2026-09-30T02:00:00Z',raw:{workItemType:'film',fields:{}}}];store.insert(s);
    const content='模拟成果：三组试验数据已提交。',sha256=createHash('sha256').update(content).digest('hex');
    const review=new ResultReview({store,domain,adapter:{readObject:async()=>({complete:true,remoteId:'123',spaceKey:'test',collectedAt:'2026-09-30T02:00:00Z',fields:{field_d06ce2:['https://a.feishu.cn/docx/RESULTbtest']}})},reader:{read:async({documentKey})=>({documentKey,name:'模拟报告',content,sha256,revision:1,url:'https://a.feishu.cn/docx/RESULTbtest',carrier:'results'})},analyse:async()=>({summary:'模拟成果',concerns:[],limitations:[]})});
    const prepared=await review.prepare({workspaceId:s.workspaceId,deliverableId:'d'});const input={workspaceId:s.workspaceId,sourceId:prepared.source.id,professionalReviewConfirmed:true};const results=await Promise.allSettled([review.decide({...input,decision:'accepted',comment:'本人确认验收'}),review.decide({...input,decision:'returned',comment:'请补充数据'})]);assert.equal(results.filter(r=>r.status==='fulfilled').length,1);assert.equal(results.filter(r=>r.status==='rejected').length,1);const saved=store.load(s.workspaceId);assert.equal(saved.deliverables[0].deliveryReview,'未审核');assert.equal(saved.flowNodes[0].nodeStatus,'进行中');await review.close();
  });
  await reminders.close();
}finally{store.close();writeFileSync(path.join(output,'boundary-verification.json'),JSON.stringify({at:new Date().toISOString(),dataDir:dir,external:'mock-only',tests},null,2));}
console.log(`${tests.length} B boundary checks passed.`);
