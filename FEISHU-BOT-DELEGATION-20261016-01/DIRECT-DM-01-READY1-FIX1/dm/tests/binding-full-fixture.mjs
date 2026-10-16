import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,chmodSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {generateKeyPairSync,sign} from 'node:crypto';
import {fullFixture,blockedExternal,restoreExecutionGuard} from './full-service-fixture.mjs';
import {digest,canonical,bindingOf} from '../candidate/scripts/direct-dm-authority.mjs';
import {verifyBuild} from '../candidate/scripts/direct-dm-runtime.mjs';

const root=resolve(import.meta.dirname,'../candidate');
export async function setup({arm=false,configPatch={},platformPatch={}}={}){
 const c=await fullFixture(),m=c.f.manifest,buildManifest=join(root,'build-manifest.json'),buildHash=verifyBuild(root,buildManifest);
 const {publicKey,privateKey}=generateKeyPairSync('ed25519'),pem=publicKey.export({type:'spki',format:'pem'}),approvalFile=join(c.dir,'approval.json'),configFile=join(c.dir,'control.json'),cli=join(c.dir,'synthetic-cli');
 writeFileSync(cli,'synthetic executable pinned by hash; runner supplied in test mode');
 const config={version:1,enabled:true,buildManifest,buildHash,publicKey:pem,publicKeyHash:digest(pem),approvalFile,cli,cliHash:digest(readFileSync(cli,'utf8')),binding:{...bindingOf(m),...configPatch}};
 writeFileSync(configFile,JSON.stringify(config),{mode:0o600});
 const actual={...config.binding,...platformPatch};
 const state={calls:[],sends:[],messages:new Map(),mode:'ok',readHook:null,identityHook:null};
 const raw=(id,chat,text,who='app')=>({message_id:id,chat_id:chat,msg_type:'text',sender:{id:who==='app'?m.appId:m.participantId,id_type:who==='app'?'app_id':'open_id',sender_type:who,tenant_key:m.tenantKey},body:{content:JSON.stringify({text})},create_time:String(m.issuedAt+(who==='app'?0:100)),deleted:false});
 const runner=async(_file,args,{signal}={})=>{
  state.calls.push([...args]);assert.equal(args.at(-1)==='user'||args.includes('bot')||args.includes('user'),true);
  if(args[0]==='whoami'){const identity=args.at(-1);return {identity,available:true,appId:state.mode==='wrongApp'?'other':actual.appId,brand:'feishu',onBehalfOf:{openId:actual.ownerId}};}
  if(args[2]==='/open-apis/bot/v3/info'){await state.identityHook?.();return {ok:true,identity:'bot',data:{open_id:actual.botId,activate_status:2}};}
  if(args[2]==='/open-apis/authen/v1/user_info')return {ok:true,identity:'user',data:{open_id:actual.ownerId,tenant_key:state.mode==='wrongTenant'?'other':actual.tenantKey}};
  if(args[1]==='+messages-send'){
   assert.equal(args[args.indexOf('--as')+1],'bot');
   const chat=args[args.indexOf('--chat-id')+1],text=args[args.indexOf('--text')+1],id='om_ready_'+(state.sends.length+1);
   state.sends.push({chat,text,id,idempotencyKey:args[args.indexOf('--idempotency-key')+1]});
   if(state.mode==='lostReceipt')throw Error('SYNTHETIC_LOST_RECEIPT');
   state.messages.set(id,raw(id,chat,text));return {ok:true,identity:'bot',data:{message_id:id,chat_id:chat}};
  }
  if(args[2]?.startsWith('/open-apis/im/v1/messages/')){
   const id=args[2].split('/').at(-1);if(state.readHook)await state.readHook(id);
   if(state.mode==='readFailure')throw Error('SYNTHETIC_READ_FAILURE');
   const value=structuredClone(state.messages.get(id));
   if(state.mode==='wrongBody')value.body.content=JSON.stringify({text:'changed'});
   if(state.mode==='formattedTime')value.create_time='2026-10-16 16:00';
   if(state.mode==='wrongSender')value.sender.id='other';
   if(state.mode==='wrongMessageTenant')value.sender.tenant_key='other';
   return {ok:true,identity:'bot',data:{items:value?[value]:[]}};
  }
  throw Error('UNEXPECTED_OFFLINE_CLI_CALL');
 };
 const app=await c.start({directDmControlFile:configFile,directDmRuntimeOptions:{runner,clock:()=>c.state.now}});if(arm)c.arm();c.state.now=m.issuedAt+1;
 const payload={version:1,task:'DIRECT-DM-01-READY1',revoked:false,buildHash,manifestHash:digest(m),binding:bindingOf(m),ledgerId:app.store.directDmIsolation.ledgerId,notBefore:m.issuedAt,expiresAt:m.expiresAt,evidence:Object.fromEntries(['review','installation','exactText','isolationPrinciple','memberVisibility','conversationBinding','read','disclose'].map(k=>[k,{approved:true,reference:'synthetic-only:'+k,sha256:digest('synthetic:'+k)}]))};
 function approve(change){if(change)change(payload);writeFileSync(approvalFile,JSON.stringify({payload,signature:sign(null,Buffer.from(canonical(payload)),privateKey).toString('base64')}),{mode:0o600});}
 approve();
 function confirmation(){const event={...c.f.event,parent_id:state.sends[0].id};const r=raw(event.message_id,event.chat_id,event.content,'user');r.parent_id=event.parent_id;state.messages.set(event.message_id,r);return event;}
 app.agentMonitor.configure('official',{revision:0,enabled:true,personal:true,discoverGroups:true,intervalSeconds:60});app.eventBridge.configure('official',{revision:0,enabled:true});
 return {c,app,m,state,actual,config,configFile,approvalFile,payload,approve,confirmation,runner,async close(){await c.dispose();assert.equal(c.state.externalModels,0);assert.equal(blockedExternal.length,0);}};
}
