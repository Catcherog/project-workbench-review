// Offline replay of the redacted live sample; performs no remote calls.
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {aggregate} from '../src/aggregate.mjs';
const response=JSON.parse(await readFile(new URL('source-t02.json',import.meta.url),'utf8'));
const context=JSON.parse(await readFile(new URL('source-read-context.json',import.meta.url),'utf8'));
const snapshot={response,readAt:context.readAt,complete:true};
const result=[];
for(const mode of ['week','month']){
 const out=aggregate([snapshot],{mode,coverage:[{source:'known-real-project',status:'no_records',total:0}]});
 assert.equal(out.cells.length,1);assert.equal(out.cells[0].hours,'8');
 assert.equal(out.cells[0].rows.length,1);
 result.push({mode,person:out.cells[0].person.id,period:out.cells[0].period.label,hours:out.cells[0].hours,sourceRows:1,coverageGaps:out.coverageGaps});
}
console.log(JSON.stringify({status:'passed',offlineReplay:true,result},null,2));
