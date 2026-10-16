import { readFile,readdir,writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../',import.meta.url));
const dirs=(await readdir(root+'evidence',{withFileTypes:true})).filter(d=>d.isDirectory()&&d.name.startsWith('live-')).map(d=>d.name).sort();
const latest=dirs.at(-1);assert.ok(latest,'Run read-live first.');
const json=async p=>JSON.parse(await readFile(root+'evidence/'+p,'utf8'));
const equal=(a,b)=>{assert.deepEqual(a,b);return true;};
const checks={
 t02_all_fields_unchanged:equal(await json('t02-all-fields.json'),await json(latest+'/t02-all-fields.json')),
 project_records_unchanged:equal(await json('project-records-before.json'),await json(latest+'/project-records.json')),
 project_node_unchanged:equal(await json('project-node-before.json'),await json(latest+'/project-node.json')),
 dashboard_page_config_unchanged:equal((await json('dashboard-before.json')).data,(await json('dashboard-after.json')).data),
 matrix_records_unchanged:equal(await readFile(root+'evidence/matrix-records-before.ndjson','utf8'),await readFile(root+'evidence/matrix-records-after.ndjson','utf8'))
};
checks.matrix_records_count=(await readFile(root+'evidence/matrix-records-before.ndjson','utf8')).trim().split('\n').length;
for(const mode of ['week','month']){
 const d=await json(latest+`/aggregate-${mode}.json`);assert.equal(d.cells.length,1);assert.equal(d.errors.length,0);
 const c=d.cells[0];assert.equal(c.hours,'8');assert.equal(c.rows.length,1);assert.equal(c.rows[0].person.id,c.person.id);
 assert.equal(c.period.label,mode==='week'?'2026-09-14—2026-09-20':'2026-09');
 checks[mode+'_live_result']={personId:c.person.id,period:c.period.label,hours:c.hours,sameRowSources:c.rows.length,nonProjectItems:c.nonProjectItemCount,coveredOnly:c.coverage==='covered_sources_only',componentBinding:d.componentBinding};
}
const result={observedAt:new Date().toISOString(),latestLiveDirectory:'evidence/'+latest,checks,limits:'仅核对实际读取的源字段、节点、底表记录和页面配置；共享权限未改但未单独全量回读。该脚本的8小时断言仅固定本轮样本，未来源变化应解释差异，不能改写源数据。'};
await writeFile(root+'evidence/no-write-and-live-verification.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
