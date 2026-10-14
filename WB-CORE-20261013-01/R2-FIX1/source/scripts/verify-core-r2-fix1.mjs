import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import path from 'node:path';

const output=path.resolve('output/r2-fix1/verification-'+new Date().toISOString().replaceAll(':','-'));mkdirSync(output,{recursive:true});
const paths=['lib/work-item-core.ts','lib/work-items.ts','scripts/work-item-core-service.mjs','scripts/core-feishu-input.mjs','scripts/test-core-r2-fix1.mjs','scripts/test-core-p1-p5.mjs','scripts/test-core-feishu.mjs','scripts/verify-core-r2-fix1.mjs','package.json','package-lock.json','release.json'];
const summary={startedAt:new Date().toISOString(),baseline:'012b89173cebfcdfafd1cb011d42ab97237c554b',release:JSON.parse(readFileSync('release.json')),scope:'isolated product regression; synthetic model, calendar and transport; no production or live business writes',source:paths.map(p=>({path:p,sha256:createHash('sha256').update(readFileSync(p)).digest('hex')})),checks:[]};
function save(){writeFileSync(output+'/summary.json',JSON.stringify(summary,null,2));writeFileSync('output/r2-fix1/latest-verification.json',JSON.stringify({directory:output,...summary},null,2));}
async function run(name,cmd,args){
  const start=Date.now();let log='';const exitCode=await new Promise(resolve=>{const child=spawn(cmd,args,{shell:false,stdio:['ignore','pipe','pipe'],env:{...process.env,PM_R2_OUTPUT:output+'/targeted'}});child.stdout.on('data',d=>log+=d);child.stderr.on('data',d=>log+=d);child.on('error',e=>{log+=e.stack;resolve(-1);});child.on('close',resolve);});
  writeFileSync(output+'/'+name+'.log',log);summary.checks.push({name,command:[cmd,...args],exitCode,passed:exitCode===0,durationMs:Date.now()-start,assertionGroups:log.split('\n').filter(l=>l.startsWith('PASS ')).length,log:name+'.log'});save();console.log(exitCode===0?'PASS':'FAIL',name);if(exitCode!==0)throw Error(name+' failed; inspect '+output+'/'+name+'.log');
}
try{
  await run('build','npm',['run','build']);await run('typecheck','npm',['run','typecheck']);
  await run('lint','node_modules/.bin/eslint',['lib/work-item-core.ts','lib/work-items.ts']);
  for(const p of paths.filter(p=>p.endsWith('.mjs')))await run('syntax-'+path.basename(p,'.mjs'),'node',['--check',p]);
  await run('targeted','node',['scripts/test-core-r2-fix1.mjs']);
  for(const name of ['core-p1-p5','core-runtime','core-feishu','core-input','core-work-agent','core-chain','s1p1-domain','s1p1-fix1-domain','s1p1-http','work-items','core-browser'])await run(name,'node',['scripts/test-'+name+'.mjs']);
  summary.status='passed';
}catch(error){summary.status='failed';summary.error=error.message;process.exitCode=1;}finally{summary.finishedAt=new Date().toISOString();save();console.log('Verification evidence:',output);}
