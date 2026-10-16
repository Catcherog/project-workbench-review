import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {aggregate} from './src/aggregate.mjs';
const response=JSON.parse(await readFile(new URL('./sample-redacted.json',import.meta.url),'utf8'));
for(const mode of ['week','month']){const r=aggregate([{response,readAt:'2026-10-16T11:37:35+08:00',complete:true}],{mode,coverage:[{source:'PROJECT-TEST',status:'no_records'}]});assert.equal(r.cells[0].hours,'8');assert.equal(r.cells[0].period.label,mode==='week'?'2026-09-14—2026-09-20':'2026-09');console.log(JSON.stringify({mode,hours:r.cells[0].hours,period:r.cells[0].period.label,componentBinding:r.componentBinding}));}
