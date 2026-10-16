// Exact bot transport. Instantiating this class performs no I/O or registration.
import {execFile} from 'node:child_process';
import {readFileSync,realpathSync} from 'node:fs';
import {createHash} from 'node:crypto';
const hash=b=>createHash('sha256').update(b).digest('hex');
const fail=code=>{throw Object.assign(Error(code),{status:409});};
export const runCli=(file,args,{signal}={})=>new Promise((resolve,reject)=>execFile(file,args,{shell:false,signal,timeout:30000,maxBuffer:1024*1024,env:{...process.env,LARKSUITE_CLI_NO_UPDATE_NOTIFIER:'1',LARKSUITE_CLI_NO_SKILLS_NOTIFIER:'1'}},(error,stdout,stderr)=>{
 if(error)return reject(Object.assign(Error('PLATFORM_CALL_UNCERTAIN'),{causeCode:error.code}));
 try{resolve(JSON.parse(stdout));}catch{reject(Error('PLATFORM_RESPONSE_INVALID'));}
}));
export class DirectDmTransport {
 constructor({cli,cliHash,binding,runner=runCli}={}){
  if(!cli||!(/^[a-f0-9]{64}$/).test(cliHash||''))fail('CLI_NOT_PINNED');
  this.cli=realpathSync(cli);this.cliHash=cliHash;this.runner=runner;
  Object.defineProperty(this,'binding',{value:Object.freeze(structuredClone(binding)),enumerable:true});
  for(const key of ['appId','tenantKey','ownerId','participantId','botId','ownerChatId','participantChatId'])if(!binding?.[key])fail('BINDING_INCOMPLETE');
  if(binding.ownerChatId===binding.participantChatId)fail('BINDING_INCOMPLETE');
 }
 async call(args,{signal}={}){
  if(hash(readFileSync(this.cli))!==this.cliHash)fail('CLI_BYTES_CHANGED');
  return this.runner(this.cli,args,{signal});
 }
 async assertIdentity({signal}={}){
  const b=this.binding,who=await this.call(['whoami','--as','bot'],{signal});
  if(who.identity!=='bot'||who.available!==true||who.appId!==b.appId||who.brand!=='feishu')fail('PLATFORM_APP_CHANGED');
  const user=await this.call(['whoami','--as','user'],{signal});
  if(user.identity!=='user'||user.appId!==b.appId||user.onBehalfOf?.openId!==b.ownerId||user.available!==true)fail('PLATFORM_OPERATOR_CHANGED');
  const profile=await this.call(['api','GET','/open-apis/authen/v1/user_info','--as','user'],{signal});
  if(profile.ok!==true||profile.identity!=='user'||profile.data?.open_id!==b.ownerId||profile.data?.tenant_key!==b.tenantKey)fail('PLATFORM_TENANT_CHANGED');
  const bot=await this.call(['api','GET','/open-apis/bot/v3/info','--as','bot'],{signal});
  if(bot.ok!==true||bot.identity!=='bot'||bot.data?.open_id!==b.botId||bot.data?.activate_status!==2)fail('PLATFORM_BOT_CHANGED');
 }
 async send(payload,{idempotencyKey,signal,beforeSend}={}){
  const b=this.binding,chat=payload.recipient===b.participantId?b.participantChatId:payload.recipient===b.ownerId?b.ownerChatId:null;
  if(!chat||payload.chatId!==chat||payload.appId!==b.appId||typeof payload.text!=='string')fail('SEND_BINDING_INVALID');
  await this.assertIdentity({signal});beforeSend?.();
  const result=await this.call(['im','+messages-send','--as','bot','--chat-id',chat,'--text',payload.text,'--idempotency-key',idempotencyKey],{signal});
  if(result.ok!==true||result.identity!=='bot'||!/^om_[\w-]+$/.test(result.data?.message_id||'')||result.data?.chat_id!==chat)fail('SEND_RECEIPT_UNCERTAIN');
  return {messageId:result.data.message_id,chatId:result.data.chat_id};
 }
 async read(messageId,{signal}={}){
  if(!/^om_[\w-]+$/.test(messageId||''))fail('MESSAGE_ID_INVALID');
  await this.assertIdentity({signal});
  // Raw API retains millisecond time and root/parent; the display shortcut may
  // replace create_time with a minute-level formatted string.
  const response=await this.call(['api','GET','/open-apis/im/v1/messages/'+messageId,'--as','bot'],{signal});
  if(response.ok!==true||response.identity!=='bot'||response.data?.items?.length!==1)fail('READBACK_SHAPE_INVALID');
  const m=response.data.items[0],b=this.binding;
  if(m.message_id!==messageId||![b.ownerChatId,b.participantChatId].includes(m.chat_id)||m.msg_type!=='text'||m.deleted||m.sender?.tenant_key!==b.tenantKey)fail('READBACK_BINDING_INVALID');
  let content;try{content=JSON.parse(m.body.content).text;}catch{fail('READBACK_BODY_INVALID');}
  if(typeof content!=='string'||!/^\d{13}$/.test(String(m.create_time)))fail('READBACK_FIELDS_INCOMPLETE');
  let senderId=m.sender.id;
  if(m.sender.sender_type==='app'){
   if(m.sender.id_type==='app_id'&&senderId===b.appId)senderId=b.botId;
   else if(m.sender.id_type!=='open_id'||senderId!==b.botId)fail('READBACK_BOT_INVALID');
  }else if(m.sender.sender_type!=='user'||m.sender.id_type!=='open_id')fail('READBACK_SENDER_INVALID');
  return {message_id:m.message_id,chat_id:m.chat_id,chat_type:'p2p',sender_id:senderId,sender_type:m.sender.sender_type,parent_id:m.parent_id||'',root_id:m.root_id||'',create_time:Number(m.create_time),content,deleted:false};
 }
}
