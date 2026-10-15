import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {fileURLToPath} from 'node:url';
const budgetPath=fileURLToPath(new URL('../runtime/model-budget.sqlite',import.meta.url));
export const hash=x=>createHash('sha256').update(typeof x==='string'?x:JSON.stringify(x)).digest('hex');
export const cleanEnv=()=>Object.fromEntries(['HOME','USER','LOGNAME','LANG','TMPDIR'].filter(k=>process.env[k]).map(k=>[k,process.env[k]]).concat([['PATH','/usr/bin:/bin:/usr/sbin:/sbin']]));
export function permissionArgs(jobDir){
  const policy={':root':'deny',':minimal':'read',[resolve(jobDir)]:'read'};
  const toml='{'+Object.entries(policy).map(([k,v])=>JSON.stringify(k)+'='+JSON.stringify(v)).join(',')+'}';
  return ['-c','default_permissions="probe"','-c','permissions.probe.filesystem='+toml,'-c','permissions.probe.network.enabled=false'];
}
export function processRun(binary,args,{cwd,input='',timeoutMs=180000,maxBytes=5242880,env=cleanEnv(),onRecord}={}){
  return new Promise((accept,reject)=>{
    const startedAt=new Date().toISOString(),child=spawn(binary,args,{cwd,env,stdio:['pipe','pipe','pipe'],shell:false,detached:true});
    let stdout='',stderr='',bytes=0,line='',stopReason='',termTimer;
    const kill=reason=>{if(stopReason)return;stopReason=reason;try{process.kill(-child.pid,'SIGTERM');}catch{}termTimer=setTimeout(()=>{try{process.kill(-child.pid,'SIGKILL');}catch{}},1500);};
    const timer=setTimeout(()=>kill('timeout'),timeoutMs);
    child.stdout.on('data',b=>{bytes+=b.length;if(bytes>maxBytes)return kill('output_limit');stdout+=b;line+=b;let p;while((p=line.indexOf('\n'))>=0){const s=line.slice(0,p);line=line.slice(p+1);try{onRecord?.(JSON.parse(s));}catch{}}});
    child.stderr.on('data',b=>{bytes+=b.length;if(bytes>maxBytes)return kill('output_limit');stderr+=b;});
    child.once('error',e=>{clearTimeout(timer);clearTimeout(termTimer);reject(e);});
    child.once('close',(exit,signal)=>{clearTimeout(timer);clearTimeout(termTimer);accept({pid:child.pid,startedAt,endedAt:new Date().toISOString(),exit,signal,stopReason,stdout,stderr});});
    child.stdin.on('error',()=>{});child.stdin.end(input);
  });
}
export function execArgs({jobDir,outputFile,schemaFile,model='gpt-6-astra',effort='max'}){
  const disabled=['apps','plugins','remote_plugin','browser_use','browser_use_external','in_app_browser','computer_use','multi_agent','multi_agent_v2','memories','chronicle','hooks','skill_search','skill_mcp_dependency_install','image_generation','view_image','sleep_tool'];
  return ['exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check','--json','--color','never','-C',jobDir,
    ...permissionArgs(jobDir),'-c','approval_policy="never"','-c','project_doc_max_bytes=0','-c','mcp_servers={}','-c','web_search="disabled"','-c','features.skip_host_skill_discovery=true',
    '-c','shell_environment_policy.inherit="none"','-c','shell_environment_policy.set={PATH="/usr/bin:/bin:/usr/sbin:/sbin"}','-c','model_reasoning_effort='+JSON.stringify(effort),'-m',model,
    ...disabled.flatMap(f=>['--disable',f]),'--output-schema',schemaFile,'--output-last-message',outputFile,'-'];
}
export const resultSchema={type:'object',additionalProperties:false,required:['marker','summary','missing','question'],properties:{marker:{type:'string'},summary:{type:'string'},missing:{type:'array',items:{type:'string'}},question:{type:'string'}}};
export async function runCodex({binary,jobDir,prompt,marker,model,effort,timeoutMs=180000}){
  if(timeoutMs<1||timeoutMs>180000)throw Error('INVALID_TIMEOUT');
  await fs.mkdir(resolve(budgetPath,'..'),{recursive:true,mode:0o700});
  const budget=new DatabaseSync(budgetPath);budget.exec('CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,at TEXT,state TEXT);');
  if(!budget.prepare('PRAGMA table_info(calls)').all().some(x=>x.name==='state'))budget.exec("ALTER TABLE calls ADD COLUMN state TEXT DEFAULT 'finished';");
  budget.exec('BEGIN IMMEDIATE;');
  if(budget.prepare('SELECT count(*) AS n FROM calls').get().n>=20){budget.exec('ROLLBACK');budget.close();throw Error('ROUND_CALL_LIMIT');}
  if(budget.prepare("SELECT count(*) AS n FROM calls WHERE state='running'").get().n>=2){budget.exec('ROLLBACK');budget.close();throw Error('ROUND_CONCURRENCY_LIMIT');}
  const callId=budget.prepare("INSERT INTO calls(at,state) VALUES(?,'running')").run(new Date().toISOString()).lastInsertRowid;budget.exec('COMMIT');budget.close();
  try{
  await fs.mkdir(jobDir,{recursive:true,mode:0o700});
  const schemaFile=join(jobDir,'schema.json'),outputFile=join(jobDir,'final.json');
  await fs.writeFile(schemaFile,JSON.stringify(resultSchema),{mode:0o600});
  const events=[];
  const onRecord=e=>{
    if(['thread.started','turn.started','turn.completed','turn.failed','error'].includes(e.type))events.push(e);
    // Do not persist reasoning items. Commands contain only synthetic test data.
    if(['item.started','item.completed','item.failed'].includes(e.type)&&['command_execution','agent_message'].includes(e.item?.type))events.push(e);
  };
  const args=execArgs({jobDir,outputFile,schemaFile,model,effort});
  const r=await processRun(binary,args,{cwd:jobDir,input:prompt,timeoutMs,onRecord});
  let result;try{result=JSON.parse(await fs.readFile(outputFile,'utf8'));}catch{}
  const completed=events.some(e=>e.type==='turn.completed'),failed=events.some(e=>['turn.failed','error'].includes(e.type));
  const valid=result&&Object.keys(result).sort().join(',')==='marker,missing,question,summary'&&result.marker===marker&&typeof result.summary==='string'&&result.summary.length<=1800&&typeof result.question==='string'&&result.question.length<=500&&Array.isArray(result.missing)&&result.missing.every(x=>typeof x==='string'&&x.length<200);
  const implementationSha256=hash(await fs.readFile(new URL(import.meta.url),'utf8'));
  const evidence={implementationSha256,pid:r.pid,startedAt:r.startedAt,endedAt:r.endedAt,exit:r.exit,signal:r.signal,stopReason:r.stopReason,completed,failed,valid:!!valid,model,effort,inputSha256:hash(prompt),outputSha256:result?hash(result):null,events};
  await fs.writeFile(join(jobDir,'execution.json'),JSON.stringify(evidence,null,2),{mode:0o600});
  // Infrastructure diagnostics stay local; never pass them into a chat response.
  if(r.stderr)await fs.writeFile(join(jobDir,'diagnostics.txt'),r.stderr,{mode:0o600});
  if(r.exit!==0||r.stopReason||!completed||failed||!valid)throw Object.assign(Error('MODEL_NOT_COMPLETED'),{evidence});
  return {result,evidence};
  }finally{const db=new DatabaseSync(budgetPath);db.prepare("UPDATE calls SET state='finished' WHERE id=?").run(callId);db.close();}
}
