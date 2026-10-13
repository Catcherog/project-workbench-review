import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdirSync,readFileSync,writeFileSync,readdirSync,statSync} from 'node:fs';
import path from 'node:path';
const output=path.resolve('output/core-p1-p5-r1/verification-'+new Date().toISOString().replaceAll(':','-'));mkdirSync(output,{recursive:true});
const files=[];for(const dir of ['app','lib','scripts']){const walk=p=>{for(const n of readdirSync(p)){const f=path.join(p,n);if(statSync(f).isDirectory())walk(f);else if(/\.(ts|tsx|mjs|py|css)$/.test(f))files.push(f);}};walk(dir);}
const productHash=createHash('sha256');for(const f of files.sort())productHash.update(f).update(readFileSync(f));
const summary={startedAt:new Date().toISOString(),release:JSON.parse(readFileSync('release.json')),productTreeSha256:productHash.digest('hex'),scope:'isolated fixtures only; no production mutation; real-model evidence is reported separately',checks:[]};
function save(){writeFileSync(output+'/summary.json',JSON.stringify(summary,null,2));writeFileSync('output/core-p1-p5-r1/latest-verification.json',JSON.stringify({directory:output,...summary},null,2));}
async function run(name,cmd,args){const start=Date.now();let log='';const code=await new Promise(resolve=>{const p=spawn(cmd,args,{shell:false,stdio:['ignore','pipe','pipe']});p.stdout.on('data',d=>log+=d);p.stderr.on('data',d=>log+=d);p.on('error',e=>{log+=e.stack;resolve(-1);});p.on('close',c=>resolve(c));});writeFileSync(output+'/'+name+'.log',log);summary.checks.push({name,command:[cmd,...args],exitCode:code,passed:code===0,durationMs:Date.now()-start,assertionGroups:log.split('\n').filter(l=>l.startsWith('PASS ')).length,log:name+'.log'});save();console.log(code===0?'PASS':'FAIL',name);if(code!==0)throw Error(name+' failed; see '+output+'/'+name+'.log');}
try{
 await run('build','npm',['run','build']);await run('types','npm',['run','typecheck']);
 await run('static','node_modules/.bin/eslint',['app/core-preparation-result.tsx','app/input-images.tsx','app/core-schedule-settings.tsx','app/work-item-core-controls.tsx','app/work-item-entry.tsx','app/codex-assistant.tsx','app/work-item-panel.tsx','lib/core-reconcile.ts','lib/work-calendar.ts','lib/work-item-core.ts','lib/work-item-dependencies.ts','lib/work-item-collaboration.ts']);
 for(const file of ['scripts/core-input.mjs','scripts/core-work-agent.mjs','scripts/core-work-schema.mjs','scripts/core-collaboration.mjs','scripts/core-feishu-input.mjs','scripts/work-item-core-service.mjs','scripts/local-http.mjs','scripts/codex-assistant.mjs','scripts/feishu-event-bridge.mjs'])await run('syntax-'+path.basename(file,'.mjs'),'node',['--check',file]);
 await run('followup-bundle','node',['scripts/followup-build.mjs']);
 const groups=[['core-p1-p5','core-runtime','s1p1-domain','s1p1-fix1-domain','work-items','followup-boundaries','followup-lifecycle','feishu-event-bridge','feishu-sync-service'],['core-input','core-work-agent','core-feishu','core-chain','s1p1-http','task-review-reminders'],['core-browser','s1p1-browser']];
 const results=await Promise.allSettled(groups.map(async group=>{for(const name of group)await run(name,'node',['scripts/test-'+name+'.mjs']);}));
 const failed=results.find(r=>r.status==='rejected');if(failed)throw failed.reason;
 // Followup bundle is a test helper; deliver the normal application bundle.
 await run('final-build','npm',['run','build']);summary.status='passed';
}catch(error){summary.status='failed';summary.error=error.message;process.exitCode=1;}finally{summary.finishedAt=new Date().toISOString();save();console.log('Verification evidence:',output);}
