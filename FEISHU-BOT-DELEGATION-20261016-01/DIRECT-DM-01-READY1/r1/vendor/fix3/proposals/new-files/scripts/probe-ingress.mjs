// UNAPPLIED CANDIDATE. The current application never loads this module.
import fs from 'node:fs';import {dirname} from 'node:path';import {DatabaseSync} from 'node:sqlite';import {createHash,randomUUID} from 'node:crypto';
import {bounded} from './probe-operation.mjs';
const hash=x=>createHash('sha256').update(JSON.stringify(x??null)).digest('hex');
export class TestIngress{
 constructor({file,appId,tenantId,enabled=false,windows=[],verify,enqueue,clock=()=>Date.now(),ioTimeoutMs=1000}){
  if(ioTimeoutMs<1||ioTimeoutMs>30000)throw Error('INVALID_INGRESS_TIMEOUT');
  Object.assign(this,{appId,tenantId,enabled,verify,enqueue,clock,ioTimeoutMs});this.windows=new Map(windows.map(w=>[w.token,w]));
  for(const w of windows)if(!/^[a-f0-9]{32}$/.test(w.token)||!w.userId||!w.alias||!Number.isFinite(w.start)||!Number.isFinite(w.end)||w.end<=w.start||w.end-w.start>3600000)throw Error('INVALID_TEST_WINDOW');
  fs.mkdirSync(dirname(file),{recursive:true,mode:0o700});this.lock=file+'.owner';fs.mkdirSync(this.lock,{mode:0o700});fs.writeFileSync(this.lock+'/owner.json',JSON.stringify({id:randomUUID(),pid:process.pid,at:new Date().toISOString()}),{mode:0o600});
  this.db=new DatabaseSync(file);try{this.db.exec('CREATE TABLE IF NOT EXISTS scope(k TEXT PRIMARY KEY); CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY,data TEXT); CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY,status TEXT,data TEXT); CREATE TABLE IF NOT EXISTS sessions(k TEXT PRIMARY KEY);');
  this.db.exec('BEGIN IMMEDIATE');const scope=hash([appId,tenantId]),priorScope=this.db.prepare('SELECT k FROM scope').get();if(priorScope&&priorScope.k!==scope)throw Error('INGRESS_SCOPE_CHANGED');if(!priorScope)this.db.prepare('INSERT INTO scope VALUES(?)').run(scope);
  for(const row of this.db.prepare('SELECT * FROM tokens').all()){const old=JSON.parse(row.data),next=this.windows.get(row.token);if(next&&JSON.stringify(next)!==JSON.stringify(old))throw Error('TEST_TOKEN_REUSE_DENIED');this.windows.set(row.token,old);}
  for(const w of this.windows.values())this.db.prepare('INSERT OR IGNORE INTO tokens VALUES(?,?)').run(w.token,JSON.stringify(w));
  this.db.exec("UPDATE claims SET status='held_after_restart' WHERE status IN ('verifying','dispatching')");
  this.db.exec('COMMIT');}catch(e){try{this.db.exec('ROLLBACK');}catch{}this.db.close();fs.unlinkSync(this.lock+'/owner.json');fs.rmdirSync(this.lock);throw e;}
  this.lifetime=new AbortController();this.pending=new Set();this.closed=false;
 }
 match({identity,event,key,source='event'}){
  if(key!=='im.message.receive_v1')return null;
  if(this.closed)throw Error('INGRESS_CLOSED_KEEP_TEST_QUARANTINE');
  const prior=this.db.prepare('SELECT * FROM claims WHERE id=?').get(event.message_id||'');
  let window;for(const w of this.windows.values())if(typeof event.content==='string'&&(event.content===`#PROBE ${w.token}`||event.content.startsWith(`#PROBE ${w.token} `))){window=w;break;}
  if(!prior&&!window)return null;
  return Object.freeze({identity,event,source,window:window||this.windows.get(JSON.parse(prior.data).token),prior});
 }
 async filterPolled({identity,messages}){
  const ordinary=[];
  for(const m of messages){const e={message_id:m.message_id,content:m.content,sender_id:typeof m.sender?.id==='string'?m.sender.id:m.sender?.id?.open_id||m.sender?.open_id,chat_id:m.chat_id,chat_type:m.chat_type,create_time:m.create_time};const match=this.match({identity,event:e,key:'im.message.receive_v1',source:'polling'});if(match)await this.handle(match);else ordinary.push(m);}
  return ordinary;
 }
 handle(match){const p=this.route(match);this.pending.add(p);p.then(()=>this.pending.delete(p),()=>this.pending.delete(p));return p;}
 save(id,status,data){this.db.prepare('INSERT INTO claims VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data').run(id,status,JSON.stringify(data));return {handled:true,status};}
 async route({identity,event:e,source,window:w}){
  const old=this.db.prepare('SELECT * FROM claims WHERE id=?').get(e.message_id);
  if(old&&!(source==='event'&&old.status==='observed_polling'))return {handled:true,status:'duplicate',storedStatus:old.status};
  const data={token:w?.token||'',senderHash:hash(e.sender_id),chatHash:hash(e.chat_id),contentHash:hash(e.content),source};
  if(source==='polling')return this.save(e.message_id,'observed_polling',data); // suppress collection; only a later verified event may execute
  // A recognized test namespace is held even when disabled, invalid or late.
  if(!w||typeof e.message_id!=='string'||!e.message_id.startsWith('om_')||!Number.isFinite(Number(e.create_time))||identity.appId!==this.appId||identity.tenantKey!==this.tenantId||e.sender_id!==w.userId||e.chat_type!=='p2p'||e.sender_type!=='user')return this.save(e.message_id,'quarantined_identity',data);
  if(!this.enabled)return this.save(e.message_id,'held_disabled',data);
  if(this.clock()<w.start||this.clock()>=w.end||Number(e.create_time)<w.start||Number(e.create_time)>=w.end)return this.save(e.message_id,'held_window',data);
  this.save(e.message_id,'verifying',data);
  let verified;
  try{verified=await bounded('verify_test_message',s=>this.verify(e.message_id,{signal:s}),{timeoutMs:this.ioTimeoutMs,signal:this.lifetime.signal});}catch{return this.save(e.message_id,'held_verification',data);}
  if(!verified||['message_id','sender_id','sender_type','chat_id','chat_type','content','create_time'].some(k=>String(e[k])!==String(verified[k]))||verified.appId!==this.appId||verified.tenantKey!==this.tenantId)return this.save(e.message_id,'quarantined_readback',data);
  if(!this.enabled||this.lifetime.signal.aborted)return this.save(e.message_id,'held_disabled',data);
  if(this.clock()>=w.end)return this.save(e.message_id,'held_window',data);
  const action=e.content.slice(`#PROBE ${w.token}`.length).trim(),session=hash([this.appId,this.tenantId,e.sender_id,e.chat_id,w.token]);
  if(action==='BEGIN'){this.db.prepare('INSERT OR IGNORE INTO sessions VALUES(?)').run(session);return this.save(e.message_id,'activated',data);}
  if(action!=='RUN'||!this.db.prepare('SELECT k FROM sessions WHERE k=?').get(session))return this.save(e.message_id,'held_session',data);
  this.save(e.message_id,'dispatching',data);
  try{await bounded('dispatch_test_job',s=>this.enqueue({jobId:hash([this.appId,e.message_id]),sessionId:session,participantAlias:w.alias,operation:'synthetic_sum',expiresAt:w.end},{signal:s}),{timeoutMs:this.ioTimeoutMs,signal:this.lifetime.signal});return this.save(e.message_id,this.clock()>=w.end||this.lifetime.signal.aborted?'worker_ack_late':'worker_accepted',data);}catch{return this.save(e.message_id,'worker_unknown',data);}
 }
 async close(){this.enabled=false;this.lifetime.abort();await Promise.allSettled([...this.pending]);this.closed=true;this.db.close();fs.unlinkSync(this.lock+'/owner.json');fs.rmdirSync(this.lock);}
}
