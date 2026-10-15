import {DatabaseSync} from 'node:sqlite';
import {mkdirSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
import {hash} from './codex.mjs';

// A transport adapter must verify the original message with the platform first.
// R1 ships no enabled live adapter: application scope and production routing are blocked.
export class ProbeBroker{
 constructor({file,appId,tenantId,participants,deadline,verify,execute,reply,readReply,clock=()=>Date.now(),maxCalls=20,taskTimeoutMs=180000,maxReplies=40}){
  if(!Number.isFinite(deadline)||deadline<=clock()||deadline-clock()>3600000)throw Error('INVALID_WINDOW');
  if(maxCalls<1||maxCalls>20||taskTimeoutMs<1||taskTimeoutMs>180000||maxReplies<1||maxReplies>40)throw Error('INVALID_LIMITS');
  Object.assign(this,{appId,tenantId,participants:new Map(participants.map(x=>[x.id,x.alias])),deadline,verify,execute,reply,readReply,clock,maxCalls,taskTimeoutMs,maxReplies});
  mkdirSync(dirname(file),{recursive:true,mode:0o700});this.db=new DatabaseSync(file);this.jobsRoot=resolve(dirname(file),'jobs');
  this.db.exec('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v INTEGER); CREATE TABLE IF NOT EXISTS sessions(k TEXT PRIMARY KEY,marker TEXT,history TEXT); CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,session TEXT,status TEXT,data TEXT,output TEXT,reply_id TEXT);');
  this.db.prepare('INSERT OR IGNORE INTO meta VALUES(?,0)').run('calls');this.db.prepare('INSERT OR IGNORE INTO meta VALUES(?,0)').run('replies');
  // Never replay an uncertain side effect after restart.
  this.db.exec("UPDATE messages SET status='interrupted' WHERE status='running'; UPDATE messages SET status='reply_unknown' WHERE status='sending';");
  this.db.prepare('INSERT OR IGNORE INTO meta VALUES(?,?)').run('startedAt',clock());
  this.db.prepare('INSERT OR IGNORE INTO meta VALUES(?,?)').run('deadline',deadline);
  this.startedAt=this.count('startedAt');
  if(this.count('deadline')!==deadline){this.db.close();throw Error('WINDOW_CANNOT_RENEW');}
  this.queue=Promise.resolve();this.stopped=false;
 }
 count(k){return this.db.prepare('SELECT v FROM meta WHERE k=?').get(k).v;}
 identity(e){return e&&e.appId===this.appId&&e.tenantId===this.tenantId&&e.chatType==='p2p'&&e.senderType==='user'&&this.participants.has(e.senderId)&&typeof e.chatId==='string'&&e.chatId.length>0&&e.chatId.length<160&&typeof e.messageId==='string'&&e.messageId.length>0&&e.messageId.length<160&&typeof e.text==='string'&&e.text.length<=2000&&Number.isFinite(e.createdAt)&&e.createdAt<=this.clock()+30000&&e.createdAt>=this.startedAt;}
 async accept(event){
  if(this.stopped||this.clock()>=this.deadline)return {status:'closed'};
  if(!this.identity(event))return {status:'ignored'};
  const verified=await this.verify(event.messageId); // The model does not provide identity.
  if(!this.identity(verified)||['appId','tenantId','senderId','chatId','messageId','text','createdAt'].some(k=>event[k]!==verified[k]))return {status:'rejected_identity'};
  const session=hash([this.appId,this.tenantId,event.senderId,event.chatId,'probe-r1']);
  if(!this.db.prepare('SELECT k FROM sessions WHERE k=?').get(session)&&event.text!=='联调开始')return {status:'inactive'};
  const data={...verified,alias:this.participants.get(event.senderId)};
  const insert=this.db.prepare('INSERT OR IGNORE INTO messages VALUES(?,?,?, ?,NULL,NULL)').run(event.messageId,session,'queued',JSON.stringify(data));
  if(!insert.changes)return {status:'duplicate'};
  // Persisted admission returns before the worker starts. One worker is within the <=2 limit.
  this.queue=this.queue.then(()=>this.process(event.messageId)).catch(()=>{});
  return {status:'queued',session};
 }
 update(id,status,output=null,replyId=null){this.db.prepare('UPDATE messages SET status=?,output=?,reply_id=? WHERE id=?').run(status,output,replyId,id);}
 async process(id){
  const row=this.db.prepare('SELECT * FROM messages WHERE id=?').get(id);if(!row||row.status!=='queued')return;
  if(this.stopped||this.clock()>=this.deadline){this.update(id,'expired');return;}
  const data=JSON.parse(row.data);let session=this.db.prepare('SELECT * FROM sessions WHERE k=?').get(row.session);
  if(data.text==='联调开始'&&!session){session={k:row.session,marker:randomUUID(),history:'[]'};this.db.prepare('INSERT INTO sessions VALUES(?,?,?)').run(session.k,session.marker,session.history);await this.send(row,data,'合成测试会话已开始。发送“计算合成样本”可执行一次受控验证。');return;}
  // Explicit test commands keep this prototype's capability surface narrow.
  if(data.text!=='计算合成样本'){await this.send(row,data,'本轮仅支持合成样本计算；身份、权限和其他会话均不能通过消息修改。');return;}
  if(this.count('calls')>=this.maxCalls){this.update(id,'call_limit');return;}
  this.db.prepare("UPDATE meta SET v=v+1 WHERE k='calls'").run();this.update(id,'running');
  let timer;const controller=new AbortController();
  try{
   const work=this.execute({marker:session.marker,alias:data.alias,history:JSON.parse(session.history),jobDir:resolve(this.jobsRoot,row.session,hash(id)),signal:controller.signal});
   const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>{reject(Error('TASK_TIMEOUT'));controller.abort();},this.taskTimeoutMs);});
   const result=await Promise.race([work,timeout]);clearTimeout(timer);
   // No destination or path from the model is accepted, even if extra keys are valid JSON.
   if(!result||Object.keys(result).sort().join(',')!=='marker,summary'||result.marker!==session.marker||typeof result.summary!=='string'||result.summary.length>1800)throw Error('INVALID_MODEL_RESULT');
   const history=JSON.parse(session.history);history.push({input:'计算合成样本',summary:result.summary});
   this.db.prepare('UPDATE sessions SET history=? WHERE k=?').run(JSON.stringify(history.slice(-8)),row.session);
   this.update(id,'model_completed',JSON.stringify(result));
   if(this.stopped||this.clock()>=this.deadline){this.update(id,'completed_after_window',JSON.stringify(result));return;}
   await this.send(row,data,'【合成测试 '+session.marker+'】'+result.summary);
  }catch{this.update(id,'model_failed');}finally{clearTimeout(timer);}
 }
 async send(row,data,text){
  if(this.stopped||this.clock()>=this.deadline){this.update(row.id,'expired');return;}
  if(this.count('replies')>=this.maxReplies){this.update(row.id,'reply_limit');return;}
  this.db.prepare("UPDATE meta SET v=v+1 WHERE k='replies'").run();this.update(row.id,'sending',text);
  const target={messageId:data.messageId,chatId:data.chatId,senderId:data.senderId,idempotencyKey:hash(['reply',this.appId,this.tenantId,data.messageId]).slice(0,48)};
  try{
   const sent=await this.reply(Object.freeze(target),text);
   if(!sent?.messageId||sent.chatId!==data.chatId)throw Error('UNCONFIRMED_SEND');
   this.update(row.id,'sent',text,sent.messageId);
   try{const read=await this.readReply(sent.messageId);if(read?.chatId===data.chatId&&read?.text===text)this.update(row.id,'readback_verified',text,sent.messageId);}catch{/* Sent remains distinct from readback. */}
  }catch{this.update(row.id,'reply_unknown',text);}
 }
 async stop(){this.stopped=true;await this.queue;}
 async close(){await this.stop();this.db.close();}
}
