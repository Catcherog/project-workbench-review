import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {mkdirSync,readdirSync,readFileSync,writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import * as d from '../dist-local/domain.mjs';
import {startCoreFixture} from './core-fixtures.mjs';
import {fixtureState} from './s1p1-fixtures.mjs';

// Actual product React -> HTTP -> isolated SQLite. No UI behavior is replaced by an API write.
// Fixture preparation and deliberate external state/failure injection are explicitly separate.
const output=path.resolve(process.env.PM_UAT1_FIX1_OUTPUT||'output/uat1-fix1/browser');mkdirSync(output,{recursive:true});
const {chromium}=createRequire(process.env.PM_PLAYWRIGHT_MODULE||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json'))('playwright');
const cache=path.join(os.homedir(),'.agent-browser/browsers');
const executablePath=process.env.PM_CHROME_PATH||path.join(cache,readdirSync(cache).filter(x=>x.startsWith('chrome-')).sort().at(-1),'Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing');
const outbound=[],client={simulation:true,identity:async()=>({scope:'tenant/app',userId:'ou_self',appId:'app',tenantKey:'tenant'}),run:async()=>{outbound.push('unexpected send');throw Error('This suite must not send even a simulated message');}};
const app=await startCoreFixture({client}),browser=await chromium.launch({executablePath,headless:true}),context=await browser.newContext({viewport:{width:1440,height:900},timezoneId:'Asia/Shanghai'}),page=await context.newPage();
const results=[],errors=[],external=[],posts=[],reads=[],screenshots=[];let serial=0,workspaceId,ids,batchId;
page.setDefaultTimeout(12000);page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{const url=new URL(r.url());if(r.method()==='POST')posts.push({path:url.pathname,body:r.postDataJSON()});else if(url.pathname.startsWith('/api/'))reads.push(url.pathname+url.search);});
await context.route('**/*',route=>{const u=new URL(route.request().url());if(['http:','https:'].includes(u.protocol)&&u.origin!==app.origin){external.push(u.origin);return route.abort();}return route.continue();});
const state=(id=workspaceId)=>app.store.load(id),progress=(id=workspaceId,source=ids.action)=>state(id).sources.find(r=>r.id===source)?.workItem.p1?.progress||[];
const panel=()=>page.locator('.iw-dialog'),entry=()=>panel().locator('.p1-entry'),input=()=>entry().locator('[data-assistant-input]');
const receipt=()=>page.getByRole('region',{name:'本次保存回执',exact:true}).last(),collab=()=>page.locator('.wb-int-collaboration').last();
const batch=()=>collab().getByRole('region',{name:'协作批次 '+batchId,exact:true}),card=i=>batch().locator('[data-message-id]').nth(i);
const save=()=>batch().getByRole('button',{name:'保存本批所选决定（不发送）',exact:true});
const feedback=()=>batch().locator('.wb-action-feedback').filter({hasText:'本批决定：'});
async function until(fn){for(let i=0;i<250;i++){const value=await fn();if(value)return value;await delay(30);}throw Error('Expected UI/persistent state not reached');}
async function shot(name){const file=name+'.png';await page.screenshot({path:path.join(output,file)});screenshots.push(file);return file;}
async function visibleBox(locator){const box=await locator.boundingBox();assert.ok(box,'feedback is rendered');const viewport=page.viewportSize();assert.ok(box.y>=0&&box.y+box.height<=viewport.height+1,JSON.stringify({box,viewport}));return {box,viewport};}
async function check(id,name,fn){if(process.env.PM_UAT1_FIX1_CASES&&!process.env.PM_UAT1_FIX1_CASES.split(',').some(p=>id.startsWith(p)))return;try{const evidence=await fn();results.push({id,name,passed:true,evidence});console.log('PASS',id,name);}catch(e){results.push({id,name,passed:false,error:e.stack});await shot('failure-'+id);writeFileSync(path.join(output,'failure-'+id+'.txt'),await page.locator('body').innerText());throw e;}}
function fixture(name,{different=false}={}){const id='uat1-fix1-'+name+'-'+(++serial),f=fixtureState(id);f.s.workspaceName='合成验收 '+name;if(different){const row=f.s.sources.find(r=>r.id===f.ids.action);row.id='different-action-'+serial;f.ids.action=row.id;}app.store.insert(f.s);return {workspaceId:id,ids:f.ids};}
function setup(name){const f=fixture(name);workspaceId=f.workspaceId;ids=f.ids;return f;}
async function goto(view='attention',id){await page.goto(app.origin+'/?'+new URLSearchParams({workspaceId,view,...(id?{record:id}:{})}));await page.locator('.v2-app').waitFor();await until(()=>page.locator('#workspace-select').inputValue().then(v=>v===workspaceId));}
async function compose(){await goto('attention',ids.action);await panel().getByRole('button',{name:'记录进展 / 讨论',exact:true}).click();await input().waitFor();}
async function submit(){await until(()=>entry().getByRole('button',{name:'发送',exact:true}).isEnabled());await entry().getByRole('button',{name:'发送',exact:true}).click();}
async function saveProgress(text='已收到本轮合成样件'){await compose();await input().fill(text);await submit();await panel().waitFor({state:'detached'});await receipt().getByText('本地记录已保存',{exact:true}).waitFor();}
async function selectWorkspace(id){await page.locator('#workspace-select').selectOption(id);await until(()=>new URL(page.url()).searchParams.get('workspaceId')===id);await page.getByText('本地数据已连接',{exact:true}).waitFor();}
async function noStaleReceipt(){assert.equal(await page.locator('.p1-receipt').count(),0);for(const name of ['查看记录','修改记录','撤销本次操作','设置时间','目前都待定'])assert.equal(await page.getByRole('button',{name,exact:true}).count(),0);}
async function openCollab(){await goto('assistant');await collab().locator(':scope > summary').click();await until(()=>collab().getByRole('button',{name:'重新读取当前记录',exact:true}).isEnabled());await batch().waitFor();}
async function reread(){await collab().getByRole('button',{name:'重新读取当前记录',exact:true}).click();await until(()=>collab().getByRole('button',{name:'重新读取当前记录',exact:true}).isEnabled());}
async function prepare(name){setup(name);let s=state();s.people=[{id:'engineer',title:'合成责任人',projectIds:['p'],sourceIds:[],version:1,identityVerified:true,feishuUserId:'ou_engineer',feishuIdType:'open_id',feishuAppId:'app',feishuTenantKey:'tenant'}];s.sources.push({id:'uat-proof',title:'合成依据',excerpt:'请核对两项合成工作。',projectIds:['p'],sourceIds:[],version:1});s.revision++;app.store.save(s,s.revision-1);const proof=s.sources.find(r=>r.id==='uat-proof');const messages=[ids.action,ids.risk].map((id,i)=>({id:'draft-'+i,workItemId:id,title:'合成消息 '+(i+1),text:'请核对合成样件 '+(i+1)+'；不是真实业务发送。',recipientId:'engineer',channel:'private',proof:[{sourceId:proof.id,fingerprint:d.coreProofFingerprint(proof),quote:proof.excerpt}]}));const r=await app.api('/api/v2/core',{workspaceId,action:'prepare-messages',requestId:crypto.randomUUID(),messages});batchId=r.source.id;}
function messages(){return state().sources.find(r=>r.id===batchId).reminderRun.items;}

try{
 await check('U01-navigation','saved receipt and all five actions stay in their original workspace across dropdown/back/forward',async()=>{
  const a=setup('scope-a'),b=fixture('same-ids'),c=fixture('different-ids',{different:true}),bBefore=state(b.workspaceId),cBefore=state(c.workspaceId);
  await saveProgress();const op=d.entryReceipts(state(),ids.action)[0].operationId;
  await receipt().getByRole('button',{name:'查看记录',exact:true}).click();await panel().waitFor();assert.equal(new URL(page.url()).searchParams.get('record'),ids.action);await panel().getByRole('button',{name:'关闭事项，返回清单',exact:true}).click();
  await receipt().getByRole('button',{name:'修改记录',exact:true}).click();await input().waitFor();assert.match(await input().inputValue(),/已收到本轮/);await entry().getByRole('button',{name:'取消编辑',exact:true}).click();await panel().waitFor({state:'detached'});
  await receipt().getByRole('button',{name:'设置时间',exact:true}).click();await entry().getByLabel('检查时间状态',{exact:true}).waitFor();assert.equal(new URL(page.url()).searchParams.get('record'),ids.action);await entry().getByRole('button',{name:'取消编辑',exact:true}).click();
  const before=posts.length;await selectWorkspace(b.workspaceId);await noStaleReceipt();await shot('u01-same-id-workspace-clean');await page.goBack();await until(()=>page.locator('#workspace-select').inputValue().then(v=>v===a.workspaceId));await page.getByText('本地数据已连接',{exact:true}).waitFor();await noStaleReceipt();await page.goForward();await until(()=>page.locator('#workspace-select').inputValue().then(v=>v===b.workspaceId));await noStaleReceipt();await selectWorkspace(c.workspaceId);await noStaleReceipt();
  assert.equal(posts.length,before);assert.deepEqual(state(b.workspaceId),bBefore);assert.deepEqual(state(c.workspaceId),cBefore);
  await selectWorkspace(a.workspaceId);await compose();await receipt().getByText('本地记录已保存',{exact:true}).waitFor();assert.equal(d.entryReceipts(state(),ids.action)[0].operationId,op);
  return {sameItemIds:true,differentItemIds:true,historyNavigation:true,forbiddenActionPostDelta:0,otherWorkspacesUnchanged:true,operationId:op};
 });
 await check('U01-undo','undo survives workspace switching and persistent reentry without becoming saved again',async()=>{
  setup('undo');const b=fixture('undo-other'),before=state(b.workspaceId);await saveProgress('已收到待撤销的合成样件');const op=d.entryReceipts(state(),ids.action)[0].operationId;
  await receipt().getByRole('button',{name:'撤销本次操作',exact:true}).click();await receipt().getByText('本次操作已撤销',{exact:true}).waitFor();assert.equal(progress().length,0);const count=posts.length;
  await selectWorkspace(b.workspaceId);await noStaleReceipt();await selectWorkspace(workspaceId);await compose();await receipt().getByText('本次操作已撤销',{exact:true}).waitFor();assert.equal(await receipt().getByRole('button',{name:'撤销本次操作',exact:true}).count(),0);assert.equal(posts.length,count);assert.deepEqual(state(b.workspaceId),before);await shot('u01-durable-undone-reentry');return {operationId:op,undoneAt:state().receipts['work-item:'+op].result.undoneAt,newPosts:0};
 });
 await check('U01-pending-valid','the original workspace still accepts the explicit pending-time action exactly once',async()=>{
  setup('pending-valid');await saveProgress();const before=posts.length;await receipt().getByRole('button',{name:'目前都待定',exact:true}).click({clickCount:2,delay:15});await receipt().getByText('明确待定',{exact:true}).waitFor();const timing=state().sources.find(r=>r.id===ids.action).workItem.p1;assert.equal(timing.check.state,'pending');assert.equal(timing.completion.state,'pending');assert.equal(posts.length-before,1);return {check:'pending',completion:'pending',writes:1,simulatedSends:0};
 });
 await check('U01-late-job','a job finishing after leaving its workspace cannot populate or close the new workspace entry',async()=>{
  setup('late-job');const origin=workspaceId,originId=ids.action,b=fixture('late-job-other'),before=state(b.workspaceId);await compose();await input().fill('已收到延迟的合成样件');await submit();await panel().getByRole('button',{name:'关闭事项，返回清单',exact:true}).click();await selectWorkspace(b.workspaceId);await page.locator('.att-row').filter({hasText:'模拟培训材料'}).click();await panel().getByRole('button',{name:'记录进展 / 讨论',exact:true}).click();await input().fill('新区尚未提交的草稿');await until(()=>progress(origin,originId).length===1);await delay(150);assert.equal(await input().inputValue(),'新区尚未提交的草稿');assert.equal(await entry().getByRole('region',{name:'本次保存回执',exact:true}).count(),0);assert.deepEqual(state(b.workspaceId),before);return {originalWorkspaceSavedOnce:true,newWorkspaceUnchanged:true,newDraftPreserved:true};
 });
 for(const action of ['undo','pending'])await check('U01-inflight-'+action,'scope changes while original-request lookup is pending cannot continue a receipt write',async()=>{
  setup('inflight-'+action);const b=fixture('inflight-other');await saveProgress();const aBefore=state(),bBefore=state(b.workspaceId),before=posts.length;let release,entered=false,finished=false;
  const hold=async route=>{if(route.request().method()==='GET'){const response=await route.fetch();entered=true;await new Promise(r=>{release=r;});await route.fulfill({response});finished=true;}else await route.continue();};await page.route('**/api/v2/work-items?*',hold);
  try{await receipt().getByRole('button',{name:action==='undo'?'撤销本次操作':'目前都待定',exact:true}).click();await until(()=>entered);await selectWorkspace(b.workspaceId);release();await until(()=>finished);await page.unroute('**/api/v2/work-items?*',hold);await noStaleReceipt();await delay(100);assert.equal(posts.length,before);assert.deepEqual(state(),aBefore);assert.deepEqual(state(b.workspaceId),bBefore);return {action,originalLookupOnly:true,writeDelta:0,bothWorkspacesUnchanged:true};}finally{release?.();if(entered&&!finished)await until(()=>finished);await page.unroute('**/api/v2/work-items?*',hold);}
 });
 await check('U01-late-refresh','A-to-B-to-A during save readback cannot close or replace the new entry',async()=>{
  setup('late');const b=fixture('late-other'),bBefore=state(b.workspaceId);await compose();await input().fill('已收到异步保存的合成样件');let release,entered=false,finished=false;
  const hold=async route=>{if(!entered&&progress().length===1){const response=await route.fetch();entered=true;await new Promise(r=>{release=r;});await route.fulfill({response});finished=true;}else await route.continue();};await page.route('**/api/v2/snapshot?workspaceId='+workspaceId,hold);
  try{await submit();await until(()=>entered);await panel().getByRole('button',{name:'关闭事项，返回清单',exact:true}).click();await selectWorkspace(b.workspaceId);await noStaleReceipt();await selectWorkspace(workspaceId);await page.locator('.att-row').filter({hasText:'模拟培训材料'}).click();await panel().getByRole('button',{name:'记录进展 / 讨论',exact:true}).click();await input().fill('新的未提交草稿');release();await until(()=>finished);await page.unroute('**/api/v2/snapshot?workspaceId='+workspaceId,hold);await delay(150);assert.equal(await input().inputValue(),'新的未提交草稿');assert.equal(progress().length,1);assert.deepEqual(state(b.workspaceId),bBefore);return {originSavedOnce:true,otherWorkspaceUnchanged:true,newDraftPreserved:true};}finally{release?.();if(entered&&!finished)await until(()=>finished);await page.unroute('**/api/v2/snapshot?workspaceId='+workspaceId,hold);}
 });
 await check('U01-missing','missing current durable receipt disables every action instead of trusting cached saved content',async()=>{
  setup('missing');await saveProgress();const live=d.entryReceipts(state(),ids.action)[0],s=state();delete s.receipts['work-item:'+live.operationId];s.revision++;app.store.save(s,s.revision-1);const before=posts.length;
  const warning=page.getByRole('region',{name:'保存回执待核实',exact:true});await warning.waitFor();assert.equal(await warning.getByRole('button').count(),0);assert.equal(await page.getByText('本地记录已保存',{exact:true}).count(),0);assert.equal(posts.length,before);await shot('u01-missing-durable-receipt');return {injected:'removed only the synthetic durable receipt',cachedSuccess:false,actionCount:0,writeDelta:0};
 });
 for(const viewport of [{width:1024,height:768},{width:1440,height:900}]){
  const size=viewport.width+'x'+viewport.height;
  await check('U02-field-'+size,'empty scheduled date points to its field, stays visible and makes no request',async()=>{
   setup('field-'+size);await page.setViewportSize(viewport);await compose();const text='已收到需补日期的合成样件';await input().fill(text);await entry().getByLabel('检查时间状态',{exact:true}).selectOption('scheduled');const before=posts.length;await submit();const error=entry().locator('#p1-check-error');await error.waitFor();await until(()=>page.evaluate(()=>document.activeElement?.getAttribute('aria-label')==='检查日期'));const geometry=await visibleBox(error);assert.equal(await input().inputValue(),text);assert.equal(await entry().getByLabel('检查日期',{exact:true}).getAttribute('aria-invalid'),'true');assert.equal(posts.length,before);await shot('u02-field-'+size);await entry().getByLabel('检查日期',{exact:true}).fill('2026-10-20');await submit();await panel().waitFor({state:'detached'});assert.equal(progress().length,1);return {...geometry,draftRetained:true,invalidSubmissionPosts:0,correctedSaveCount:1};
  });
  await check('U02-save-'+size,'decision save feedback is local and visible; rapid repeat click has one write and no send',async()=>{
   await prepare('save-'+size);await page.setViewportSize(viewport);await openCollab();await card(0).getByRole('checkbox').check();const before=posts.length;await save().click({clickCount:2,delay:15});await feedback().getByText('所选决定已保存；本次没有发送消息。',{exact:true}).waitFor();const geometry=await visibleBox(feedback());assert.equal(messages()[0].stage,'approved');assert.equal(messages()[1].stage,'pending_review');assert.equal(posts.slice(before).filter(x=>x.body.action==='decide-messages').length,1);assert.equal(outbound.length,0);await shot('u02-save-'+size);return {...geometry,approvalWrites:1,simulatedSends:0};
  });
  await check('U02-rejected-'+size,'known rejection stays beside the edit action and preserves the local draft',async()=>{
   await prepare('rejected-'+size);await page.setViewportSize(viewport);await openCollab();await card(0).getByRole('textbox').fill('本地尚未保存的合成草稿');const before=structuredClone(state()),start=posts.length;
   const reject=route=>route.request().method()==='POST'?route.fulfill({status:409,contentType:'application/json',body:'{"error":"合成保存被拒绝，请重新核对"}'}):route.continue();await page.route('**/api/v2/core',reject);
   try{await card(0).getByRole('button',{name:'保存修改并回读预览',exact:true}).click();const local=card(0).locator('.wb-action-feedback');await local.getByRole('alert').waitFor();const geometry=await visibleBox(local);assert.equal(await card(0).getByRole('textbox').inputValue(),'本地尚未保存的合成草稿');assert.deepEqual(state(),before);assert.doesNotMatch(await local.innerText(),/所选决定已保存/);assert.equal(posts.length-start,1);await shot('u02-rejected-'+size);return {...geometry,postAttempts:1,durableWrites:0,draftRetained:true};}finally{await page.unroute('**/api/v2/core',reject);}
  });
  await check('U02-readback-'+size,'acknowledged save plus failed readback remain distinct and visible; reread does not resubmit',async()=>{
   await prepare('readback-'+size);await page.setViewportSize(viewport);await openCollab();await card(0).getByRole('checkbox').check();const before=posts.length;
   const reject=route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"合成显示回读失败"}'});await page.route('**/api/v2/core?*',reject);
   try{await save().click();await feedback().getByRole('alert').filter({hasText:'显示回读失败'}).waitFor();const geometry=await visibleBox(feedback());assert.equal(messages()[0].stage,'approved');assert.equal(await save().isDisabled(),true);await shot('u02-readback-'+size);await page.unroute('**/api/v2/core?*',reject);await reread();assert.equal(posts.length-before,1);assert.equal(messages()[0].approvalHistory.length,1);return {...geometry,approvalWrites:1,readbackRecoveryPostDelta:0};}finally{await page.unroute('**/api/v2/core?*',reject);}
  });
  await check('U02-unknown-'+size,'lost acknowledgement stays unknown; explicit retry reads first and reuses the same request identity',async()=>{
   await prepare('unknown-'+size);await page.setViewportSize(viewport);await openCollab();await card(0).getByRole('checkbox').check();const start=posts.length;let lost=false;
   const lose=async route=>{if(!lost&&route.request().method()==='POST'){lost=true;await route.fetch();await route.abort('failed');}else await route.continue();};await page.route('**/api/v2/core',lose);
   try{await save().click();await feedback().getByText(/请求结果尚未完全核实/).waitFor();const geometry=await visibleBox(feedback());assert.doesNotMatch(await feedback().innerText(),/所选决定已保存/);assert.equal(messages()[0].approvalHistory.length,1);assert.equal(posts.length-start,1);await shot('u02-unknown-'+size);await page.unroute('**/api/v2/core',lose);await reread();await collab().getByRole('region',{name:'尚未核实的请求',exact:true}).waitFor();assert.equal(posts.length-start,1);const readBefore=reads.length;await collab().getByRole('button',{name:'先查询，再按原身份核实／续办',exact:true}).click();await collab().getByText('所选决定已保存；本次没有发送消息。',{exact:true}).waitFor();assert.equal(posts.length-start,2);assert.deepEqual(posts[start].body,posts[start+1].body);assert.ok(reads.length>readBefore);assert.equal(messages()[0].approvalHistory.length,1);return {...geometry,originalRequestId:posts[start].body.requestId,automaticRetryCount:0,explicitSameIdentityRetries:1,durableApprovals:1};}finally{await page.unroute('**/api/v2/core',lose);}
  });
 }
 await check('U02-filter','a completed message leaving the current filter keeps its feedback visible in its batch',async()=>{
  await prepare('filter');await openCollab();await collab().getByRole('button',{name:'待决定',exact:true}).click();const before=posts.length;await card(0).getByRole('button',{name:'取消此消息',exact:true}).click();await feedback().getByText('所选决定已保存；本次没有发送消息。',{exact:true}).waitFor();const geometry=await visibleBox(feedback());assert.equal(messages()[0].stage,'cancelled');assert.equal(await batch().getByRole('heading',{name:'合成消息 1',exact:true}).count(),0);assert.equal(posts.length-before,1);return {...geometry,completedCardExited:true,feedbackRetained:true};
 });
 await check('BOUNDARY','all writes remain synthetic and no scheduler or outbound transport is used',async()=>{assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.equal(outbound.length,0);assert.equal(app.core.settings(workspaceId).enabled,false);return {consoleErrors:errors,externalRequests:external,realWrites:0,simulatedSends:0,schedulerEnabled:false};});
}finally{
 const files=['app/workbench-v2.tsx','app/work-item-entry.tsx','app/work-item-time.tsx','app/integration/core-collaboration-panel.tsx','app/integration/receipt-scope.ts','app/integration/action-feedback.tsx','app/integration/action-feedback.css','lib/work-item-progress.ts'];
 writeFileSync(path.join(output,'results.json'),JSON.stringify({scope:'Actual isolated product React/HTTP/SQLite; synthetic fixtures and injected transport failures; not user acceptance',code:files.map(file=>({file,sha256:createHash('sha256').update(readFileSync(file)).digest('hex')})),results,posts,reads,screenshots,errors,external,simulatedSends:outbound.length},null,2)+'\n');await browser.close();await app.close();
}
