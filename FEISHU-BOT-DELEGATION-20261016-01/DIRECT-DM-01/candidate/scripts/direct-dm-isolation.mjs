// Candidate only. No transport, event consumer, model, or automatic sender.
import {DatabaseSync} from 'node:sqlite';
import {existsSync, mkdirSync, chmodSync} from 'node:fs';
import {dirname} from 'node:path';
import {createHash} from 'node:crypto';

const sha = text => createHash('sha256').update(text).digest('hex');
const fail = message => Object.assign(Error(message), {status: 409});
const SUMMARY='合成测试：计划 10 项，通过 7 项，失败 2 项，阻塞 1 项，通过率 70%。不附原始日志。';
const schema = `
 CREATE TABLE requests(id TEXT PRIMARY KEY, manifest TEXT NOT NULL, state TEXT NOT NULL);
 CREATE TABLE messages(id TEXT PRIMARY KEY, request_id TEXT NOT NULL, stage TEXT NOT NULL, payload TEXT NOT NULL);
 CREATE TABLE effects(request_id TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(request_id,kind));
`;
export function createIsolationLedger(file) {
  if(existsSync(file))throw fail('ISOLATION_LEDGER_ALREADY_EXISTS');
  mkdirSync(dirname(file),{recursive:true,mode:0o700});
  const db = new DatabaseSync(file);
  try { db.exec(schema); } finally { db.close(); }
  chmodSync(file,0o600);
}
export function normalizeDmMessage(m) {
  let content = m.content;
  if(typeof content !== 'string' && typeof m.body?.content === 'string') {
    try { content=JSON.parse(m.body.content).text; } catch { content=m.body.content; }
  }
  const sender=m.sender||{};
  return {id:m.message_id||m.messageId||'',chatId:m.chat_id||m.chatId||'',
    senderId:m.sender_id||m.senderId||(typeof sender.id==='string'?sender.id:sender.id?.open_id||sender.open_id)||'',
    senderType:m.sender_type||sender.sender_type||sender.type||'',chatType:m.chat_type||m.chatType||'',
    parentId:m.parent_id||m.parentId||'',rootId:m.root_id||m.rootId||'',
    createdAt:Number(m.create_time||m.rawCreateTime||m.createdAt),content:typeof content==='string'?content:'',deleted:!!m.deleted};
}
export class DirectDmIsolation {
  constructor(file,{clock=()=>Date.now()}={}) {
    // Never recreate a missing/corrupt ledger: that would lose late-message exclusions.
    if(!existsSync(file))throw fail('ISOLATION_LEDGER_MISSING');
    this.db=new DatabaseSync(file); this.clock=clock;this.closed=false;
    this.db.exec('PRAGMA busy_timeout=1000; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;');
    if(this.db.prepare('PRAGMA integrity_check').get().integrity_check!=='ok')throw fail('ISOLATION_LEDGER_CORRUPT');
    this.db.prepare('SELECT id FROM requests LIMIT 1').get();
  }
  transaction(fn) {
    if(this.closed)throw fail('ISOLATION_CLOSED');
    this.db.exec('BEGIN IMMEDIATE');
    try { const value=fn();this.db.exec('COMMIT');return value; }
    catch(e){this.db.exec('ROLLBACK');throw e;}
  }
  register(manifest) {
    const m=structuredClone(manifest);
    for(const k of ['id','scope','appId','tenantKey','ownerId','participantId','botId','participantChatId','ownerChatId','nonce','preview','summary','resourceVersion','policyVersion','purpose']) {
      if(typeof m[k]!=='string'||!m[k])throw fail('MANIFEST_FIELD_MISSING:'+k);
    }
    if(!/^DIRECT-DM-[a-f0-9]{32}$/.test(m.id)||!Number.isSafeInteger(m.issuedAt)||!Number.isSafeInteger(m.expiresAt)||m.expiresAt-m.issuedAt!==300000||m.scope!==m.tenantKey+'/'+m.appId)throw fail('MANIFEST_INVALID');
    if(m.summary!==SUMMARY||m.resourceVersion!=='v1'||m.purpose!=='synthetic-test-only'||!(/^[a-f0-9]{24,64}$/).test(m.nonce)||m.summaryHash!==sha(m.summary)||m.previewHash!==sha(m.preview)||!m.preview.includes(m.summary)||!m.preview.includes(m.id)||!m.preview.includes(m.nonce))throw fail('MANIFEST_CONTENT_INVALID');
    if(m.participantChatId===m.ownerChatId||m.participantId===m.ownerId)throw fail('MANIFEST_PARTICIPANTS_INVALID');
    // Callers are trusted local setup only. Message fields never create requests or gates.
    this.transaction(()=>{
      if(this.db.prepare('SELECT 1 FROM requests WHERE id=?').get(m.id))throw fail('REQUEST_REUSE_DENIED');
      this.db.prepare('INSERT INTO requests VALUES(?,?,?)').run(m.id,JSON.stringify(m),'PREPARED');
    });
  }
  request(id) {
    if(this.closed)throw fail('ISOLATION_CLOSED');
    const row=this.db.prepare('SELECT * FROM requests WHERE id=?').get(id);
    if(!row)throw fail('REQUEST_UNKNOWN');return {...row,manifest:JSON.parse(row.manifest)};
  }
  activeScope(identity,m) {
    const actual=identity.scope||[identity.tenantKey,identity.appId].join('/');
    return actual===m.scope&&identity.userId===m.ownerId;
  }
  classify(identity,raw) {
    if(this.closed)throw fail('ISOLATION_CLOSED');
    const e=normalizeDmMessage(raw);
    const old=e.id&&this.db.prepare('SELECT * FROM messages WHERE id=?').get(e.id);
    if(old)return {requestId:old.request_id,reason:'known_message',e};
    for(const row of this.db.prepare('SELECT * FROM requests').all()) {
      const m=JSON.parse(row.manifest);
      const effects=this.db.prepare('SELECT payload FROM effects WHERE request_id=?').all(m.id).map(r=>JSON.parse(r.payload));
      const known=effects.map(x=>x.messageId).filter(Boolean);
      // An exact, pre-registered random request marker is quarantine, never authority.
      // This also holds copied/wrong-actor input without granting it access to a worker.
      if(known.includes(e.id)||known.includes(e.parentId)||known.includes(e.rootId)||e.content.includes(m.id))return {requestId:m.id,reason:'request_link',e};
      const tuple=this.activeScope(identity,m)&&[m.participantChatId,m.ownerChatId].includes(e.chatId);
      const expectedSender=e.chatId===m.participantChatId?[m.botId,m.participantId]:[m.botId,m.ownerId];
      if(tuple&&expectedSender.includes(e.senderId)) {
        if(sha(e.content)===m.previewHash||sha(e.content)===m.summaryHash)return {requestId:m.id,reason:'outbound_bytes',e};
        // The historical window remains effective on delayed polling after expiry/stop.
        if(e.createdAt>=m.issuedAt&&e.createdAt<m.expiresAt)return {requestId:m.id,reason:'bounded_session',e};
      }
    }
    return null;
  }
  hold({identity={},message,channel}) {
    const match=this.classify(identity,message);if(!match)return false;
    const {e,requestId,reason}=match;
    if(!e.id)throw fail('TEST_MESSAGE_ID_MISSING');
    const key=JSON.stringify({identity,message:e,channel,reason});
    this.db.prepare('INSERT OR IGNORE INTO messages VALUES(?,?,?,?)').run(e.id,requestId,'QUARANTINED',key);
    return true; // Synchronous durable barrier. No worker availability dependency.
  }
  sourceHeld(source) {
    const p=source.personalMessage||source.caseChat||{};
    return this.hold({identity:{scope:p.scope,userId:p.accountId},channel:'source_barrier',message:{
      message_id:p.messageId||source.inputEnvelope?.messageId,chat_id:p.chatId,sender_id:p.senderId,
      create_time:p.rawCreateTime,parent_id:p.parentId||source.inputEnvelope?.replyTo,content:source.excerpt||''}});
  }
  assertNoSources(sources=[]) {
    for(const source of sources)if(this.sourceHeld(source))throw fail('TEST_SOURCE_BLOCKED_BEFORE_SAVE');
  }
  policy(m,current) {
    if(!current||['reviewApproved','exactTextApproved','isolationInstalled','memberVisible','bindingVerified','readAllowed','discloseAllowed'].some(k=>current[k]!==true))throw fail('LIVE_GATE_NOT_SATISFIED');
    if(current.appId!==m.appId||current.participantId!==m.participantId||current.ownerId!==m.ownerId||current.policyVersion!==m.policyVersion||current.resourceVersion!==m.resourceVersion||current.summaryHash!==m.summaryHash||current.previewHash!==m.previewHash)throw fail('SNAPSHOT_CHANGED');
    if(this.clock()<m.issuedAt||this.clock()>=m.expiresAt)throw fail('REQUEST_EXPIRED');
  }
  reserveEffect(id,kind,current) {
    if(!['preview','summary'].includes(kind))throw fail('EFFECT_NOT_ALLOWED');
    return this.transaction(()=>{
      const r=this.request(id),m=r.manifest;this.policy(m,current);
      if(kind==='preview'&&r.state!=='PREPARED'||kind==='summary'&&r.state!=='CONFIRMED')throw fail('EFFECT_STATE_DENIED');
      if(this.db.prepare('SELECT 1 FROM effects WHERE request_id=? AND kind=?').get(id,kind))throw fail('EFFECT_ALREADY_RESERVED');
      const payload={text:kind==='preview'?m.preview:m.summary,recipient:kind==='preview'?m.participantId:m.ownerId,chatId:kind==='preview'?m.participantChatId:m.ownerChatId,appId:m.appId};
      this.db.prepare('INSERT INTO effects VALUES(?,?,?,?)').run(id,kind,'SENDING',JSON.stringify(payload));
      this.db.prepare('UPDATE requests SET state=? WHERE id=?').run(kind==='preview'?'PREVIEW_PENDING':'DELIVERY_PENDING',id);
      return payload;
    });
  }
  recordEffect(id,kind,result) {
    this.transaction(()=>{
      const row=this.db.prepare('SELECT * FROM effects WHERE request_id=? AND kind=?').get(id,kind);
      if(!row||row.state!=='SENDING')throw fail('EFFECT_RECEIPT_STATE_DENIED');
      const p=JSON.parse(row.payload),ok=typeof result.messageId==='string'&&!!result.messageId&&result.chatId===p.chatId;
      const state=ok?'ACCEPTED':'DELIVERY_UNKNOWN';
      this.db.prepare('UPDATE effects SET state=?,payload=? WHERE request_id=? AND kind=?').run(state,JSON.stringify({...p,...(ok?{messageId:result.messageId}:{}),platformResultKnown:ok}),id,kind);
      if(!ok&&!['STOPPED','STOP_UNKNOWN'].includes(this.request(id).state))this.db.prepare('UPDATE requests SET state=? WHERE id=?').run('DELIVERY_UNKNOWN',id);
    });
  }
  readbackEffect(id,kind,readback) {
    this.transaction(()=>{
      const r=this.request(id),m=r.manifest,row=this.db.prepare('SELECT * FROM effects WHERE request_id=? AND kind=?').get(id,kind);
      if(!row||row.state!=='ACCEPTED')throw fail('EFFECT_NOT_ACCEPTED');
      const p=JSON.parse(row.payload),e=normalizeDmMessage(readback);
      const ok=e.id===p.messageId&&e.chatId===p.chatId&&e.senderId===m.botId&&e.content===p.text&&!e.deleted;
      this.db.prepare('UPDATE effects SET state=? WHERE request_id=? AND kind=?').run(ok?'READBACK_VERIFIED':'READBACK_FAILED',id,kind);
      if(!['STOPPED','STOP_UNKNOWN'].includes(r.state))this.db.prepare('UPDATE requests SET state=? WHERE id=?').run(ok?(kind==='preview'?'AWAITING_CONFIRMATION':'DELIVERED_READBACK_VERIFIED'):'READBACK_FAILED',id);
      if(!ok)return;
      this.hold({identity:{scope:m.scope,userId:m.ownerId},message:readback,channel:'outbound_readback'});
    });
  }
  async confirm(id,event,{identity,verify,current,timeoutMs=1000}) {
    if(timeoutMs<1||timeoutMs>30000)throw fail('VERIFY_TIMEOUT_INVALID');
    const r=this.request(id),m=r.manifest;
    if(!this.hold({identity,message:event,channel:'confirmation'}))throw fail('UNBOUND_CONFIRMATION');
    const e=normalizeDmMessage(event);
    const preview=this.db.prepare('SELECT * FROM effects WHERE request_id=? AND kind=?').get(id,'preview');
    if(r.state!=='AWAITING_CONFIRMATION'||preview?.state!=='READBACK_VERIFIED')throw fail('CONFIRMATION_STATE_DENIED');
    this.policy(m,current());
    if(!this.activeScope(identity,m)||e.senderId!==m.participantId||e.senderType!=='user'||e.chatType!=='p2p'||e.chatId!==m.participantChatId||e.deleted||!Number.isSafeInteger(e.createdAt)||e.createdAt<m.issuedAt||e.createdAt>=m.expiresAt)throw fail('CONFIRMATION_IDENTITY_OR_TIME_DENIED');
    const parent=JSON.parse(preview.payload).messageId;
    if(e.parentId!==parent&&e.rootId!==parent)throw fail('CONFIRMATION_MUST_REPLY_TO_PREVIEW');
    let timer,verified;const controller=new AbortController();
    try { verified=await Promise.race([verify(e.id,{signal:controller.signal}),new Promise((_,reject)=>timer=setTimeout(()=>{controller.abort();reject(fail('READBACK_TIMEOUT'));},timeoutMs))]); }
    finally {clearTimeout(timer);controller.abort();}
    const read=normalizeDmMessage(verified);
    if(['id','chatId','senderId','senderType','chatType','parentId','rootId','createdAt','content','deleted'].some(k=>read[k]!==e[k]))throw fail('CONFIRMATION_READBACK_MISMATCH');
    return this.transaction(()=>{
      if(this.request(id).state!=='AWAITING_CONFIRMATION')throw fail('CONFIRMATION_ALREADY_USED_OR_STOPPED');
      this.policy(m,current());
      if(e.content==='拒绝'||e.content===`拒绝 ${id}`){this.db.prepare('UPDATE requests SET state=? WHERE id=?').run('REJECTED',id);return 'REJECTED';}
      if(e.content!==`确认 ${id} ${m.nonce}`)throw fail('EXACT_CONFIRMATION_REQUIRED');
      this.db.prepare('UPDATE requests SET state=? WHERE id=?').run('CONFIRMED',id);
      return 'CONFIRMED';
    });
  }
  stop(id,{confirmed=true}={}) {
    this.request(id);this.db.prepare('UPDATE requests SET state=? WHERE id=?').run(confirmed?'STOPPED':'STOP_UNKNOWN',id);
    // Keep manifests, effects and message IDs permanently; ordinary future traffic is unblocked.
  }
  status(id) {
    const r=this.request(id);
    return {state:r.state,effects:this.db.prepare('SELECT kind,state FROM effects WHERE request_id=?').all(id),quarantined:this.db.prepare('SELECT COUNT(*) n FROM messages WHERE request_id=?').get(id).n};
  }
  close(){this.closed=true;this.db.close();}
}
