// Manual, allowlisted read of the 16 imported TEST items. Original Tasks are
// never modified. No background synchronization or source work-hour writes.
import {spawnSync} from 'node:child_process';
import {readFile,writeFile,mkdir,open,unlink} from 'node:fs/promises';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {aggregate} from './aggregate.mjs';
import {projectReal} from './real-projection.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const scope=JSON.parse(await readFile(join(root,'input/target-scope.json'),'utf8'));
const imports=Object.values(JSON.parse(await readFile(join(root,'input/real-import-map.json'),'utf8')));
if(imports.length!==16||imports.some(x=>x.status!=='verified')||new Set(imports.map(x=>x.targetId)).size!==16)throw Error('import_scope_invalid');
const lark=join(root,'.tooling/node_modules/.bin/lark-cli');
const runId='REAL-'+new Date().toISOString().replace(/[:.]/g,'-');
const dir=join(root,'evidence',runId);await mkdir(dir,{recursive:true});
const lockPath=join(root,'input/sync.lock');const lock=await open(lockPath,'wx');await lock.close();
const receipt={runId,status:'running',reads:[],writes:[],scopeCount:16};
const save=()=>writeFile(join(dir,'receipt.json'),JSON.stringify(receipt,null,2));await save();
function call(cmd,args){
 const p=spawnSync(cmd,args,{cwd:root,encoding:'utf8',timeout:45000,maxBuffer:3_000_000});
 let v;try{v=JSON.parse(p.stdout);}catch{throw Error('invalid_response');}
 if(p.status!==0||v.error||v.ok===false)throw Error('request_failed');return v;
}
const targetArgs=['--base-token',scope.baseToken,'--table-id',scope.tableId,'--as','user'];
async function target(name){
 const file=join(dir,name+'.ndjson');const meta=call(lark,['base','+record-list',...targetArgs,'--output',file]);
 if(meta.has_more!==false||meta.records_count>200)throw Error('target_pagination_or_scope_limit');
 return (await readFile(file,'utf8')).trim().split('\n').filter(Boolean).map(JSON.parse);
}
try{
 const projectAuth=call('meegle',['auth','status','--format','json']);
 if(projectAuth.authenticated!==true||projectAuth.host!=='project.feishu.cn')throw Error('identity_or_host_mismatch');
 const who=call('meegle',['user','me','--format','json']),auth=call(lark,['auth','status']);
 if(who.user_key!==scope.sourcePersonId||auth.brand!=='feishu'||auth.identities?.user?.openId!==scope.larkUserOpenId||auth.identities.user.status!=='ready')throw Error('identity_mismatch');
 const snapshots=[];const needsReview=new Set();let failedItems=0,unregisteredItems=0,missingDetailItems=0;
 for(const item of imports){
  let response;
  try{response=call('meegle',['workitem','get','--project-key',scope.sourceProjectKey,'--work-item-id',item.targetId,'--fields','_all','--page-size','100','--format','json']);}
  catch{failedItems++;needsReview.add(item.targetId);receipt.reads.push({targetId:item.targetId,status:'request_failed',readAt:new Date().toISOString()});await save();continue;}
  const a=response.work_item_attribute,f=response.work_item_fields;
  if(a?.work_item_id!==item.targetId||a?.owned_project?.key!==scope.sourceProjectKey||a?.work_item_type?.key!==scope.sourceType||!f.some(x=>x.key==='field_8cc591'&&x.value===`REAL-UAT-20261016 | ${item.sourceUrl}`))throw Error('source_scope_mismatch');
  const readAt=new Date().toISOString();
  const raw=f.find(x=>x.key==='field_f34a5f');
  if(!raw)missingDetailItems++;
  // This count means needs entry OR verification. Missing compound fields
  // remain aggregation coverage gaps; they are never coerced to zero rows.
  if(!raw||raw.value===null||Array.isArray(raw.value)&&raw.value.length===0)needsReview.add(item.targetId);
  await writeFile(join(dir,item.targetId+'.json'),JSON.stringify(response,null,2));
  snapshots.push({response,readAt,sourceHint:item.targetId,complete:response.pagination?.has_more===false});
  receipt.reads.push({targetId:item.targetId,status:'ok',readAt});await save();
 }
 if(!snapshots.length)throw Error('all_sources_failed');
 const coverage=failedItems?[{source:'real-test-scope',status:'request_failed',failedItems}]:[];
 const outputs=['week','month'].map(mode=>aggregate(snapshots,{mode,coverage,registrationPolicy:'source_locator'}));
 for(const out of outputs){
  for(const e of out.errors){let id=e.source;try{id??=JSON.parse(e.sourceId).workItemId;}catch{}if(imports.some(i=>i.targetId===id))needsReview.add(id);}
  for(const p of out.pending)needsReview.add(p.row.source.workItemId);
 }
 unregisteredItems=needsReview.size;
 await writeFile(join(dir,'aggregates.json'),JSON.stringify(outputs,null,2));
 const aliasPath=join(root,'input/real-person-aliases.json');let aliases={};try{aliases=JSON.parse(await readFile(aliasPath,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
 for(const id of [...new Set(outputs.flatMap(o=>o.cells.map(c=>c.person.id)))].sort())if(!aliases[id]){const n=Object.keys(aliases).length+1;aliases[id]={id:`real-person-${String(n).padStart(2,'0')}`,name:`体验登记人${String(n).padStart(2,'0')}`};}
 await writeFile(aliasPath,JSON.stringify(aliases,null,2));
 const readAt=snapshots.map(x=>x.readAt).sort().at(-1);
 const desired=projectReal(outputs,{aliases,allowedPersonIds:[scope.sourcePersonId],runId,readAt,totalItems:imports.length,unregisteredItems,failedItems,missingDetailItems});
 await writeFile(join(dir,'projected-rows.json'),JSON.stringify(desired,null,2));
 const fields=call(lark,['base','+field-list',...targetArgs]).data.fields;
 if(desired.some(row=>Object.keys(row).some(k=>!fields.some(f=>f.name===k&&['text','number'].includes(f.type)))))throw Error('schema_mismatch');
 const ownedPath=join(root,'input/real-target-records.json');let owned={};try{owned=JSON.parse(await readFile(ownedPath,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
 const before=(await target('target-before')).filter(r=>r['数据集']==='real');
 const seen=new Set();for(const r of before){if(seen.has(r['汇总键'])||owned[r['汇总键']]!==r.record_id)throw Error('unowned_or_duplicate_target');seen.add(r['汇总键']);}
 const updates=[...desired];
 // Never delete an absent aggregate or turn stale data into zero. Prior cells
 // not represented by this run remain explicit stale history, outside totals.
 for(const old of before)if(!desired.some(r=>r['汇总键']===old['汇总键']))updates.push({'汇总键':old['汇总键'],'记录类型':'stale','刷新结果':'stale','覆盖缺口':'本次未取得该单元格的有效来源；保留上次值供核对，不计入本次小计'});
 for(const row of updates){
  const recordId=owned[row['汇总键']];const args=['base','+record-upsert',...targetArgs,'--json',JSON.stringify(row)];if(recordId)args.push('--record-id',recordId);
  const result=call(lark,args);await writeFile(join(dir,`write-${receipt.writes.length+1}.json`),JSON.stringify(result,null,2));
  const ids=result.data?.record?.record_id_list??result.data?.record_id_list;
  const id=recordId??(ids?.length===1?ids[0]:null);if(!id)throw Error('unknown_write_receipt');
  owned[row['汇总键']]=id;await writeFile(ownedPath,JSON.stringify(owned,null,2));
  receipt.writes.push({key:row['汇总键'],recordId:id,operation:recordId?'update':'create'});await save();
 }
 const after=(await target('target-after')).filter(r=>r['数据集']==='real');
 if(!desired.every(r=>{const a=after.filter(x=>x['汇总键']===r['汇总键']);return a.length===1&&Object.entries(r).every(([k,v])=>a[0][k]===v);}))throw Error('target_readback_mismatch');
 receipt.status='passed';receipt.targetUpdateVerified=true;receipt.actualRows=outputs[0].rowsRead;receipt.needsEntryOrVerification=unregisteredItems;receipt.missingDetailItems=missingDetailItems;receipt.failedItems=failedItems;receipt.targetDatasetRecords=after.length;receipt.sourceReadAt=readAt;
}catch(e){receipt.status='failed';receipt.error=/^[a-z_]+$/.test(e.message)?e.message:'unexpected_failure';process.exitCode=1;}
finally{receipt.finishedAt=new Date().toISOString();await save();await unlink(lockPath);console.log(JSON.stringify(receipt,null,2));}
