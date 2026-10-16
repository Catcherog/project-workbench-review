// Copies only the user-selected open source tasks into the existing TEST type.
// Original Tasks, source assignees, hours, and schedules are never written.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
const root=fileURLToPath(new URL('../',import.meta.url));
const scope=JSON.parse(await readFile(join(root,'input/target-scope.json'),'utf8'));
const list=JSON.parse(await readFile(join(root,'evidence/current/real-tasklist.json'),'utf8')).data.tasklist;
const fields=JSON.parse(await readFile(join(root,'evidence/current/real-tasklist-fields.json'),'utf8')).data.items;
const priorities=JSON.parse(await readFile(join(root,'evidence/current/requirement-priority-field.json'),'utf8')).list[0];
const summaries=JSON.parse(await readFile(join(root,'evidence/current/real-tasklist-items-page1.json'),'utf8')).data;
if(!scope.sourceTasklistGuid||list.guid!==scope.sourceTasklistGuid||summaries.has_more)throw Error('source_list_scope_mismatch');
const selected=summaries.items.filter(t=>t.completed_at==='0');
if(selected.length!==16)throw Error('source_selection_changed');
const dir=join(root,'evidence/real-import');await mkdir(dir,{recursive:true});
const ledgerPath=join(root,'input/real-import-map.json');
let ledger={};try{ledger=JSON.parse(await readFile(ledgerPath,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
const save=()=>writeFile(ledgerPath,JSON.stringify(ledger,null,2));
function run(cmd,args){const p=spawnSync(cmd,args,{cwd:root,encoding:'utf8',timeout:45000,maxBuffer:2_000_000});if(p.status!==0)throw Error('command_failed_'+p.status);const v=JSON.parse(p.stdout);if(v.error||v.ok===false)throw Error('upstream_failure');return v;}
function textField(t,name){
 const f=t.custom_fields.find(f=>f.name===name);if(!f)return '';
 if(f.type==='text')return f.text_value??'';
 const meta=fields.find(m=>m.guid===f.guid);const options=meta?.single_select_setting?.options??meta?.multi_select_setting?.options??[];
 const ids=f.single_select_value?[f.single_select_value]:(f.multi_select_value??[]);
 return ids.map(id=>{const o=options.find(o=>o.guid===id);if(!o)throw Error('unmapped_source_option');return o.name;}).join('、');
}
const who=run('meegle',['user','me','--format','json']);if(who.user_key!==scope.sourcePersonId)throw Error('operator_changed');
const plans=[];
for(const summary of selected){
 if(ledger[summary.guid]?.targetId){plans.push({sourceGuid:summary.guid,status:'already_created',targetId:ledger[summary.guid].targetId});continue;}
 if(ledger[summary.guid]?.status==='creating')throw Error('unresolved_create_requires_readback');
 const src=run(join(root,'.tooling/node_modules/.bin/lark-cli'),['task','tasks','get','--task-guid',summary.guid,'--as','user']).data.task;
 await writeFile(join(dir,summary.guid+'-source.json'),JSON.stringify(src,null,2));
 if(src.completed_at!=='0'){plans.push({sourceGuid:src.guid,status:'now_completed_skipped'});continue;}
 if(!(src.tasklists??[]).some(x=>x.tasklist_guid===list.guid||x.guid===list.guid))throw Error('source_membership_mismatch');
 const priority=textField(src,'优先级');const priorityId=priority?priorities.option.find(o=>o.option_name===priority)?.option_id:null;
 if(priority&&!priorityId)throw Error('priority_mapping_missing');
 const sourceLink=src.url; if(!sourceLink||new URL(sourceLink).searchParams.get('guid')!==src.guid)throw Error('source_link_mismatch');
 const retained=['需求编号','优先级','需求分类','发起部门','审批编号'].map(n=>`${n}：${textField(src,n)||'未填写'}`).join('\n\n');
 const description=`这是一份真实需求的体验副本，原任务记录和办理状态保持不变。详细问题、附件与讨论请查看[原任务](${sourceLink})。\n\n${retained}\n\n实际工时尚未登记；没有复制或推算原负责人的投入。体验负责人为当前操作人，未向原任务成员派发或发送消息。`;
 const payload={project_key:scope.sourceProjectKey,work_item_type:scope.sourceType,fields:[
 {field_key:'template',field_value:scope.lightTemplateId},
 {field_key:'name',field_value:`【体验】${src.summary}`},
 {field_key:'description',field_value:description},
 {field_key:'field_8cc591',field_value:`REAL-UAT-20261016 | ${sourceLink}`},
 {field_key:'field_238b96',field_value:scope.pilotGroupOptionId},
 {field_key:'field_436ee3',field_value:'false'},
 {field_key:'field_0f3756',field_value:'false'},
 {field_key:'role_owners',field_value:JSON.stringify([{role:scope.ownerRoleKey,owners:[scope.sourcePersonId]}])},
 ...(priorityId?[{field_key:priorities.field_key,field_value:priorityId}]:[])]};
 await writeFile(join(dir,src.guid+'-payload.json'),JSON.stringify(payload,null,2));
 if(!process.argv.includes('--apply')){plans.push({sourceGuid:src.guid,status:'prepared',name:src.summary});continue;}
 ledger[src.guid]={status:'creating',sourceUpdatedAt:src.updated_at,startedAt:new Date().toISOString()};await save();
 const result=run('meegle',['workitem','create','--params',JSON.stringify(payload),'--format','json']);
 await writeFile(join(dir,src.guid+'-create.json'),JSON.stringify(result,null,2));
 const targetId=result.work_item_id??result.id;
 if(!targetId)throw Error('unrecognized_creation_receipt');
 ledger[src.guid]={...ledger[src.guid],status:'created',targetId:String(targetId),priority,sourceUrl:sourceLink,name:src.summary};await save();
 const back=run('meegle',['workitem','get','--project-key',scope.sourceProjectKey,'--work-item-id',String(targetId),'--fields','_all','--page-size','100','--format','json']);
 await writeFile(join(dir,src.guid+'-readback.json'),JSON.stringify(back,null,2));
 if(back.work_item_attribute?.work_item_id!==String(targetId)||back.work_item_attribute?.work_item_type?.key!==scope.sourceType)throw Error('target_identity_mismatch');
 const sourceField=back.work_item_fields.find(f=>f.key==='field_8cc591')?.value;
 if(sourceField!==payload.fields.find(f=>f.field_key==='field_8cc591').field_value)throw Error('source_reference_readback_mismatch');
 ledger[src.guid].status='verified';await save();plans.push({sourceGuid:src.guid,status:'verified',targetId:String(targetId)});
}
await writeFile(join(dir,'summary.json'),JSON.stringify({selected:16,results:plans,originalWrites:0,sourceHoursCopied:0},null,2));
console.log(JSON.stringify({selected:16,results:plans},null,2));
