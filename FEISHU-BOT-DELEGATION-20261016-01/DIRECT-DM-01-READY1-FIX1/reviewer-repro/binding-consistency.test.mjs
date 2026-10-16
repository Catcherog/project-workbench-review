// Independent defensive regression, synthetic identities only; no network/real CLI.
// Six READY1 modules are byte-identical; the workbench host/store integration is a fixture.
import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync,readFileSync,writeFileSync,readdirSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {generateKeyPairSync,sign} from 'node:crypto';
import {createIsolationLedger} from './candidate/scripts/direct-dm-isolation.mjs';
import {attachDirectDmIsolation} from './candidate/scripts/direct-dm-activation.mjs';
import {canonical,digest,bindingOf} from './candidate/scripts/direct-dm-authority.mjs';
import {composeDirectDmController} from './candidate/scripts/direct-dm-runtime.mjs';

const here=dirname(fileURLToPath(import.meta.url)),root=join(here,'candidate');
const SUMMARY='合成测试：计划 10 项，通过 7 项，失败 2 项，阻塞 1 项，通过率 70%。不附原始日志。';
const NOW=1792140000000;
const observations=[];
const writeJson=(file,value)=>writeFileSync(file,JSON.stringify(value,null,2),{mode:0o600});
class FixtureStore{
 constructor(dir){this.dir=dir;this.db=new DatabaseSync(join(dir,'fixture-host.sqlite'));this.db.exec('CREATE TABLE settings(k TEXT PRIMARY KEY,v TEXT NOT NULL);PRAGMA user_version=2');}
 getSetting(k){const r=this.db.prepare('SELECT v FROM settings WHERE k=?').get(k);return r?JSON.parse(r.v):null;}
 setSetting(k,v){this.db.prepare('INSERT INTO settings VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v').run(k,JSON.stringify(v));}
 transaction(fn){this.db.exec('BEGIN IMMEDIATE');try{const r=fn();this.db.exec('COMMIT');return r;}catch(e){this.db.exec('ROLLBACK');throw e;}}
}
async function scenario(name,{configPatch={},platformPatch={},tamperSignature=false}={}){
 const dir=mkdtempSync(join(tmpdir(),'ready1-binding-review-'));
 let store,gate,controller;
 const o={name,realPlatformCalls:0,fakeSendCalls:0,registered:false,error:null};
 try{
  store=new FixtureStore(dir);const ledger=join(dir,'synthetic-isolation.sqlite');
  createIsolationLedger(ledger);gate=attachDirectDmIsolation({store,configuredFile:ledger,clock:()=>NOW});
  const id='DIRECT-DM-'+'a'.repeat(32),nonce='b'.repeat(24);
  const m={id,appId:'cli_synthetic_app',tenantKey:'tenant_approved',scope:'tenant_approved/cli_synthetic_app',ownerId:'ou_approved_owner',participantId:'ou_approved_participant',botId:'ou_approved_bot',ownerChatId:'oc_approved_owner',participantChatId:'oc_approved_participant',nonce,issuedAt:NOW,expiresAt:NOW+300000,resourceVersion:'v1',policyVersion:'synthetic-policy-v1',purpose:'synthetic-test-only',summary:SUMMARY};
  m.preview=`合成审核测试，不发送真人。${SUMMARY}\n${id}\n${nonce}`;m.previewHash=digest(m.preview);m.summaryHash=digest(m.summary);
  const build={version:1,files:readdirSync(join(root,'scripts')).filter(x=>x.endsWith('.mjs')).sort().map(x=>({path:'scripts/'+x,sha256:digest(readFileSync(join(root,'scripts',x),'utf8'))}))};
  const buildManifest=join(dir,'fixture-build-manifest.json');writeJson(buildManifest,build);
  const {publicKey,privateKey}=generateKeyPairSync('ed25519'),pub=publicKey.export({type:'spki',format:'pem'});
  const payload={version:1,task:'DIRECT-DM-01-READY1',revoked:false,buildHash:digest(build),manifestHash:digest(m),binding:bindingOf(m),notBefore:NOW-1000,expiresAt:NOW+300000,ledgerId:gate.ledgerId,evidence:Object.fromEntries(['review','installation','exactText','isolationPrinciple','memberVisibility','conversationBinding','read','disclose'].map(k=>[k,{approved:true,reference:'SYNTHETIC-REVIEWER-FIXTURE:'+k,sha256:digest('synthetic:'+k)}]))};
  const approvalFile=join(dir,'synthetic-approval.json');let signature=sign(null,Buffer.from(canonical(payload)),privateKey).toString('base64');
  if(tamperSignature)signature=Buffer.alloc(64).toString('base64');writeJson(approvalFile,{payload,signature});
  const cli=join(dir,'never-executed-cli.txt');writeFileSync(cli,'synthetic runner only\n',{mode:0o600});
  const c={version:1,enabled:true,buildManifest,buildHash:digest(build),approvalFile,publicKey:pub,publicKeyHash:digest(pub),cli,cliHash:digest('synthetic runner only\n'),binding:{...bindingOf(m),...configPatch}};
  const configFile=join(dir,'synthetic-config.json');writeJson(configFile,c);
  const actual={...c.binding,...platformPatch};const messages=new Map();
  const runner=async(file,args)=>{
   if(file!==cli)throw Error('UNEXPECTED_CLI');
   if(args[0]==='whoami'&&args[2]==='bot')return {identity:'bot',available:true,appId:actual.appId,brand:'feishu'};
   if(args[0]==='whoami'&&args[2]==='user')return {identity:'user',available:true,appId:actual.appId,onBehalfOf:{openId:actual.ownerId}};
   if(args[2]==='/open-apis/authen/v1/user_info')return {ok:true,identity:'user',data:{open_id:actual.ownerId,tenant_key:actual.tenantKey}};
   if(args[2]==='/open-apis/bot/v3/info')return {ok:true,identity:'bot',data:{open_id:actual.botId,activate_status:2}};
   if(args[0]==='im'&&args[1]==='+messages-send'){
    o.fakeSendCalls++;
    const chat=args[args.indexOf('--chat-id')+1],text=args[args.indexOf('--text')+1],messageId='om_synthetic_preview_'+o.fakeSendCalls;
    messages.set(messageId,{message_id:messageId,chat_id:chat,msg_type:'text',sender:{id:actual.botId,id_type:'open_id',sender_type:'app',tenant_key:actual.tenantKey},create_time:String(NOW),body:{content:JSON.stringify({text})},deleted:false});
    return {ok:true,identity:'bot',data:{message_id:messageId,chat_id:chat}};
   }
   if(args[0]==='api'&&args[1]==='GET'&&args[2].startsWith('/open-apis/im/v1/messages/'))return {ok:true,identity:'bot',data:{items:[messages.get(args[2].split('/').at(-1))]}};
   throw Error('UNEXPECTED_SYNTHETIC_CALL:'+JSON.stringify(args));
  };
  controller=composeDirectDmController({store,configFile,root,runner,clock:()=>NOW});
  try{controller.register(m);o.registered=true;await controller.deliver(m.id,'preview');}catch(e){o.error=e.message;}
  o.requestState=o.registered?gate.status(m.id).state:null;
  o.databaseCapability=store.db.prepare('PRAGMA user_version').get().user_version;
  if(o.registered){
   const ordinary={message_id:'om_ordinary_synthetic',chat_id:actual.participantChatId,sender_id:actual.participantId,create_time:NOW+1,content:'普通合成消息，没有请求标识'};
   o.actualScopeOrdinaryHeld=gate.hold({identity:{scope:actual.tenantKey+'/'+actual.appId,userId:actual.ownerId,appId:actual.appId,tenantKey:actual.tenantKey},message:ordinary,channel:'reviewer-fixture'});
  }
  return o;
 }finally{
  observations.push(o);writeJson(join(here,'observations.json'),observations);
  if(controller)await controller.close();gate?.close();store?.db.close();rmSync(dir,{recursive:true,force:true});
 }
}

test('CONTROL: matching approved/config/platform bindings permit one synthetic preview',async()=>{
 const r=await scenario('matching');assert.equal(r.error,null);assert.equal(r.fakeSendCalls,1);assert.equal(r.requestState,'AWAITING_CONFIRMATION');assert.equal(r.actualScopeOrdinaryHeld,true);
});
test('CONTROL: platform tenant drifting from local config is blocked before send',async()=>{
 const r=await scenario('platform-tenant-drift',{platformPatch:{tenantKey:'tenant_live_changed'}});assert.equal(r.fakeSendCalls,0);assert.equal(r.error,'PLATFORM_TENANT_CHANGED');
});
test('B01 tenant: initial local tenant differing from signed approval must be denied before send',async()=>{
 const r=await scenario('initial-config-tenant-mismatch',{configPatch:{tenantKey:'tenant_not_approved',scope:'tenant_not_approved/cli_synthetic_app'}});assert.equal(r.fakeSendCalls,0,JSON.stringify(r));
});
test('B01 bot: initial local bot differing from signed approval must be denied before send',async()=>{
 const r=await scenario('initial-config-bot-mismatch',{configPatch:{botId:'ou_not_approved_bot'}});assert.equal(r.fakeSendCalls,0,JSON.stringify(r));
});
test('B01 owner: initial local operator differing from signed approval must be denied before send',async()=>{
 const r=await scenario('initial-config-owner-mismatch',{configPatch:{ownerId:'ou_not_approved_operator'}});assert.equal(r.fakeSendCalls,0,JSON.stringify(r));
});
test('CONTROL: recipient chat mismatch is blocked before send',async()=>{
 const r=await scenario('initial-config-chat-mismatch',{configPatch:{participantChatId:'oc_not_approved'}});assert.equal(r.fakeSendCalls,0);assert.match(r.error,/^(SEND_BINDING_INVALID|EXECUTION_BINDING_MISMATCH)$/); // READY1-FIX1 rejects before admission; only error name changed.
});
test('CONTROL: invalid signature is blocked before registration or capability change',async()=>{
 const r=await scenario('invalid-signature',{tamperSignature:true});assert.equal(r.fakeSendCalls,0);assert.equal(r.registered,false);assert.equal(r.databaseCapability,2);assert.equal(r.error,'APPROVAL_SIGNATURE_INVALID');
});
