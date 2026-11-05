import assert from 'node:assert/strict';
import {mkdir, writeFile, access, readFile, mkdtemp} from 'node:fs/promises';
import {createReadStream, createWriteStream} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {dirname, join, basename} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {performance} from 'node:perf_hooks';
import {pipeline} from 'node:stream/promises';
import {createBrotliDecompress} from 'node:zlib';
import {extract} from 'tar-fs';
import {chromium as playwrightChromium} from 'playwright';
import {startDemo} from '../server/demo-server.mjs';

const root=dirname(dirname(fileURLToPath(import.meta.url)));
const verification=join(root,'verification');
const screenshots=join(verification,'screenshots');
await mkdir(screenshots,{recursive:true});
const report={syntheticOnly:true,realFeishuSending:false,startedAt:new Date().toISOString(),checks:[],metrics:{},screenshots:[],limitations:[
  'Browser interaction timings are measured rendering/operation timings, not a 30-second human reading acceptance.',
  'The standalone host theme is an inspected 2.17 product fallback; current 2.18.1 host parity remains an original-machine check.',
]};
let demo,browser,page;
const pageErrors=[],requests=[];
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function waitUntil(check,message,timeout=10000){
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline){if(await check())return;await sleep(40);}
  throw new Error(message);
}
async function check(name,fn){
  const started=performance.now();
  try{const details=await fn();report.checks.push({name,passed:true,durationMs:Math.round(performance.now()-started),...(details?{details}:{})});console.log('PASS '+name);}
  catch(error){report.checks.push({name,passed:false,durationMs:Math.round(performance.now()-started),error:error.stack||String(error)});throw error;}
}
async function screenshot(name){
  const path=join(screenshots,name+'.png');
  await page.screenshot({path,fullPage:true});
  report.screenshots.push('screenshots/'+name+'.png');
}
async function fourRows(){
  await page.locator('.lw-summary-row').nth(3).waitFor({state:'visible'});
  assert.equal(await page.locator('.lw-summary-row').count(),4);
  await page.evaluate(()=>document.fonts.ready);
}
async function selectProject(id,title){
  await page.getByRole('searchbox',{name:'搜索项目或项目外主题'}).fill('');
  await page.getByRole('combobox',{name:'选择项目或项目外主题'}).selectOption(id);
  await page.getByRole('heading',{level:2,name:title,exact:true}).waitFor({state:'visible'});
  await fourRows();
  assert.equal(page.url(),demo.origin+'/');
}
async function noOverflow(label){
  const dimensions=await page.evaluate(()=>{
    const width=window.innerWidth;
    const offenders=[...document.querySelectorAll('.ledger-workbench *')].filter(element=>{
      if(element.closest('.lw-sr-only'))return false;
      const r=element.getBoundingClientRect();
      return r.width>0&&(r.right>width+1||r.left< -1);
    }).slice(0,8).map(element=>({tag:element.tagName,className:element.className,text:element.textContent.slice(0,60),right:element.getBoundingClientRect().right}));
    return {viewport:width,scrollWidth:document.documentElement.scrollWidth,offenders};
  });
  assert.ok(dimensions.scrollWidth<=dimensions.viewport+1,label+': '+JSON.stringify(dimensions));
  assert.deepEqual(dimensions.offenders,[],label+': '+JSON.stringify(dimensions));
  return dimensions;
}
async function closePanel(){
  const close=page.getByRole('button',{name:'收起展开区'});
  if(await close.count())await close.click();
}

try{
  const build=execFileSync(process.execPath,['tools/build.mjs'],{cwd:root,encoding:'utf8'});
  report.build=build.trim();
  const {default:serverlessChromium}=await import('@sparticuz/chromium');
  const args=serverlessChromium.args.filter(arg=>!['--disable-web-security','--allow-running-insecure-content'].includes(arg));
  let executablePath,launchEnv;
  if(process.env.LEDGER_CHROMIUM_EXECUTABLE){
    executablePath=process.env.LEDGER_CHROMIUM_EXECUTABLE;
  }else{
    // Container uid mappings cannot restore archive-owner IDs. Extract the same installed
    // npm payload under the current uid, without changing isolation or restoring owners.
    const runtime=await mkdtemp(join(tmpdir(),'ledger-browser-runtime-'));
    const bin=join(dirname(fileURLToPath(import.meta.resolve('@sparticuz/chromium'))),'..','bin');
    executablePath=join(runtime,'chromium');
    await Promise.all([
      pipeline(createReadStream(join(bin,'chromium.br')),createBrotliDecompress(),createWriteStream(executablePath,{mode:0o700})),
      pipeline(createReadStream(join(bin,'fonts.tar.br')),createBrotliDecompress(),extract(join(runtime,'fonts'),{chown:false})),
      pipeline(createReadStream(join(bin,'swiftshader.tar.br')),createBrotliDecompress(),extract(runtime,{chown:false})),
      pipeline(createReadStream(join(bin,'al2023.tar.br')),createBrotliDecompress(),extract(join(runtime,'al2023'),{chown:false})),
    ]);
    // The Lambda fontconfig payload names /tmp/fonts. Point this isolated test runtime
    // at its actual extracted fonts and the installed system fonts instead.
    await writeFile(join(runtime,'fonts','fonts.conf'),
      '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'+
      '<dir>'+join(runtime,'fonts')+'</dir><dir>/usr/share/fonts</dir><dir>/usr/local/share/fonts</dir>'+
      '<cachedir>'+join(runtime,'font-cache')+'</cachedir></fontconfig>');
    launchEnv={...process.env,FONTCONFIG_PATH:join(runtime,'fonts'),
      LD_LIBRARY_PATH:[runtime,join(runtime,'al2023','lib'),process.env.LD_LIBRARY_PATH].filter(Boolean).join(':')};
    report.browserRuntime={sameInstalledPackage:true,archiveOwnersRestored:false};
  }
  await access(executablePath);
  demo=await startDemo();
  browser=await playwrightChromium.launch({executablePath,args,headless:true,...(launchEnv?{env:launchEnv}:{})});
  report.browserVersion=browser.version();
  const context=await browser.newContext({viewport:{width:1440,height:900},locale:'zh-CN',timezoneId:'Asia/Shanghai'});
  page=await context.newPage();
  if(process.env.LEDGER_FONT_PACKAGE){
    const fontRoot=process.env.LEDGER_FONT_PACKAGE;
    const css=(await readFile(join(fontRoot,'index.css'),'utf8')).replaceAll('./files/','/_ledger-test-font/');
    await page.route(demo.origin+'/_ledger-test-font.css',route=>route.fulfill({
      status:200,contentType:'text/css',body:css+'\n:root{font-family:"Noto Sans SC Variable",sans-serif;}',
    }));
    await page.route(demo.origin+'/_ledger-test-font/*',async route=>{
      const filename=basename(new URL(route.request().url()).pathname);
      const bytes=await readFile(join(fontRoot,'files',filename));
      await route.fulfill({status:200,contentType:'font/woff2',body:bytes});
    });
    report.syntheticScreenshotFont='Noto Sans SC Variable, loaded only through internal test routes';
  }
  page.on('pageerror',error=>pageErrors.push(error.message));
  page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/v2/ledger/'))requests.push({method:request.method(),path:url.pathname});});
  const loadStarted=performance.now();
  await page.goto(demo.origin+'/',{waitUntil:'domcontentloaded'});
  if(process.env.LEDGER_FONT_PACKAGE){
    await page.addStyleTag({url:demo.origin+'/_ledger-test-font.css'});
    await page.evaluate(()=>document.fonts.ready);
  }

  await check('Desktop: four summary rows appear in the first viewport',async()=>{
    await fourRows();
    report.metrics.initialFourRowsRenderMs=Math.round(performance.now()-loadStarted);
    assert.deepEqual(await page.locator('.lw-summary dt').allTextContents(),['计划','进展','卡点','我的待办']);
    const boxes=await page.locator('.lw-summary-row').evaluateAll(rows=>rows.map(row=>{const r=row.getBoundingClientRect();return{top:r.top,bottom:r.bottom};}));
    assert.ok(boxes.every(box=>box.top>=0&&box.bottom<=900),JSON.stringify(boxes));
    const dimensions=await noOverflow('desktop default');
    await screenshot('desktop-four-rows');
    return{boxes,dimensions};
  });

  await check('The component inherits host font, text color and line tokens',async()=>{
    await page.route(demo.origin+'/_ledger-theme-probe.css',route=>route.fulfill({
      status:200,contentType:'text/css',body:'.v2-button{color:rgb(87,65,43);font-family:"Courier New",monospace;}',
    }));
    await page.addStyleTag({url:demo.origin+'/_ledger-theme-probe.css'});
    const result=await page.evaluate(()=>{
      const host=document.querySelector('.demo-host'),app=document.querySelector('.ledger-workbench');
      const previous=host.getAttribute('style');
      host.style.fontFamily='"Courier New", monospace';
      host.style.color='rgb(23, 45, 67)';
      host.style.setProperty('--v2-line','#123456');
      host.style.setProperty('--v2-muted','#567890');
      const probe=document.createElement('section');
      probe.className='ledger-workbench';
      const hostButton=document.createElement('button');
      hostButton.className='v2-button';
      hostButton.textContent='Theme inheritance probe';
      probe.append(hostButton);document.body.append(probe);
      const result={hostFont:getComputedStyle(host).fontFamily,appFont:getComputedStyle(app).fontFamily,
        color:getComputedStyle(app).color,line:getComputedStyle(document.querySelector('.lw-summary')).borderTopColor,
        muted:getComputedStyle(document.querySelector('.lw-project-heading .lw-muted')).color,
        nativeButtonColor:getComputedStyle(hostButton).color,nativeButtonFont:getComputedStyle(hostButton).fontFamily};
      probe.remove();
      if(previous===null)host.removeAttribute('style');else host.setAttribute('style',previous);
      return result;
    });
    assert.equal(result.appFont,result.hostFont);
    assert.equal(result.color,'rgb(23, 45, 67)');
    assert.equal(result.line,'rgb(18, 52, 86)');
    assert.equal(result.muted,'rgb(86, 120, 144)');
    assert.equal(result.nativeButtonColor,'rgb(87, 65, 43)');
    assert.ok(result.nativeButtonFont.includes('Courier New'));
    return result;
  });

  await check('Project search and switch stay on the same URL',async()=>{
    await page.getByRole('searchbox',{name:'搜索项目或项目外主题'}).fill('软件');
    await page.getByRole('combobox',{name:'选择项目或项目外主题'}).selectOption('demo-release');
    await page.getByRole('heading',{level:2,name:'软件发布 · 示例',exact:true}).waitFor();
    await fourRows();
    assert.equal(page.url(),demo.origin+'/');
  });

  await check('Wait recommendation has no external-send confirmation',async()=>{
    const approvals=demo.bridge.calls.filter(call=>call.method==='approve').length;
    await page.getByRole('button',{name:'请 AM 建议下一步',exact:true}).click();
    await page.getByLabel('要跟进哪件事',{exact:true}).selectOption('demo-rollout');
    await page.getByRole('button',{name:'获取建议',exact:true}).click();
    await page.getByRole('heading',{name:'按原发布窗口等待即可。',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'确认并执行本次跟进',exact:true}).count(),0);
    assert.equal(demo.bridge.calls.filter(call=>call.method==='approve').length,approvals);
    await screenshot('desktop-wait');
  });

  await check('AM prepare, present, edit, re-preview, approve and original-receipt query',async()=>{
    await selectProject('demo-sample','样机验证 · 示例');
    await page.getByRole('button',{name:'请 AM 建议下一步',exact:true}).click();
    await page.getByLabel('要跟进哪件事',{exact:true}).selectOption('demo-bench');
    await page.getByRole('button',{name:'获取建议',exact:true}).click();
    const confirm=page.getByRole('button',{name:'确认并执行本次跟进',exact:true});
    await waitUntil(()=>confirm.isEnabled(),'Initial preview was not presented');
    const firstPreview=[...demo.bridge.previews.keys()].at(-1);
    const original=await page.getByLabel('消息正文',{exact:true}).inputValue();
    const edited=original+' 请一并说明预计开测日期。';
    await page.getByLabel('消息正文',{exact:true}).fill(edited);
    assert.equal(await confirm.count(),0);
    const amCalls=demo.bridge.calls.filter(call=>['prepare','revise','present','approve'].includes(call.method)).length;
    const getCount=requests.filter(request=>request.method==='GET').length;
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await waitUntil(()=>requests.filter(request=>request.method==='GET').length>getCount,'Focus did not refresh read projection');
    await waitUntil(async()=>!(await page.locator('.lw-busy').count()),'Focus refresh did not settle');
    assert.equal(await page.getByLabel('消息正文',{exact:true}).inputValue(),edited);
    assert.equal(demo.bridge.calls.filter(call=>['prepare','revise','present','approve'].includes(call.method)).length,amCalls);
    await page.getByRole('button',{name:'更新预览',exact:true}).click();
    await waitUntil(()=>confirm.isEnabled(),'Edited preview was not re-presented');
    const revisedPreview=[...demo.bridge.previews.keys()].at(-1);
    assert.notEqual(revisedPreview,firstPreview);
    assert.equal(demo.bridge.previews.get(firstPreview).superseded,true);
    assert.equal(demo.bridge.previews.get(revisedPreview).preview.body,edited);
    await screenshot('desktop-am-preview');
    const stateBefore=demo.bridge.snapshot.items.find(item=>item.id==='demo-bench').businessState;
    await confirm.click();
    await page.getByRole('heading',{name:'已进入执行队列',exact:true}).waitFor();
    assert.equal(demo.bridge.calls.filter(call=>call.method==='approve').length,1);
    const requestId=[...demo.bridge.receipts.keys()][0];
    assert.ok(requestId);
    await page.getByRole('button',{name:'查询原请求回执',exact:true}).click();
    await waitUntil(()=>demo.bridge.calls.some(call=>call.method==='status'),'Original receipt was not queried');
    assert.ok(requests.some(request=>request.method==='GET'&&request.path==='/api/v2/ledger/am/receipts/'+requestId));
    assert.equal(demo.bridge.snapshot.items.find(item=>item.id==='demo-bench').businessState,stateBefore);
    assert.equal(demo.bridge.snapshot.items.find(item=>item.id==='demo-bench').businessState,'open');
    assert.equal(demo.bridge.receipts.get(requestId).messageId,null);
    await screenshot('desktop-am-receipt');
    return{requestId,simulatedReceiptState:demo.bridge.receipts.get(requestId).state,businessState:stateBefore};
  });

  await check('An ambiguous fragment is associated through its explicit review choice',async()=>{
    const review=demo.bridge.snapshot.reviews.find(review=>review.status==='pending');
    assert.ok(review);
    await page.getByRole('button',{name:/^待我判断/}).click();
    await page.getByLabel('选择这条疑点的处理方式').selectOption('demo-outside');
    await page.getByRole('button',{name:'确认这条判断',exact:true}).click();
    await waitUntil(()=>demo.bridge.snapshot.reviews.find(row=>row.id===review.id)?.status==='resolved','Review was not persisted');
    assert.equal(demo.bridge.snapshot.reviews.find(row=>row.id===review.id).projectId,'demo-outside');
    assert.ok(demo.bridge.snapshot.facts.filter(fact=>review.factIds.includes(fact.id)).every(fact=>fact.projectId==='demo-outside'));
    assert.equal(demo.bridge.calls.filter(call=>call.method==='approve').length,1);
    await selectProject('demo-outside','模板协同 · 项目外示例');
    assert.equal(page.url(),demo.origin+'/');
    await screenshot('desktop-outside-theme');
  });

  await check('Reminder locate, read and snooze update display state without closing the item',async()=>{
    await page.getByRole('button',{name:/^需关注/}).click();
    await page.getByRole('button',{name:'定位',exact:true}).click();
    await page.getByRole('heading',{level:2,name:'样机验证 · 示例',exact:true}).waitFor();
    assert.ok(await page.locator('.lw-located').count());
    assert.equal(page.url(),demo.origin+'/');
    await page.getByRole('button',{name:/^需关注/}).click();
    await page.getByRole('button',{name:'已读',exact:true}).click();
    await waitUntil(()=>demo.bridge.snapshot.reminders[0].displayState==='read','Reminder was not marked read');
    await waitUntil(async()=>!(await page.getByRole('button',{name:'稍后 1 小时',exact:true}).isDisabled()),'Reminder mutation did not settle');
    await page.getByRole('button',{name:'稍后 1 小时',exact:true}).click();
    await waitUntil(()=>demo.bridge.snapshot.reminders[0].displayState==='snoozed','Reminder was not snoozed');
    assert.equal(demo.bridge.snapshot.reminders[0].businessState,'open');
    assert.equal(demo.bridge.snapshot.items.find(item=>item.id==='demo-bench').businessState,'open');
    await page.getByText('此提醒暂缓显示 1 小时；原期限保留。',{exact:true}).waitFor();
    await screenshot('desktop-reminder');
  });

  await check('Ordinary read failure retains the last four rows with a visible gap',async()=>{
    await closePanel();
    const before=await page.locator('.lw-summary').innerText();
    const abortReads=route=>route.request().method()==='GET'?route.abort('failed'):route.continue();
    await page.route('**/api/v2/ledger/**',abortReads);
    await page.getByRole('button',{name:'刷新台账',exact:true}).click();
    await page.getByText('最新资料暂未读到，以下保留上次读取结果。',{exact:true}).waitFor();
    assert.equal(await page.locator('.lw-summary').innerText(),before);
    await page.unroute('**/api/v2/ledger/**',abortReads);
    await page.getByRole('button',{name:'重新读取',exact:true}).click();
    await waitUntil(async()=>!(await page.getByText('最新资料暂未读到，以下保留上次读取结果。',{exact:true}).count()),'Read gap did not recover');
  });

  await check('Access denial clears old summary, raw evidence and AM presentation',async()=>{
    for(const [status,code] of [[403,'WEB_SCOPE_DENIED'],[409,'WEB_SOURCE_ACCESS_CHANGED'],[401,'authentication_required']]){
      await page.locator('[data-row="progress"] .lw-row-more').click();
      const expand=page.locator('.lw-source-entry details summary').first();
      await expand.click();
      assert.ok(await page.locator('.lw-panel blockquote').count());
      const deniedReads=route=>route.request().method()==='GET'
        ?route.fulfill({status,contentType:'application/json',body:JSON.stringify({error:{code,message:'合成测试：来源访问范围已变化'}})})
        :route.continue();
      await page.route('**/api/v2/ledger/**',deniedReads);
      await page.getByRole('button',{name:'刷新台账',exact:true}).click();
      await page.getByRole('heading',{name:'访问范围需要重新核对',exact:true}).waitFor();
      assert.equal(await page.locator('.lw-summary').count(),0);
      assert.equal(await page.locator('.lw-panel').count(),0);
      assert.equal(await page.locator('.lw-preview').count(),0);
      assert.ok(!(await page.locator('.ledger-workbench').innerText()).includes('样机和方案已齐'));
      await page.unroute('**/api/v2/ledger/**',deniedReads);
      await page.getByRole('button',{name:'重新核对访问',exact:true}).click();
      await fourRows();
    }
  });

  await check('Expired excerpt copies disappear while structured facts and review count remain',async()=>{
    const boundText='仅用于到期核验的原文复制';
    const gapText='尚未归类的处理缺口原文';
    const ordinaryText='结构化状态仍需保留';
    const beforeReviews=await page.getByRole('button',{name:/^待我判断/}).innerText();
    const injectRetention=async route=>{
      const response=await route.fetch();
      const dto=await response.json();
      const expiry=new Date(Date.now()+1800).toISOString();
      const evidence=quote=>({sourceId:'synthetic-retention',objectId:'retention-proof',version:'1',quote,rawAvailable:true,
        rawExpiresAt:expiry,verification:'verbatim_at_extraction',url:null,occurredAt:null,receivedAt:null,stale:false});
      const progress=dto.rows.find(row=>row.key==='progress');
      progress.entries=[
        {id:'structured-state',itemId:null,text:ordinaryText,certainty:'source_confirmed',critical:false,sourceRefs:[evidence('结构化事实的来源原文')]},
        {id:'retained-copy',itemId:null,text:boundText,certainty:'reported',critical:false,sourceRefs:[evidence(boundText)],retentionBoundExcerpt:true,rawExcerptUnavailable:false},
      ];
      progress.moreEntries=[];
      progress.text=progress.entries.map(entry=>entry.text).join('；');
      dto.details.processingGaps=[{id:'synthetic-processing-gap',kind:'processing',projectIds:[dto.project.id],reason:'待进一步处理',
        gapCode:'synthetic',text:gapText,retentionBoundExcerpt:true,rawExcerptUnavailable:false,sourceRefs:[evidence(gapText)]}];
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(dto)});
    };
    await page.route('**/api/v2/ledger/projects/demo-sample',injectRetention);
    await page.getByRole('button',{name:'刷新台账',exact:true}).click();
    await waitUntil(async()=>(await page.locator('[data-row="progress"]').innerText()).includes(boundText),'Synthetic bound excerpt did not appear');
    await page.locator('[data-row="progress"] .lw-row-more').click();
    await page.getByRole('heading',{name:'待整理信息',exact:true}).waitFor();
    await waitUntil(async()=>!(await page.locator('.ledger-workbench').innerText()).includes(boundText)
      &&!(await page.locator('.ledger-workbench').innerText()).includes(gapText),'Expired raw copies remained visible');
    assert.ok((await page.locator('[data-row="progress"]').innerText()).includes(ordinaryText));
    assert.ok((await page.locator('.ledger-workbench').innerText()).includes('原文暂不可用，待刷新'));
    assert.equal(await page.getByRole('button',{name:/^待我判断/}).innerText(),beforeReviews);
    await page.unroute('**/api/v2/ledger/projects/demo-sample',injectRetention);
    await closePanel();
    await page.getByRole('button',{name:'刷新台账',exact:true}).click();
    await waitUntil(async()=>!(await page.locator('.lw-summary').innerText()).includes(ordinaryText),'Original projection did not return');
  });

  await check('Desktop 1440 and phones 390/320 have no horizontal overflow',async()=>{
    const sizes=[];
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:width===1440?900:844});
      await selectProject('demo-outside','模板协同 · 项目外示例');
      await closePanel();
      await page.evaluate(()=>window.scrollTo(0,0));
      sizes.push({view:'summary',...await noOverflow(width+' summary')});
      await screenshot('layout-'+width+'-summary');
      await page.getByRole('button',{name:'请 AM 建议下一步',exact:true}).click();
      if(!(await page.getByLabel('消息正文',{exact:true}).count())){
        await page.getByLabel('要跟进哪件事',{exact:true}).selectOption('demo-template');
        await page.getByRole('button',{name:'获取建议',exact:true}).click();
        await waitUntil(()=>page.getByRole('button',{name:'确认并执行本次跟进',exact:true}).isEnabled(),'Responsive AM preview did not settle');
      }
      sizes.push({view:'am',...await noOverflow(width+' AM')});
      await screenshot('layout-'+width+'-am');
      await page.getByRole('button',{name:/^需关注/}).click();
      sizes.push({view:'reminders',...await noOverflow(width+' reminders')});
      await screenshot('layout-'+width+'-reminders');
    }
    assert.equal(demo.bridge.calls.filter(call=>call.method==='approve').length,1);
    return sizes;
  });
  assert.deepEqual(pageErrors,[]);
  report.requestCounts={get:requests.filter(request=>request.method==='GET').length,post:requests.filter(request=>request.method==='POST').length};
  report.externalSends=0;
  report.passed=true;
}catch(error){
  report.passed=false;
  report.failure=error.stack||String(error);
  console.error(report.failure);
  if(page){try{await screenshot('failure');}catch{}}
  process.exitCode=1;
}finally{
  report.pageErrors=pageErrors;
  report.finishedAt=new Date().toISOString();
  await writeFile(join(verification,'browser-report.json'),JSON.stringify(report,null,2)+'\n');
  if(browser)await browser.close();
  if(demo)await demo.close();
}

