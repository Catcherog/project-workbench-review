import fs from 'node:fs';
import {dirname} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {randomUUID,createHash} from 'node:crypto';
import {processIdentity,liveGroupMembers} from './process.mjs';
const digest=x=>createHash('sha256').update(x).digest('hex');
export class ExecutionBudget{
 constructor(file,snapshot,{phase='R1-FIX1',maxNew=4,total=20}={}){
  if(maxNew>4||total>20)throw Error('BUDGET_EXPANSION_DENIED');
  fs.mkdirSync(dirname(file),{recursive:true,mode:0o700});this.db=new DatabaseSync(file);Object.assign(this,{phase,maxNew,total});
  this.db.exec('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,phase TEXT,at TEXT,state TEXT,process TEXT,owner TEXT); CREATE TABLE IF NOT EXISTS snapshots(hash TEXT PRIMARY KEY);');
  const source=JSON.stringify(snapshot),key=digest(source);
  this.db.exec('BEGIN IMMEDIATE');
  try{
   if(!this.db.prepare('SELECT hash FROM snapshots WHERE hash=?').get(key)){
    if(this.db.prepare('SELECT count(*) n FROM calls').get().n)throw Error('BUDGET_RECONCILIATION_REQUIRED');
    if(snapshot.usedCalls!==snapshot.startedAt.length||snapshot.usedCalls>20)throw Error('INVALID_BASELINE_BUDGET');
    for(const [i,at]of snapshot.startedAt.entries())this.db.prepare('INSERT INTO calls VALUES(?,?,?,?,NULL,NULL)').run('inherited-'+i,'R1',at,'finished');
    this.db.prepare('INSERT INTO snapshots VALUES(?)').run(key);
   }
   this.db.exec('COMMIT');
  }catch(e){this.db.exec('ROLLBACK');this.db.close();throw e;}
 }
 status(){const rows=this.db.prepare('SELECT * FROM calls').all();return {total:rows.length,newCalls:rows.filter(x=>x.phase===this.phase).length,active:rows.filter(x=>['running','termination_unknown'].includes(x.state)).length};}
 reserve(){this.db.exec('BEGIN IMMEDIATE');try{const s=this.status();if(s.total>=this.total)throw Error('TOTAL_MODEL_LIMIT');if(s.newCalls>=this.maxNew)throw Error('FIX1_MODEL_LIMIT');if(s.active)throw Error('MODEL_OWNER_BUSY');const id=randomUUID();this.db.prepare('INSERT INTO calls VALUES(?,?,?,?,NULL,?)').run(id,this.phase,new Date().toISOString(),'running',JSON.stringify({pid:process.pid,identity:processIdentity(process.pid)}));this.db.exec('COMMIT');return id;}catch(e){this.db.exec('ROLLBACK');throw e;}}
 spawned(id,receipt){this.db.prepare('UPDATE calls SET process=? WHERE id=?').run(JSON.stringify(receipt),id);}
 finish(id,confirmed){this.db.prepare('UPDATE calls SET state=? WHERE id=?').run(confirmed?'finished':'termination_unknown',id);}
 inspect(id){
  const row=this.db.prepare('SELECT * FROM calls WHERE id=?').get(id);if(!row)throw Error('UNKNOWN_RUN');
  const owner=row.owner?JSON.parse(row.owner):null,p=row.process?JSON.parse(row.process):null;
  const currentOwner=owner?processIdentity(owner.pid):null,current=p?processIdentity(p.pid):null,members=p?liveGroupMembers(p.pgid):[];
  const ownerGone=!owner||currentOwner!==owner.identity,processGone=!p||current!==p.identity;
  return {id,state:row.state,ownerGone,processGone,liveMembers:members,reconcilable:ownerGone&&processGone&&Array.isArray(members)&&members.length===0};
 }
 reconcile(id){const r=this.inspect(id);if(!r.reconcilable)throw Error('PROCESS_STILL_ACTIVE_OR_UNKNOWN');this.db.prepare("UPDATE calls SET state='interrupted_confirmed' WHERE id=?").run(id);return r;}
 close(){this.db.close();}
}
