// Explicitly invoked CLI reads only; no daemon, remote listener or write command.
import { spawnSync } from 'node:child_process';
import { mkdir,writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { aggregate } from './aggregate.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const config=JSON.parse(await (await import('node:fs/promises')).readFile(root+'input/read-scope.json','utf8'));
function run(args){
  const p=spawnSync('meegle',[...args,'--format','json'],{encoding:'utf8',timeout:30000,maxBuffer:2_000_000});
  if(p.status!==0)throw new Error(`read failed (${p.status??'timeout'}); no fallback or write attempted`);
  return JSON.parse(p.stdout);
}
const auth=run(['auth','status']);
if(auth.authenticated!==true||auth.host!=='project.feishu.cn')throw new Error('Existing Feishu profile not ready; no login/profile change attempted.');
const dir=root+'evidence/live-'+new Date().toISOString().replace(/[:.]/g,'-');await mkdir(dir,{recursive:true});
const base=['--project-key',config.projectKey];
const commands={
 't02-all-fields':['workitem','get',...base,'--work-item-id',config.extraItemId,'--fields','_all','--page-size','100'],
 'project-records':['workhour','list-records',...base,'--work-item-id',config.projectItemId,'--work-item-type',config.projectType,'--page-num','1'],
 'project-node':['workflow','get-node',...base,'--work-item-id',config.projectItemId,'--node-id-list','state_1','--need-sub-task','false']
};
const receipts=[],responses={};
for(const[name,args]of Object.entries(commands)){const startedAt=new Date().toISOString();const data=run(args);responses[name]=data;await writeFile(`${dir}/${name}.json`,JSON.stringify(data,null,2));receipts.push({name,startedAt,readAt:new Date().toISOString(),args});}
await writeFile(`${dir}/receipt.json`,JSON.stringify(receipts,null,2));
const total=responses['project-records'].Pagination?.total;
const coverage=[{source:'known-real-project',status:total===0?'no_records':'mapping_unverified',total:total??null,meaning:'空记录不代表零投入；非空真实项目字段映射未验证'}];
for(const mode of ['week','month']){
 const response=responses['t02-all-fields'];
 const output=aggregate([{response,readAt:receipts[0].readAt,complete:response.pagination?.has_more===false}],{mode,coverage});
 await writeFile(`${dir}/aggregate-${mode}.json`,JSON.stringify(output,null,2));
 console.log(JSON.stringify({mode,source:'live-api-to-adapter',componentBinding:output.componentBinding,cells:output.cells.map(c=>({period:c.period.label,hours:c.hours,coverage:c.caption})),pending:output.pending.length,errors:output.errors.length}));
}
console.log(dir);
