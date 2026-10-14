import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdirSync,readFileSync,readdirSync,writeFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {setTimeout as delay} from 'node:timers/promises';
import path from 'node:path';
import * as d from '../dist-local/domain.mjs';
import {workItemInputLabel} from '../app/work-item-input-label.ts';
import {startCoreFixture} from './core-fixtures.mjs';

const output=path.resolve('output/uat-ui01/evidence');mkdirSync(output,{recursive:true});
const {chromium}=createRequire('/REVIEW_HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json')('playwright');
const cache='/REVIEW_HOME/.agent-browser/browsers',chrome=readdirSync(cache).filter(x=>x.startsWith('chrome-')).sort().at(-1);
const app=await startCoreFixture(),browser=await chromium.launch({executablePath:path.join(cache,chrome,'Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'),headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1100},timezoneId:'Asia/Shanghai'}),page=await context.newPage(),results=[],errors=[],externalRequests=[];
page.setDefaultTimeout(18000);page.on('pageerror',e=>errors.push(e.message));
await context.route('**/*',route=>{const u=new URL(route.request().url());if(u.hostname!=='127.0.0.1'){externalRequests.push(u.origin);return route.abort();}return route.continue();});
const sessionId=crypto.randomUUID(),jobs=[];
function snapshot(){const db=new DatabaseSync(path.join(app.dataDir,'workbench.sqlite'),{readOnly:true});try{return {state:app.state(),jobs:db.prepare('select id,payload from assistant_jobs order by id').all()};}finally{db.close();}}
async function test(id,name,fn){try{await fn();results.push({id,name,passed:true});console.log('PASS',id,name);}catch(e){results.push({id,name,passed:false,error:e.stack});await page.screenshot({path:path.join(output,'history-failure.png'),fullPage:true});throw e;}}
async function submit(text,extra={}){const state=app.state(),row=state.sources.find(r=>r.id===app.ids.action),c=d.workItemState(state,row);let j=(await app.api('/api/v2/codex/jobs',{workspaceId:app.workspaceId,requestId:crypto.randomUUID(),sessionId,parentJobId:jobs.at(-1)?.id||'',mode:'answer',contextRef:{kind:'sources',id:row.id},sourceIds:[],text,attachmentIds:extra.attachmentIds||[],p1Input:{occurredAt:'2026-10-14T03:00:00Z',expectedVersion:row.version,expectedBasis:c.basis,expectedEvidenceBasis:c.liveEvidenceBasis,manual:extra.manual||{}}})).job;
 while(j.status==='running'){await delay(40);j=(await app.api('/api/v2/codex/jobs/'+j.id+'?workspaceId='+app.workspaceId)).job;}assert.equal(j.status,'completed',j.error);assert.equal(j.p1Outcome.status,'saved');jobs.push(j);return j;}
const entry=()=>page.locator('.iw-dialog .p1-entry');
async function openHistory(){await page.goto(app.origin+'/?'+new URLSearchParams({workspaceId:app.workspaceId,view:'attention',record:app.ids.action}));const panel=page.locator('.iw-dialog');await panel.locator('.work-item-panel').waitFor();await panel.getByRole('button',{name:'记录进展 / 讨论',exact:true}).click();await entry().getByRole('button',{name:'选项',exact:true}).click();const chooser=entry().getByLabel('已有对话',{exact:true});if(await chooser.inputValue()!==sessionId)await chooser.selectOption(sessionId);await entry().locator('.ca-user-message p').last().waitFor();}
try{
 await page.setContent('<main style="font:28px sans-serif;padding:40px"><h1>合成样件反馈</h1><p>样件已收到，等待验证。</p><p>UI-01 隔离测试图片，不代表实际业务。</p></main>');await page.screenshot({path:path.join(output,'synthetic-input.png')});
 const attachment=(await app.api('/api/v2/attachments',{workspaceId:app.workspaceId,name:'synthetic-input.png',mime:'image/png',base64:readFileSync(path.join(output,'synthetic-input.png')).toString('base64')})).attachment;
 await test('H01','original HTTP saves text, image, mixed, manual-only and image-plus-manual histories',async()=>{
  await submit('已联系合成负责人，文字记录。');
  await submit('',{attachmentIds:[attachment.id]});
  await submit('已收到合成样件，附图说明。',{attachmentIds:[attachment.id]});
  await submit('',{manual:{check:{state:'scheduled',date:'2026-10-20'}}});
  await submit('',{attachmentIds:[attachment.id],manual:{check:{state:'scheduled',date:'2026-10-21'}}});
  const history=await app.api('/api/v2/codex/sessions/'+sessionId+'?workspaceId='+app.workspaceId);assert.equal(history.jobs.length,5);
  const readback=history.jobs.map(j=>{assert.equal(j.attachmentIds,undefined);assert.equal(j.clientDraft,undefined);const original=app.state().sources.find(s=>s.id===j.coreInputSourceId);return {id:j.id,text:j.text,coreInputSourceId:j.coreInputSourceId,manual:j.p1Input?.manual,attachments:original?.attachments?.map(a=>({id:a.id,mime:a.mime})),receiptStatus:j.p1Outcome?.status,label:workItemInputLabel(j,app.state().sources)};});
  assert.deepEqual(readback.map(r=>r.label),['已联系合成负责人，文字记录。','图片输入','已收到合成样件，附图说明。','手动时间安排','图片输入与手动时间安排']);
  assert.equal(app.state().sources.find(s=>s.id===app.ids.action).workItem.p1.check.date,'2026-10-21');writeFileSync(path.join(output,'history-api-readback.json'),JSON.stringify(readback,null,2));
 });
 const before=snapshot(),expected=['已联系合成负责人，文字记录。','图片输入','已收到合成样件，附图说明。','手动时间安排','图片输入与手动时间安排'];
 await test('H02','actual product browser shows the five persisted input labels',async()=>{await openHistory();assert.deepEqual(await entry().locator('.ca-user-message p').allTextContents(),expected);await entry().getByRole('button',{name:'选项',exact:true}).click();await page.screenshot({path:path.join(output,'history-labels-before-refresh.png'),fullPage:true});});
 await test('H03','refresh and re-entry recover the same original history labels',async()=>{await page.reload();await openHistory();assert.deepEqual(await entry().locator('.ca-user-message p').allTextContents(),expected);await entry().getByRole('button',{name:'选项',exact:true}).click();await page.screenshot({path:path.join(output,'history-labels-after-refresh.png'),fullPage:true});await entry().locator('.ca-user-message p').last().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'history-manual-labels-after-refresh.png'),fullPage:true});});
 await test('H04','reading and refreshing do not change persisted input, time, receipts, reminder or approval data',async()=>{assert.deepEqual(snapshot(),before);assert.deepEqual(errors,[]);assert.deepEqual(externalRequests,[]);});
 await test('H05','related evidence and missing historical fields do not become manual-time or image claims',async()=>{
  const sources=[{id:'related-image',attachments:[{mime:'image/png'}]},{id:'document',attachments:[{mime:'application/pdf'}]}];
  assert.equal(workItemInputLabel({text:'',sourceIds:['related-image']},sources),'本次输入');
  assert.equal(workItemInputLabel({text:'',coreInputSourceId:'missing'},sources),'本次输入');
  assert.equal(workItemInputLabel({text:'',coreInputSourceId:'document'},sources),'附件输入');
  assert.equal(workItemInputLabel({text:'',p1Input:{manual:{check:{state:'unset'}}}},sources),'本次输入');
  for(const state of ['scheduled','pending','clear'])assert.equal(workItemInputLabel({text:'',p1Input:{manual:{completion:{state}}}},sources),'手动时间安排');
  assert.equal(workItemInputLabel({text:'保留原文',p1Input:{manual:{check:{state:'scheduled'}}}},sources),'保留原文');
 });
}finally{writeFileSync(path.join(output,'history-label-results.json'),JSON.stringify({scope:'Original product HTTP + isolated SQLite + Chromium history rendering; fixed synthetic model; display helper negative cases',version:JSON.parse(readFileSync('release.json')),results,errors,externalBrowserRequests:externalRequests},null,2));await browser.close();await app.close();}
