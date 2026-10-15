import fs from 'node:fs/promises';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
const raw=await fs.readFile(new URL('../evidence/round-budget.json',import.meta.url),'utf8'),known=JSON.parse(raw),key=createHash('sha256').update(raw).digest('hex');
await fs.mkdir(new URL('../runtime',import.meta.url),{recursive:true});
const d=new DatabaseSync(new URL('../runtime/model-budget.sqlite',import.meta.url));
d.exec('CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,at TEXT,state TEXT); CREATE TABLE IF NOT EXISTS imported_snapshots(k TEXT PRIMARY KEY); BEGIN IMMEDIATE;');
if(!d.prepare('SELECT k FROM imported_snapshots WHERE k=?').get(key)){
 if(d.prepare('SELECT count(*) AS n FROM calls').get().n){d.exec('ROLLBACK');d.close();throw Error('EXISTING_BUDGET_REQUIRES_RECONCILIATION: do not erase or reset this ledger');}
 for(const at of known.startedAt)d.prepare("INSERT INTO calls(at,state) VALUES(?,'finished')").run(at);
 d.prepare('INSERT INTO imported_snapshots VALUES(?)').run(key);
}
d.exec('COMMIT');
console.log({recordedCalls:d.prepare('SELECT count(*) AS n FROM calls').get().n,roundLimit:20});d.close();
