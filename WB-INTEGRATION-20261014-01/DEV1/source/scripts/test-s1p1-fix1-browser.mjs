import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readdirSync,writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import * as d from '../dist-local/domain.mjs';
import {startFixture,output,operation} from './s1p1-fixtures.mjs';

const {chromium}=process.env.PM_PLAYWRIGHT_MODULE?createRequire(process.env.PM_PLAYWRIGHT_MODULE)('playwright'):await import('playwright');
const cache=path.join(os.homedir(),'.agent-browser/browsers'),chrome=process.env.PM_CHROME_PATH||path.join(cache,readdirSync(cache).filter(x=>x.startsWith('chrome-')).sort().at(-1),'Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing');
const app=await startFixture(),browser=await chromium.launch({executablePath:chrome,headless:true}),context=await browser.newContext({viewport:{width:1440,height:1100},timezoneId:'Asia/Shanghai'}),page=await context.newPage();
const results=[],errors=[],external=[],mutations=[],screenshots=[];page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')mutations.push(new URL(r.url()).pathname);});
await context.route('**/*',route=>{const u=new URL(route.request().url());if(['http:','https:'].includes(u.protocol)&&u.origin!==app.origin){external.push(u.origin);return route.abort();}return route.continue();});
const state=()=>app.state(),record=id=>state().sources.find(x=>x.id===id),panel=()=>page.locator('.iw-dialog'),entry=()=>panel().locator('.p1-entry'),message=()=>entry().locator('[data-assistant-input]'),send=()=>entry().getByRole('button',{name:'发送',exact:true}),receipt=()=>page.getByRole('region',{name:'本次保存回执'}).last();
async function open(id,view='attention'){await page.goto(app.origin+'/?'+new URLSearchParams({workspaceId:app.workspaceId,view,record:id}));await panel().locator('.work-item-panel').waitFor();}
async function compose(id,view='attention'){await open(id,view);await panel().getByRole('button',{name:'设置时间 / 记录进展',exact:true}).click();await entry().waitFor();}
async function selectTime(kind,date){await entry().getByLabel(kind+'时间状态',{exact:true}).selectOption('scheduled');await entry().getByLabel(kind+'日期',{exact:true}).fill(date);}
async function returned(){await panel().waitFor({state:'detached'});await receipt().waitFor();}
async function shot(name){await page.screenshot({path:path.join(output,name)});screenshots.push(name);}
async function post(id,text='',manual={}){return app.api('/api/v2/work-items',operation(state(),id,text,manual));}
async function ready(){await page.waitForFunction(()=>!document.querySelector('.p1-entry button[type=submit]')?.disabled);}
const selectedCases=(process.env.PM_FIX1_CASES||'').split(',').filter(Boolean);
async function check(id,name,fn){if(selectedCases.length&&!selectedCases.includes(id)&&id!=='boundary')return;try{const evidence=await fn();results.push({id,name,passed:true,evidence});console.log('PASS',id,name);}catch(error){results.push({id,name,passed:false,error:error.stack});await shot('fix1-browser-failure.png');throw error;}}
try{
 await check('F01-UI','旧时间→新安排→后来进展→撤销后回显旧时间',async()=>{
  const s=state(),r=s.sources.find(r=>r.id===app.ids.action);r.workItem.handling={state:'waiting',nextCheckAt:'2026-10-14T08:00:00+08:00'};s.revision++;app.store.save(s,s.revision-1);
  const before=d.workItemState(state(),record(app.ids.action));await compose(app.ids.action);assert.equal(await entry().getByLabel('检查具体时刻（可选）',{exact:true}).inputValue(),'08:00');
  await selectTime('检查','2026-10-15');await entry().getByLabel('检查具体时刻（可选）',{exact:true}).fill('');await ready();await send().click();await returned();
  await post(app.ids.action,'已收到初稿');await receipt().getByRole('button',{name:'撤销本次操作',exact:true}).click();await receipt().getByText('本次操作已撤销',{exact:true}).waitFor();
  const after=d.workItemState(state(),record(app.ids.action));assert.deepEqual(after.timing,before.timing);assert.equal(after.nextCheckAt,before.nextCheckAt);assert.equal(record(app.ids.action).workItem.p1.progress[0].text,'已收到初稿');
  await compose(app.ids.action);assert.equal(await entry().getByLabel('检查日期',{exact:true}).inputValue(),'2026-10-14');assert.equal(await entry().getByLabel('检查具体时刻（可选）',{exact:true}).inputValue(),'08:00');await shot('08-legacy-time-restored.png');return {summary:d.timeLabel(after.timing.check),status:after.timing.status,nextCheckAt:after.nextCheckAt,laterProgress:'已收到初稿'};
 });
 await check('F02-UI','处理期间修改时间和文字，旧候选不可操作，新候选与保存一致',async()=>{
  await compose(app.ids.action);await message().fill('延迟长：周三检查');await selectTime('检查','2026-10-15');await entry().getByLabel('检查具体时刻（可选）',{exact:true}).fill('');const before=structuredClone(record(app.ids.action).workItem.p1);
  await send().click();await entry().getByText('正在理解本次输入…',{exact:false}).waitFor();await selectTime('检查','2026-10-16');await message().fill('延迟：周三检查');
  await entry().getByText(/旧冲突候选已失效/).waitFor();assert.equal(await entry().locator('.p1-conflict').count(),0);assert.equal(await entry().getByLabel('检查日期',{exact:true}).inputValue(),'2026-10-16');assert.deepEqual(record(app.ids.action).workItem.p1,before); // Raw input persistence may advance the workspace revision; business timing must stay unchanged.
  await shot('09-obsolete-conflict-retired.png');
  await send().click();await entry().locator('.p1-conflict').waitFor();const label=entry().getByLabel(/手选安排.*2026-10-16/);await label.check();
  await message().fill('补充文字：周三检查');assert.equal(await entry().locator('.p1-conflict').count(),0);await send().click();await entry().locator('.p1-conflict').waitFor();assert.equal(await entry().getByLabel(/手选安排/).isChecked(),false);
  await entry().getByLabel(/手选安排.*2026-10-16/).check();await shot('10-current-conflict-candidate.png');await send().click();await returned();assert.equal(record(app.ids.action).workItem.p1.check.date,'2026-10-16');return {obsolete:'2026-10-15',visibleCandidate:'2026-10-16',saved:'2026-10-16',textEditInvalidated:true};
 });
 await check('F02-reload','分析中刷新仍保留较新草稿，旧clarify不重新成为可选项',async()=>{
  await compose(app.ids.action);await message().fill('延迟长：周三检查');await selectTime('检查','2026-10-15');await send().click();await entry().getByText('正在理解本次输入…',{exact:false}).waitFor();await selectTime('检查','2026-10-17');await page.reload();await panel().getByRole('button',{name:'记录进展 / 讨论',exact:true}).click();await entry().getByText(/旧冲突候选已失效/).waitFor();
  assert.equal(await entry().locator('.p1-conflict').count(),0);assert.equal(await entry().getByLabel('检查日期',{exact:true}).inputValue(),'2026-10-17');await entry().getByRole('button',{name:'取消编辑',exact:true}).click();return {restoredDraft:'2026-10-17',executableOldCandidates:0};
 });
 await check('F03-UI','列表回执和留场回执连续修改同一进展，撤销第二次修改',async()=>{
  await compose(app.ids.action);const count=record(app.ids.action).workItem.p1.progress.length;await message().fill('已联系负责人');await send().click();await returned();const first=record(app.ids.action).workItem.p1.progress.at(-1);
  await receipt().getByRole('button',{name:'修改记录',exact:true}).click();await message().fill('已收到初稿，接下来怎么办？');await send().click();await page.waitForFunction(()=>document.querySelector('.p1-entry [data-assistant-input]')?.value==='');
  await entry().getByRole('region',{name:'本次保存回执'}).getByRole('button',{name:'修改记录',exact:true}).click();await message().fill('补充进展：完成复核');await send().click();await returned();const latest=record(app.ids.action).workItem.p1.progress.at(-1);assert.equal(latest.id,first.id);assert.equal(record(app.ids.action).workItem.p1.progress.length,count+1);
  await receipt().getByRole('button',{name:'撤销本次操作',exact:true}).click();await receipt().getByText('本次操作已撤销',{exact:true}).waitFor();assert.equal(record(app.ids.action).workItem.p1.progress.at(-1).text,'已收到初稿');await open(app.ids.action);await shot('11-second-edit-undone.png');return {progressId:first.id,count:count+1,restored:'已收到初稿',bothEditEntrances:true};
 });
 await check('F04-UI','纯时间草稿版本变化可核对继续；核对后再次变更仍被服务拒绝',async()=>{
  await compose(app.ids.action);await selectTime('检查','2026-10-18');await post(app.ids.action,'补充进展：另一条记录已更新');await page.reload();await panel().getByRole('button',{name:'记录进展 / 讨论',exact:true}).click();
  await entry().getByRole('button',{name:'已核对当前记录，继续',exact:true}).waitFor();assert.equal(await message().inputValue(),'');assert.equal(await send().isDisabled(),true);assert.equal(await entry().getByLabel('检查日期',{exact:true}).inputValue(),'2026-10-18');await shot('12-time-only-version-recovery.png');
  await entry().getByRole('button',{name:'已核对当前记录，继续',exact:true}).click();await ready();await post(app.ids.action,'补充进展：核对后再更新');await send().click();await entry().getByRole('alert').filter({hasText:'事项已有新变化'}).waitFor();assert.equal(await entry().getByLabel('检查日期',{exact:true}).inputValue(),'2026-10-18');
  await page.reload();await panel().getByRole('button',{name:'记录进展 / 讨论',exact:true}).click();await entry().getByRole('button',{name:'已核对当前记录，继续',exact:true}).click();await send().click();await returned();assert.equal(record(app.ids.action).workItem.p1.check.date,'2026-10-18');return {emptyText:true,retained:'2026-10-18',postAcknowledgementRaceRejected:true,saved:'2026-10-18'};
 });
 await check('F05-UI','资料新增等待出现时间缺口，可补安排和两项待定',async()=>{
  assert.equal(d.itemTiming(state(),record(app.ids.reference)).status,'无需时间安排');await compose(app.ids.reference,'inbox');await message().fill('等待模拟工程师提供报告');await send().click();await returned();assert.match(await receipt().innerText(),/时间待确认/);await receipt().getByRole('button',{name:'设置时间',exact:true}).waitFor();await receipt().getByRole('button',{name:'目前都待定',exact:true}).waitFor();await shot('13-reference-waiting-time-gap.png');
  await receipt().getByRole('button',{name:'设置时间',exact:true}).click();await selectTime('检查','2026-10-16');await send().click();await returned();assert.match(await receipt().innerText(),/已安排/);await shot('14-reference-scheduled.png');
  await receipt().getByRole('button',{name:'设置时间',exact:true}).click();await entry().locator('[data-p1-time]').getByRole('button',{name:'目前都待定',exact:true}).click();await send().click();await returned();assert.match(await receipt().innerText(),/明确待定/);assert.equal(record(app.ids.reference).workItem.nature,'reference');await shot('15-reference-both-pending.png');return {statuses:['无需时间安排','时间待确认','已安排','明确待定'],nature:'reference'};
 });
 await check('F06-UI','其他时区日期完成要求保留精度，结束冲突须明确选择',async()=>{
  await post(app.ids.action,'',{completion:{state:'scheduled',date:'2026-10-15',zone:'-04:00'}});await compose(app.ids.action);assert.match(await entry().innerText(),/2026-10-15 -04:00/);assert.equal(await entry().getByLabel('完成具体时刻（可选）',{exact:true}).inputValue(),'');
  await message().fill('停止跟进');await selectTime('完成','2026-10-16');await send().click();await entry().locator('.p1-conflict').waitFor();assert.equal(record(app.ids.action).workItem.p1.completion.date,'2026-10-15');await panel().evaluate(el=>{const node=el.querySelector('.p1-conflict');el.scrollBy({top:node.getBoundingClientRect().top-el.getBoundingClientRect().top-110});});await shot('16-zone-date-end-conflict.png');
  await entry().getByLabel('还有后续，保留新安排',{exact:true}).check();await send().click();await returned();const node=record(app.ids.action).workItem.p1.completion;assert.equal(node.zone,'-04:00');assert.equal(node.precision,'date');assert.equal(node.effectiveAt,undefined);await compose(app.ids.action);await entry().locator('[data-p1-time]').scrollIntoViewIfNeeded();await shot('16b-zone-date-saved.png');return {date:node.date,zone:node.zone,precision:node.precision,display:d.timeLabel(node),effectiveAtPresent:Object.hasOwn(node,'effectiveAt')};
 });
 await check('B15-position','普通保存返回后项目筛选、搜索、原排序和非零浏览位置保留',async()=>{
  const s=state(),base=structuredClone(s.sources.find(x=>x.id===app.ids.action));
  for(let i=1;i<=36;i++){const r=structuredClone(base);r.id='p1-scroll-'+i;r.title='模拟浏览位置 '+String(i).padStart(2,'0');r.workItem.p1={};r.workItem.handling={};s.sources.push(r);}s.revision++;app.store.save(s,s.revision-1);
  await page.goto(app.origin+'/?'+new URLSearchParams({workspaceId:app.workspaceId,view:'attention'}));await page.getByLabel('按项目筛选待处理事项',{exact:true}).selectOption('p');await page.getByLabel('搜索待处理事项',{exact:true}).fill('模拟浏览位置');
  const rows=page.locator('.att-row'),target=rows.filter({hasText:'模拟浏览位置 22'});await target.scrollIntoViewIfNeeded();
  const position=()=>page.evaluate(()=>({window:window.scrollY,containers:[...document.querySelectorAll('main,.v2-content')].map(e=>({className:e.className,top:e.scrollTop}))}));
  const before={ids:await rows.evaluateAll(es=>es.map(e=>e.getAttribute('data-attention-id'))),position:await position(),top:await target.evaluate(e=>e.getBoundingClientRect().top)};
  assert.ok(before.position.window>0||before.position.containers.some(e=>e.top>0));await shot('17-list-before-save.png');await target.click();await panel().getByRole('button',{name:'记录进展 / 讨论',exact:true}).click();await message().fill('已收到初稿');await send().click();await returned();
  const after={ids:await rows.evaluateAll(es=>es.map(e=>e.getAttribute('data-attention-id'))),position:await position(),top:await target.evaluate(e=>e.getBoundingClientRect().top)};
  assert.equal(await page.getByLabel('按项目筛选待处理事项',{exact:true}).inputValue(),'p');assert.equal(await page.getByLabel('搜索待处理事项',{exact:true}).inputValue(),'模拟浏览位置');assert.deepEqual(after.ids,before.ids);assert.ok(Math.abs(after.top-before.top)<2,JSON.stringify({before,after}));await shot('18-list-after-save.png');return {filter:'p',query:'模拟浏览位置',before,after,sortControl:'页面使用原有优先级排序，无独立手动排序控件',scrollMeaning:'新增回执改变页面高度，scrollY可变；同一事项在视口的top误差须小于2像素' };
 });
 await check('boundary','隔离页面→真实HTTP→SQLite→回执，无真实外发',async()=>{assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.ok(!mutations.some(p=>/reminders|meeting|publish|feishu/.test(p)));assert.equal(state().actions.length,0);return {consoleErrors:errors,externalRequests:external,externalBusinessWrites:0};});
}finally{
 const release=(await(await fetch(app.origin+'/api/v2/status')).json()).release;
 writeFileSync(output+'/fix1-browser-results'+(selectedCases.length?'.'+selectedCases.join('-'):'')+'.json',JSON.stringify({scope:'real Chromium / local API / isolated SQLite; simulated model; synthetic records',release,results,screenshots,errors,external,mutations},null,2));await browser.close();await app.close();
}
