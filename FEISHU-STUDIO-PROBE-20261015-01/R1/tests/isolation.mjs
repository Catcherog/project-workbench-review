import fs from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {createServer} from 'node:http';
import assert from 'node:assert/strict';
import {permissionArgs,processRun} from '../src/codex.mjs';
const root=resolve('runtime/isolation'),job=join(root,'session-a');
await fs.mkdir(job,{recursive:true});await fs.mkdir(join(root,'session-b'),{recursive:true});
const marker=randomUUID(),outside=join(root,'session-b','sentinel.txt');
await fs.writeFile(join(job,'allowed.txt'),'SYNTHETIC_ALLOWED_'+marker);await fs.writeFile(outside,'SYNTHETIC_FORBIDDEN_'+marker);
try{await fs.symlink(outside,join(job,'escape'));}catch{}
const binary=process.env.PROBE_CODEX_BIN||'codex',records=[];
async function check(name,cmd,ok){const r=await processRun(binary,['sandbox','-P','probe',...permissionArgs(job),'-C',job,...cmd],{cwd:job,timeoutMs:10000});records.push({name,exit:r.exit,stdout:r.stdout,stderr:r.stderr});assert.equal(r.exit===0,ok,name);return r;}
try{
 const allowed=await check('own_synthetic_file',['/bin/cat',join(job,'allowed.txt')],true);assert.match(allowed.stdout,/SYNTHETIC_ALLOWED_/);
 await check('other_session_file',['/bin/cat',outside],false);
 await check('symlink_escape',['/bin/cat',join(job,'escape')],false);
 await check('outside_directory_listing',['/bin/ls',root],false);
 const server=createServer((q,s)=>s.end('should-not-connect'));await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{await check('local_network_denied',['/usr/bin/curl','--max-time','2','http://127.0.0.1:'+server.address().port],false);}finally{server.close();}
 await fs.mkdir('evidence',{recursive:true});
 await fs.writeFile('evidence/isolation.json',JSON.stringify({at:new Date().toISOString(),kind:'real_local_sandbox',passed:true,records},null,2));
 console.log(JSON.stringify({passed:true,checks:records.map(x=>({name:x.name,exit:x.exit}))}));
}catch(e){await fs.writeFile('evidence/isolation.json',JSON.stringify({passed:false,error:e.message,records},null,2));throw e;}
