import fs from 'node:fs/promises';import {resolve,join} from 'node:path';import {randomUUID} from 'node:crypto';import {createServer} from 'node:http';import assert from 'node:assert/strict';
import {permissionArgs,hash,processRun} from '../src/codex.mjs';import {classifyReadEvidence,exactReadCommands} from '../src/isolation-evidence.mjs';
const root=resolve('runtime/isolation-'+randomUUID()),job=join(root,'session-a');await fs.mkdir(job,{recursive:true});await fs.mkdir(join(root,'session-b'));
const content='NON_SECRET_CANARY_'+randomUUID(),allowed=join(job,'allowed.txt'),outside=join(root,'session-b','sentinel.txt'),link=join(job,'escape');
await fs.writeFile(allowed,content);await fs.writeFile(outside,content);await fs.symlink(outside,link);
assert.equal((await fs.stat(outside)).isFile(),true);assert.equal((await fs.lstat(link)).isSymbolicLink(),true);assert.equal(await fs.realpath(link),await fs.realpath(outside));
const binary=process.env.PROBE_CODEX_BIN;if(!binary||!binary.startsWith('/'))throw Error('EXPLICIT_CODEX_BINARY_REQUIRED');
const executorFingerprint=hash(await fs.readFile('/bin/cat')),permissionFingerprint=hash(permissionArgs(job)),records=[];
async function restricted(command){const args=['sandbox','-P','probe',...permissionArgs(job),'-C',job,...command];const r=await processRun(binary,args,{cwd:job,timeoutMs:10000});return {r,args};}
async function readCheck(name,target,status){
 const runId=randomUUID(),canonicalTarget=await fs.realpath(target),{r,args}=await restricted(['/bin/cat','--',target]);
 assert.deepEqual(args.slice(-3),['/bin/cat','--',target]);
 const expected={runId,targetAlias:name,target,canonicalTarget,canonicalVerified:true,targetExisted:(await fs.stat(target)).isFile(),contentSha256:hash(content),executorFingerprint,permissionFingerprint,launchFingerprint:hash(args)};
 const receipt={runId,launchFingerprint:hash(args),permissionFingerprint,executorFingerprint,terminationConfirmed:r.terminationConfirmed,stopReason:r.stopReason,commandTelemetry:'complete',origin:'controller_initiated_system_sandbox_not_model_tool',events:[{type:'item.completed',item:{id:runId,type:'command_execution',command:exactReadCommands(target)[0],status:'completed',exit_code:r.exit,aggregated_output:r.stdout+r.stderr}}]};
 const verdict=classifyReadEvidence(expected,receipt);records.push({name,expected,receipt,verdict,exit:r.exit});assert.equal(verdict.status,status,name);
}
let server;
try{
 await readCheck('own_file',allowed,'read_succeeded');await readCheck('other_session',outside,'denied');await readCheck('symlink_escape',link,'denied');
 assert.equal((await fs.stat(root)).isDirectory(),true);const listing=await restricted(['/bin/ls',root]);
 assert.equal(listing.r.stopReason,'');assert.equal(listing.r.terminationConfirmed,true);assert.equal(listing.r.exit,1);assert.ok(['Operation not permitted','Permission denied'].some(x=>listing.r.stderr===`ls: ${root}: ${x}\n`));records.push({name:'outside_directory',kind:'real_system_command',target:root,exit:listing.r.exit,stderr:listing.r.stderr,permissionFingerprint});
 let requests=0;const nonce=randomUUID();server=createServer((q,s)=>{requests++;s.end(nonce);});await new Promise(r=>server.listen(0,'127.0.0.1',r));const endpoint='http://127.0.0.1:'+server.address().port+'/canary';
 const cmd=['/usr/bin/curl','-q','--silent','--show-error','--max-time','2',endpoint];
 const before=await processRun(cmd[0],cmd.slice(1),{timeoutMs:5000});assert.equal(before.exit,0);assert.equal(before.stdout,nonce);assert.equal(requests,1);
 const during=await restricted(cmd);assert.equal(during.r.stopReason,'');assert.equal(during.r.terminationConfirmed,true);assert.equal(during.r.exit,7);assert.equal(requests,1);
 const after=await processRun(cmd[0],cmd.slice(1),{timeoutMs:5000});assert.equal(after.exit,0);assert.equal(after.stdout,nonce);assert.equal(requests,2);
 records.push({name:'same_endpoint_network_control',endpointAlias:'OWN_LOOPBACK_CANARY',before:{exit:before.exit,matchedNonce:true,serverRequests:1},restricted:{exit:during.r.exit,serverRequests:1,terminationConfirmed: true},after:{exit:after.exit,matchedNonce:true,serverRequests:2},scope:'single local command endpoint; not model transport or all network destinations'});
 await fs.mkdir('evidence/fix1',{recursive:true});await fs.writeFile('evidence/fix1/system-isolation.json',JSON.stringify({passed:true,kind:'real_system_sandbox_no_model',at:new Date().toISOString(),records},null,2));console.log(JSON.stringify({passed:true,checks:records.length,realModelCalls:0}));
}catch(e){await fs.mkdir('evidence/fix1',{recursive:true});await fs.writeFile('evidence/fix1/system-isolation.json',JSON.stringify({passed:false,error:e.message,records},null,2));throw e;}finally{if(server)await new Promise(r=>server.close(r));}
