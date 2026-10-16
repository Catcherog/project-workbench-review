// One bounded local adapter process. Its only channel is a serialized stdin/stdout frame.
import fs from 'node:fs';import {DatabaseSync} from 'node:sqlite';import {randomUUID} from 'node:crypto';
import {signed,authenticated,digest,exact} from './codec.mjs';import {identity,readPolicy,authorize} from './policy.mjs';import {validateDelivery} from './grant.mjs';
let text='';for await(const chunk of process.stdin)text+=chunk;const f=JSON.parse(text);
const output=value=>console.log(JSON.stringify({rpcId:f.rpcId,...value}));
try{
 if(f.role==='engineer'){
  if(f.operation==='clarify')output({ok:true,question:'请一次确认项目、资料版本和范围：项目 X 的 v1 测试摘要，不附原始日志，交给指定合成接收人用于测试摘要审核，对吗？'});
  else if(f.operation==='sign')output({ok:true,envelope:signed('bot',identity.bot,f.payload,f.privateKey)});
  else throw Error('UNSUPPORTED_ADAPTER_OPERATION');
 }else if(f.role==='human'){
  if(f.operation!=='sign'||f.payload.synthetic!==true)throw Error('SYNTHETIC_HUMAN_ONLY');
  output({ok:true,envelope:signed('human',identity.human,f.payload,f.privateKey)});
 }else if(f.role==='receiver'){
  const authority=new DatabaseSync(f.authorityFile,{readOnly:true});const payload=authenticated(f.envelope,'bot',identity.bot,f.trust.bot);
  const id=f.operation==='deliver'?payload.snapshot?.requestId:payload.requestId;const raw=authority.prepare('SELECT * FROM requests WHERE id=?').get(id);const row=raw?{...raw,data:JSON.parse(raw.data)}:null;authority.close();
  const policy=readPolicy(f.policyFile),db=new DatabaseSync(f.receiverFile);db.exec('CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,hash TEXT,nonce TEXT UNIQUE,body TEXT,receipt TEXT);');
  try{
   if(f.operation==='deliver'){
    const s=validateDelivery(f.envelope,row,f.trust,policy,f.now);if(row.status!=='DELIVERING')throw Error('AUTHORITY_NOT_DELIVERING');
    const before=db.prepare('SELECT * FROM deliveries WHERE id=?').get(id);let receipt;
    if(before){if(before.hash!==digest(s))throw Error('RECEIVER_ID_CONFLICT');receipt=JSON.parse(before.receipt);}
    else{receipt=signed('receiver',identity.target,{kind:'local-receipt',requestId:id,snapshotHash:digest(s),contentSha256:s.contentSha256,recipient:s.recipient,target:s.target,receiptId:randomUUID(),receivedAt:f.now,synthetic:true},f.privateKey);db.prepare('INSERT INTO deliveries VALUES(?,?,?,?,?)').run(id,digest(s),s.nonce,s.body,JSON.stringify(receipt));}
    if(f.fixtureControl?.afterCommitDelayMs)await new Promise(r=>setTimeout(r,Math.min(f.fixtureControl.afterCommitDelayMs,2000)));
    output({ok:true,receipt});
   }else if(f.operation==='readback'){
    exact(payload,['kind','requestId','snapshotHash']);if(payload.kind!=='readback'||!row?.data.snapshot||digest(row.data.snapshot)!==payload.snapshotHash)throw Error('READBACK_BINDING');
    authorize(row.data.snapshot,policy,f.now);if(f.fixtureControl?.failReadback)throw Error('INJECTED_READBACK_FAILURE');
    const record=db.prepare('SELECT * FROM deliveries WHERE id=?').get(id);if(!record||record.hash!==payload.snapshotHash)throw Error('RECEIPT_NOT_FOUND');output({ok:true,body:record.body,receipt:JSON.parse(record.receipt)});
   }else throw Error('UNSUPPORTED_MESSAGE_TYPE');
  }finally{db.close();}
 }else throw Error('UNKNOWN_ADAPTER_ROLE');
}catch(e){output({ok:false,code:e.message});}
