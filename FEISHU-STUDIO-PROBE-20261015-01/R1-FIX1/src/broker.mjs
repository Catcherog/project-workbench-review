import {DatabaseSync} from 'node:sqlite';
import {resolve,dirname} from 'node:path';
import {randomUUID} from 'node:crypto';
import {hash} from './codex.mjs';
import {bounded} from './lifecycle.mjs';
import {acquireOwner} from './owner.mjs';

// Transport remains offline. Identity must come from the trusted adapter, never model text.
export class ProbeBroker{
 constructor({file,appId,tenantId,participants,deadline,verify,execute,reply,readReply,clock=()=>Date.now(),maxCalls=20,taskTimeoutMs=180000,maxReplies=40,verifyTimeoutMs=1000,sendTimeoutMs=1000,readbackTimeoutMs=1000,maxStopMs=4000}){
  if(!Number.isFinite(deadline)||deadline<=clock()||deadline-clock()>3600000)throw Error('INVALID_WINDOW');
  if(!Number.isInteger(maxCalls)||maxCalls<1||maxCalls>20||taskTimeoutMs<1||taskTimeoutMs>180000||maxReplies<1||maxReplies>40||maxStopMs<50||maxStopMs>4500)throw Error('INVALID_LIMITS');
  for(const x of [verifyTimeoutMs,sendTimeoutMs,readbackTimeoutMs])if(!Number.isFinite(x)||x<1||x>30000)throw Error('INVALID_IO_LIMIT');
  Object.assign(this,{appId,tenantId,participants:new Map(participants.map(x=>[x.id,x.alias])),deadline,verify,execute,reply,readReply,clock,maxCalls,taskTimeoutMs,maxReplies,verifyTimeoutMs,sendTimeoutMs,readbackTimeoutMs,maxStopMs});
  this.ownership=acquireOwner(file);this.jobsRoot=resolve(dirname(file),'jobs');
  try{
   this.db=new DatabaseSync(file);
   this.db.exec('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v INTEGER); CREATE TABLE IF NOT EXISTS sessions(k TEXT PRIMARY KEY,marker TEXT,history TEXT); CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,session TEXT,status TEXT,data TEXT,output TEXT,reply_id TEXT); CREATE TABLE IF NOT EXISTS intakes(id TEXT PRIMARY KEY,status TEXT,at TEXT); CREATE TABLE IF NOT EXISTS journal(n INTEGER PRIMARY KEY,id TEXT,phase TEXT,detail TEXT,at TEXT);');
   for(const [k,v] of [['calls',0],['replies',0],['startedAt',clock()],['deadline',deadline],['scope',hash([appId,tenantId,participants])]])this.db.prepare('INSERT OR IGNORE INTO meta VALUES(?,?)').run(k,v);
   this.startedAt=this.count('startedAt');
   if(this.count('deadline')!==deadline)throw Error('WINDOW_CANNOT_RENEW');
   if(this.count('scope')!==hash([appId,tenantId,participants]))throw Error('SCOPE_CANNOT_CHANGE');
   const recovery=this.db.prepare("SELECT id,status FROM messages WHERE status IN ('queued','running','sending')").all();
   for(const row of recovery){const next={queued:'interrupted_unstarted',running:'interrupted',sending:'reply_unknown'}[row.status];this.update(row.id,next);this.note(row.id,'recovered',{from:row.status,to:next,automaticReplay:false});}
   this.db.exec("UPDATE intakes SET status='verification_interrupted' WHERE status='verifying';");
  }catch(e){this.db?.close();this.ownership.release();throw e;}
  this.queue=Promise.resolve();this.pending=new Set();this.workers=new Set();this.lifetime=new AbortController();this.stopped=false;this.closed=false;
  this.expiry=setTimeout(()=>void this.stop('expired'),Math.max(1,deadline-clock()));this.expiry.unref();
 }
 count(k){return this.db.prepare('SELECT v FROM meta WHERE k=?').get(k).v;}
 note(id,phase,detail={}){if(!this.closed)this.db.prepare('INSERT INTO journal(id,phase,detail,at) VALUES(?,?,?,?)').run(id,phase,JSON.stringify(detail),new Date().toISOString());}
 update(id,status,output,replyId){
  if(this.closed)return;
  let sql='UPDATE messages SET status=?',args=[status];
  if(output!==undefined){sql+=',output=?';args.push(output);}if(replyId!==undefined){sql+=',reply_id=?';args.push(replyId);}sql+=' WHERE id=?';args.push(id);this.db.prepare(sql).run(...args);
 }
 track(p,set=this.pending){set.add(p);p.then(()=>set.delete(p),()=>set.delete(p));return p;}
 identity(e){return e&&e.appId===this.appId&&e.tenantId===this.tenantId&&e.chatType==='p2p'&&e.senderType==='user'&&this.participants.has(e.senderId)&&typeof e.chatId==='string'&&e.chatId.length>0&&e.chatId.length<160&&typeof e.messageId==='string'&&e.messageId.length>0&&e.messageId.length<160&&typeof e.text==='string'&&e.text.length<=2000&&Number.isFinite(e.createdAt)&&e.createdAt<=this.clock()+30000&&e.createdAt>=this.startedAt;}
 accept(event){
  if(this.closed||this.stopped||this.clock()>=this.deadline)return Promise.resolve({status:'closed'});
  if(!this.identity(event))return Promise.resolve({status:'ignored'});
  return this.track(this.admit(event));
 }
 async admit(event){
  const prior=this.db.prepare('SELECT status FROM messages WHERE id=?').get(event.messageId);
  if(prior)return {status:'duplicate',storedStatus:prior.status};
  if(this.db.prepare('SELECT status FROM intakes WHERE id=?').get(event.messageId)?.status==='verifying')return {status:'verification_pending'};
  this.db.prepare('INSERT INTO intakes VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,at=excluded.at').run(event.messageId,'verifying',new Date().toISOString());
  let verified;
  try{verified=await bounded('verify',signal=>this.verify(event.messageId,{signal}),{timeoutMs:this.verifyTimeoutMs,signal:this.lifetime.signal});}
  catch(e){const status=e.reason==='timeout'?'verification_timeout':e.reason==='cancelled'?'verification_cancelled':'verification_failed';this.db.prepare('UPDATE intakes SET status=? WHERE id=?').run(status,event.messageId);this.note(event.messageId,status);return {status};}
  if(this.stopped||this.clock()>=this.deadline){this.db.prepare("UPDATE intakes SET status='verification_cancelled' WHERE id=?").run(event.messageId);return {status:'closed'};}
  if(!this.identity(verified)||['appId','tenantId','senderId','chatId','messageId','text','createdAt'].some(k=>event[k]!==verified[k])){this.db.prepare("UPDATE intakes SET status='rejected_identity' WHERE id=?").run(event.messageId);return {status:'rejected_identity'};}
  this.db.prepare("UPDATE intakes SET status='verified' WHERE id=?").run(event.messageId);
  const session=hash([this.appId,this.tenantId,event.senderId,event.chatId,'probe-r1']);
  if(!this.db.prepare('SELECT k FROM sessions WHERE k=?').get(session)&&event.text!=='联调开始')return {status:'inactive'};
  const insert=this.db.prepare('INSERT OR IGNORE INTO messages VALUES(?,?,?, ?,NULL,NULL)').run(event.messageId,session,'queued',JSON.stringify({...verified,alias:this.participants.get(event.senderId)}));
  if(!insert.changes)return {status:'duplicate'};
  this.queue=this.queue.then(()=>this.process(event.messageId)).catch(e=>{this.note(event.messageId,'pipeline_failure',{reason:e.reason||'exception'});this.update(event.messageId,'pipeline_failed');});
  return {status:'queued',session};
 }
 async process(id){
  const row=this.db.prepare('SELECT * FROM messages WHERE id=?').get(id);if(!row||row.status!=='queued')return;
  if(this.stopped||this.clock()>=this.deadline){this.update(id,'cancelled_unstarted');return;}
  const data=JSON.parse(row.data);let session=this.db.prepare('SELECT * FROM sessions WHERE k=?').get(row.session);
  if(data.text==='联调开始'&&!session){session={k:row.session,marker:randomUUID(),history:'[]'};this.db.prepare('INSERT INTO sessions VALUES(?,?,?)').run(session.k,session.marker,session.history);await this.send(row,data,'合成测试会话已开始。发送“计算合成样本”可执行一次受控验证。');return;}
  if(data.text!=='计算合成样本'){await this.send(row,data,'本轮仅支持合成样本计算；身份、权限和其他会话均不能通过消息修改。');return;}
  if(this.count('calls')>=this.maxCalls){this.update(id,'call_limit');return;}
  this.db.prepare("UPDATE meta SET v=v+1 WHERE k='calls'").run();this.update(id,'running');
  let result;
  try{
   result=await bounded('execute',signal=>this.execute({marker:session.marker,alias:data.alias,history:JSON.parse(session.history),jobDir:resolve(this.jobsRoot,row.session,hash(id)),signal}),{timeoutMs:this.taskTimeoutMs,signal:this.lifetime.signal,onUnderlying:p=>this.track(p,this.workers)});
   if(this.stopped||this.clock()>=this.deadline){this.update(id,'model_failed');this.note(id,'execute_cancelled');return;}
   if(!result||Object.keys(result).sort().join(',')!=='marker,summary'||result.marker!==session.marker||typeof result.summary!=='string'||result.summary.length>1800)throw Error('INVALID_MODEL_RESULT');
  }catch(e){this.update(id,'model_failed');this.note(id,'execute_failed',{reason:e.reason||e.message});return;}
  const history=JSON.parse(session.history);history.push({input:'计算合成样本',summary:result.summary});
  this.db.prepare('UPDATE sessions SET history=? WHERE k=?').run(JSON.stringify(history.slice(-8)),row.session);
  this.update(id,'model_completed',JSON.stringify(result));
  await this.send(row,data,'【合成测试 '+session.marker+'】'+result.summary);
 }
 async send(row,data,text){
  if(this.stopped||this.clock()>=this.deadline){this.update(row.id,'completed_without_send');return;}
  if(this.count('replies')>=this.maxReplies){this.update(row.id,'reply_limit');return;}
  this.db.prepare("UPDATE meta SET v=v+1 WHERE k='replies'").run();this.update(row.id,'sending',text);
  const target=Object.freeze({messageId:data.messageId,chatId:data.chatId,senderId:data.senderId,idempotencyKey:hash(['reply',this.appId,this.tenantId,data.messageId]).slice(0,48)});
  let sent;
  try{
   sent=await bounded('reply',signal=>this.reply(target,text,{signal}),{timeoutMs:this.sendTimeoutMs,signal:this.lifetime.signal});
   if(!sent?.messageId||sent.chatId!==data.chatId)throw Error('UNCONFIRMED_SEND');
   this.update(row.id,'sent',text,sent.messageId);
  }catch(e){this.update(row.id,'reply_unknown');this.note(row.id,'reply_unknown',{reason:e.reason||e.message});return;}
  if(this.stopped||this.clock()>=this.deadline){this.note(row.id,'readback_skipped_after_stop');return;}
  try{
   const read=await bounded('readback',signal=>this.readReply(sent.messageId,{signal}),{timeoutMs:this.readbackTimeoutMs,signal:this.lifetime.signal});
   if(read?.chatId===data.chatId&&read?.text===text)this.update(row.id,'readback_verified');
   else this.note(row.id,'readback_mismatch');
  }catch(e){this.note(row.id,'readback_unverified',{reason:e.reason||e.message});}
 }
 stop(reason='operator_stop'){
  if(this.stopping)return this.stopping;
  const started=Date.now();this.stopped=true;clearTimeout(this.expiry);this.lifetime.abort();
  this.stopping=(async()=>{
   let timer,settled=false;
   const waiting=Promise.allSettled([...this.pending,this.queue,...this.workers]).then(()=>{settled=true;});
   await Promise.race([waiting,new Promise(r=>{timer=setTimeout(r,this.maxStopMs);})]);clearTimeout(timer);
   this.db.prepare("UPDATE messages SET status='cancelled_unstarted' WHERE status='queued'").run();
   this.stopReceipt={reason,elapsedMs:Date.now()-started,logicalOperations:this.pending.size,unsettledWorkers:this.workers.size,settled,confirmed:settled&&this.workers.size===0};
   this.note('broker','stop',this.stopReceipt);return this.stopReceipt;
  })();return this.stopping;
 }
 async close(){if(this.closed)return this.stopReceipt;const r=await this.stop();this.closed=true;this.db.close();if(r.confirmed)this.ownership.release();return r;}
}
