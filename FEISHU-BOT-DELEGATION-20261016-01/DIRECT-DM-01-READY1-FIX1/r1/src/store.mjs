import {DatabaseSync} from 'node:sqlite';import {mkdirSync} from 'node:fs';import {dirname} from 'node:path';
const deliveryFacts=new Set(['DELIVERING','DELIVERY_UNKNOWN','LOCAL_RECEIVED','LOCAL_RECEIVED_UNVERIFIED','LOCAL_DELIVERY_VERIFIED']);
export class Store{
 constructor(file){mkdirSync(dirname(file),{recursive:true,mode:0o700});this.db=new DatabaseSync(file);this.db.exec(`PRAGMA journal_mode=WAL;CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,fingerprint TEXT,nonce TEXT UNIQUE,status TEXT,data TEXT,rounds INTEGER);CREATE TABLE IF NOT EXISTS events(n INTEGER PRIMARY KEY,request_id TEXT,event TEXT,data TEXT);CREATE TABLE IF NOT EXISTS counters(k TEXT PRIMARY KEY,v INTEGER);CREATE TABLE IF NOT EXISTS authorization_decisions(n INTEGER PRIMARY KEY,request_id TEXT,state TEXT,reason TEXT,checked_at INTEGER);`);for(const k of ['summaryReads','rawLogReads','deliveryTools','dispatches','readbacks'])this.db.prepare('INSERT OR IGNORE INTO counters VALUES(?,0)').run(k);this.db.exec("UPDATE requests SET status='DELIVERY_UNKNOWN' WHERE status='DELIVERING'");}
 row(id){const r=this.db.prepare('SELECT * FROM requests WHERE id=?').get(id);return r?{...r,data:JSON.parse(r.data)}:null;}
 save(id,status,data,rounds){if(data===undefined)this.db.prepare('UPDATE requests SET status=? WHERE id=?').run(status,id);else if(rounds===undefined)this.db.prepare('UPDATE requests SET status=?,data=? WHERE id=?').run(status,JSON.stringify(data),id);else this.db.prepare('UPDATE requests SET status=?,data=?,rounds=? WHERE id=?').run(status,JSON.stringify(data),rounds,id);}
 recordAuthorizationDenial(id,state,reason,at){
  // Authorization describes this attempt. A past/in-flight side effect is an
  // independent fact and must survive expiry, revocation and policy changes.
  this.transaction(()=>{const row=this.row(id);if(!row)return;
   const preserved=deliveryFacts.has(row.status),authorization={state,reason,checkedAt:at};
   this.db.prepare('INSERT INTO authorization_decisions(request_id,state,reason,checked_at) VALUES(?,?,?,?)').run(id,state,reason,at);
   if(!preserved)this.save(id,state);
   this.event(id,'AUTHORIZATION_DENIED',{...authorization,deliveryFactPreserved:preserved,priorStatus:row.status,resultingStatus:preserved?row.status:state});
  });
 }
 authorization(id){return this.db.prepare('SELECT state,reason,checked_at FROM authorization_decisions WHERE request_id=? ORDER BY n DESC LIMIT 1').get(id)||null;}
 event(id,event,data={}){this.db.prepare('INSERT INTO events(request_id,event,data) VALUES(?,?,?)').run(id,event,JSON.stringify(data));}
 add(k){this.db.prepare('UPDATE counters SET v=v+1 WHERE k=?').run(k);}
 counts(){return Object.fromEntries(this.db.prepare('SELECT * FROM counters').all().map(r=>[r.k,r.v]));}
 transaction(fn){this.db.exec('BEGIN IMMEDIATE');try{const r=fn();this.db.exec('COMMIT');return r;}catch(e){this.db.exec('ROLLBACK');throw e;}}
 close(){this.db.close();}
}
