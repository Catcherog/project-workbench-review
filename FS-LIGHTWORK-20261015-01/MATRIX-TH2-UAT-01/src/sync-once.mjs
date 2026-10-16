// Explicit, single-run synchronization to the allowlisted test table only.
// No schedule, listener, source writes, permission changes, or publication.
import { spawnSync } from 'node:child_process';
import { readFile, writeFile, mkdir, open, unlink } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve, join } from 'node:path';
import { projectRows, planWrites } from './target-projection.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const scope=JSON.parse(await readFile(join(root,'input/target-scope.json'),'utf8'));
const lark=join(root,'.tooling/node_modules/.bin/lark-cli');
const runId='UAT-'+new Date().toISOString().replace(/[:.]/g,'-');
const dir=join(root,'evidence',runId);
await mkdir(dir,{recursive:true});
const receipt={runId,status:'running',startedAt:new Date().toISOString(),actions:[]};
const save=()=>writeFile(join(dir,'receipt.json'),JSON.stringify(receipt,null,2));
const lockPath=join(root,'input/sync.lock');
const lock=await open(lockPath,'wx');
await lock.close();
await save();
function call(command,args){
  const p=spawnSync(command,args,{cwd:root,encoding:'utf8',timeout:60000,maxBuffer:4_000_000});
  if(p.status!==0) throw Error(`command_failed_${p.status??'timeout'}`);
  let value;try{value=JSON.parse(p.stdout);}catch{throw Error('invalid_response');}
  if(value.ok===false||value.error) throw Error('upstream_failed');
  return value;
}
const targetArgs=['--base-token',scope.baseToken,'--table-id',scope.tableId,'--as','user'];
async function readTarget(name){
  const file=join(dir,name+'.ndjson');
  const meta=call(lark,['base','+record-list',...targetArgs,'--output',file]);
  if(meta.has_more!==false||meta.records_count>200) throw Error('incomplete_or_unexpected_target');
  const rows=(await readFile(file,'utf8')).trim().split('\n').filter(Boolean).map(x=>JSON.parse(x));
  if(rows.length!==meta.records_count) throw Error('target_record_count_mismatch');
  const sample=rows.filter(r=>r['数据集']==='sample'||(!r['数据集']&&r['汇总键']?.startsWith(`actual|${scope.aliasId}|`)));
  if(sample.length>2)throw Error('unexpected_sample_count');
  return sample;
}
try{
  const who=call('meegle',['user','me','--format','json']);
  const auth=call(lark,['auth','status']);
  if(who.user_key!==scope.sourcePersonId || auth.brand!=='feishu' || auth.identities?.user?.openId!==scope.larkUserOpenId || auth.identities.user.status!=='ready') throw Error('identity_mismatch');
  receipt.identityChecked=true;await save();
  const read=spawnSync(process.execPath,['src/read-live.mjs'],{cwd:root,encoding:'utf8',timeout:150000,maxBuffer:1_000_000});
  if(read.status!==0) throw Error('live_read_failed');
  const liveDir=read.stdout.trim().split('\n').at(-1);
  if(!liveDir.startsWith(join(root,'evidence/live-')) || resolve(liveDir)!==liveDir) throw Error('invalid_live_path');
  receipt.sourceDirectory=liveDir;
  const outputs=await Promise.all(['week','month'].map(async mode=>JSON.parse(await readFile(join(liveDir,`aggregate-${mode}.json`),'utf8'))));
  const rows=projectRows(outputs,scope,runId,new Date().toISOString());
  if(rows.some(r=>Date.now()-Date.parse(r['读取时间'])>300000)) throw Error('stale_source');
  await writeFile(join(dir,'projected-rows.json'),JSON.stringify(rows,null,2));
  const fieldSchema=call(lark,['base','+field-list',...targetArgs]);
  const writable=new Set(fieldSchema.data.fields.filter(f=>['text','number'].includes(f.type)).map(f=>f.name));
  if(rows.some(r=>Object.keys(r).some(k=>!writable.has(k)))) throw Error('target_schema_mismatch');
  const ownerFile=join(root,'input/target-owned-records.json');
  let owned=[];try{owned=JSON.parse(await readFile(ownerFile,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
  const before=await readTarget('target-before');
  const plan=planWrites(rows,before,owned);
  for(const action of plan){
    const args=['base','+record-upsert',...targetArgs,'--json',JSON.stringify(action.fields)];
    if(action.recordId)args.push('--record-id',action.recordId);
    const result=call(lark,args);
    await writeFile(join(dir,`write-${receipt.actions.length+1}.json`),JSON.stringify(result,null,2));
    // A returned creation receipt is saved before any next write. If the
    // response shape is unknown, stop; never retry an uncertain creation.
    const ids=result.data?.record?.record_id_list ?? result.data?.record_id_list ?? (result.data?.record_id?[result.data.record_id]:[]);
    if(!action.recordId && ids.length!==1) throw Error('creation_receipt_unrecognized');
    const recordId=action.recordId??ids[0];
    if(!owned.includes(recordId)){owned.push(recordId);await writeFile(ownerFile,JSON.stringify(owned,null,2));}
    receipt.actions.push({key:action.fields['汇总键'],recordId,operation:action.recordId?'update':'create',ok:true});await save();
  }
  let after=await readTarget('target-after');
  const matches=()=>after.length===rows.length && rows.every(expected=>{
    const found=after.filter(r=>r['汇总键']===expected['汇总键']);
    return found.length===1 && Object.entries(expected).every(([k,v])=>found[0][k]===v);
  });
  if(!matches()){
    await new Promise(resolve=>setTimeout(resolve,1200));
    after=await readTarget('target-after-settled');
  }
  if(!matches())throw Error('target_readback_mismatch');
  receipt.status='passed';receipt.targetRecords=after.length;
  receipt.cells=after.map(r=>({person:r['人员'],mode:r['周期类型'],period:r['周期'],hours:r['实际小时'],runId:r['运行标识'],recordId:r.record_id}));
}catch(e){
  receipt.status='failed';receipt.errorCode=/^[a-z0-9_]+$/.test(e.message)?e.message:'unexpected_failure';
  receipt.failureMeaning='本次未完成；保留目标已有值及原成功读取时间，不将旧值标成刚更新。核对回执后才能重试。';process.exitCode=1;
}finally{
  receipt.finishedAt=new Date().toISOString();await save();await unlink(lockPath);
  console.log(JSON.stringify(receipt,null,2));
}
