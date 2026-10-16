import { readFile,writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { aggregate } from './aggregate.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const response=JSON.parse(await readFile(root+'evidence/t02-all-fields.json','utf8'));
const receipt=JSON.parse(await readFile(root+'evidence/read-receipt.json','utf8'));
const records=JSON.parse(await readFile(root+'evidence/project-records-before.json','utf8'));
const total=records.Pagination?.total;
const coverage=[{source:'known-real-project',status:total===0?'no_records':'mapping_unverified',total:total??null,meaning:'真实项目非空实际来源及合并未验证，空结果不代表零投入'}];
for(const mode of ['week','month']){
  const data=aggregate([{response,readAt:receipt.readAt,complete:response.pagination?.has_more===false}],{mode,coverage});
  await writeFile(root+`evidence/aggregate-${mode}.json`,JSON.stringify(data,null,2));
  console.log(JSON.stringify({mode,source:'real-api-snapshot-replay',componentBinding:data.componentBinding,cells:data.cells.map(c=>({personId:c.person.id,period:c.period.label,hours:c.hours,valueState:c.valueState,coverage:c.caption,nonProjectItemCount:c.nonProjectItemCount})),pending:data.pending.length,errors:data.errors.length}));
}
