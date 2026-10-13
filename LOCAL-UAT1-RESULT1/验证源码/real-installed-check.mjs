import os from 'node:os';import {pathToFileURL} from 'node:url';const installRoot=process.env.PM_UAT_INSTALL_ROOT;if(!installRoot)throw Error('Set PM_UAT_INSTALL_ROOT to the reviewed local installation');
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync,readdirSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
const {startFixture,output}=await import(pathToFileURL(path.join(installRoot,'scripts/s1p1-fixtures.mjs')).href);
const daily=await(await fetch('http://127.0.0.1:5173/api/v2/status')).json();assert.equal(daily.testMode,false);assert.equal(daily.release.build,'20261013.p1-r4-fix1.1');
const cfg=await(await fetch('http://127.0.0.1:5173/api/v2/ai-settings',{headers:{'X-Workbench-Token':daily.csrfToken,'X-Workbench-Client':'ui'}})).json();assert.equal(cfg.chat.model,'gpt-6-astra');assert.equal(cfg.chat.effort,'max');
const app=await startFixture({real:true});app.runtimeSettings.update({revision:0,chat:cfg.chat,background:cfg.background});
const {chromium}=(process.env.PM_PLAYWRIGHT_MODULE?createRequire(process.env.PM_PLAYWRIGHT_MODULE)('playwright'):await import('playwright'));const cache=path.join(os.homedir(),'.agent-browser/browsers'),chrome=readdirSync(cache).filter(x=>x.startsWith('chrome-')).sort().at(-1),browser=await chromium.launch({executablePath:process.env.PM_CHROME_PATH||path.join(cache,chrome,'Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'),headless:true}),page=await browser.newPage({viewport:{width:1440,height:1100},timezoneId:'Asia/Shanghai'}),results=[],errors=[],external=[];
page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',route=>{const u=new URL(route.request().url());if(['http:','https:'].includes(u.protocol)&&u.origin!==app.origin){external.push(u.origin);return route.abort();}return route.continue();});
const target=()=>app.state().sources.find(s=>s.id===app.ids.action);const panel=()=>page.locator('.iw-dialog'),entry=()=>panel().locator('.p1-entry'),message=()=>entry().locator('[data-assistant-input]');
async function compose(){await page.goto(app.origin+'/?'+new URLSearchParams({workspaceId:app.workspaceId,view:'attention',record:app.ids.action}));await panel().getByRole('button',{name:'记录进展 / 讨论',exact:true}).click();await entry().waitFor();}
async function submit(text){await message().fill(text);await entry().getByRole('button',{name:'发送',exact:true}).click();}
try{
 await compose();const before=target().workItem.p1?.progress?.length||0;const text='我已经联系模拟工程师，收到测试报告初稿。';console.log('START real ordinary record');await submit(text);await panel().waitFor({state:'detached',timeout:600000});assert.equal(target().workItem.p1.progress.length,before+1);assert.match(target().workItem.p1.progress.at(-1).text,/联系|初稿/);await page.getByRole('region',{name:'本次保存回执'}).waitFor();await page.screenshot({path:output+'/real-ordinary-private.png'});results.push({path:'ordinary',passed:true,returnedToList:true,progressSaved:true,input:text});console.log('PASS real ordinary record returns to list');
 await compose();const next=target().workItem.p1.progress.length,mixed='我已联系模拟工程师，正在核对报告。接下来我该先检查什么？';console.log('START real mixed input');await submit(mixed);await page.waitForFunction(()=>document.querySelector('.p1-entry [data-assistant-input]')?.value==='',null,{timeout:600000});assert.equal(target().workItem.p1.progress.length,next+1);assert.equal(await panel().count(),1);assert.ok(await entry().locator('.ca-answer').count());await page.screenshot({path:output+'/real-mixed-private.png'});results.push({path:'mixed',passed:true,stayedInItem:true,progressSaved:true,input:mixed});console.log('PASS real mixed input saves facts and stays');
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.equal(app.state().actions.length,0);
}finally{
 const jobs=app.assistant.list(app.workspaceId);const fingerprints=Object.fromEntries(['domain.mjs','client/app.js','client/app.css'].map(n=>[n,createHash('sha256').update(readFileSync(path.join(installRoot,'dist-local',n))).digest('hex')]));
 writeFileSync(output+'/real-installed-results-private.json',JSON.stringify({scope:'installed modules and bundle; isolated synthetic database; real model from unchanged daily settings',release:daily.release,model:cfg.chat.model,effort:cfg.chat.effort,results,errors,external,domainAndClient: fingerprints,jobs},null,2));await browser.close();await app.close();
}
