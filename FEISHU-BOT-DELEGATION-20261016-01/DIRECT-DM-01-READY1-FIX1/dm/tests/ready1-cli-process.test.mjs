import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {DirectDmTransport} from '../candidate/scripts/direct-dm-transport.mjs';
import {digest} from '../candidate/scripts/direct-dm-authority.mjs';
const binding={appId:'app_synthetic',tenantKey:'tenant_synthetic',ownerId:'ou_owner',participantId:'ou_participant',botId:'ou_bot',ownerChatId:'oc_owner',participantChatId:'oc_participant'};
function client(){
 const dir=mkdtempSync(join(tmpdir(),'ready1-cli-')),cli=join(dir,'fake-cli'),log=join(dir,'calls.jsonl');
 const program=`#!${process.execPath}\nconst fs=require('node:fs');const a=process.argv.slice(2);fs.appendFileSync(${JSON.stringify(log)},JSON.stringify(a)+'\\n');let v;const b=${JSON.stringify(binding)};if(a[0]==='whoami'){const identity=a.at(-1);v={identity,brand:'feishu',available:true,appId:b.appId,onBehalfOf:{openId:b.ownerId}};}else if(a[2]==='/open-apis/authen/v1/user_info')v={ok:true,identity:'user',data:{open_id:b.ownerId,tenant_key:b.tenantKey}};else if(a[2]==='/open-apis/bot/v3/info')v={ok:true,identity:'bot',data:{open_id:b.botId,activate_status:2}};else if(a[1]==='+messages-send')v={ok:true,identity:'bot',data:{message_id:'om_local',chat_id:a[a.indexOf('--chat-id')+1]}};else process.exit(9);console.log(JSON.stringify(v));\n`;
 writeFileSync(cli,program,{mode:0o700});return {cli,log,transport:new DirectDmTransport({cli,cliHash:digest(program),binding})};
}
test('READY1 real child process preserves exact literal arguments without a shell',async()=>{
 const c=client(),text='one\n`do-not-execute` $(do-not-execute) "quoted" \\ literal';
 assert.deepEqual(await c.transport.send({appId:binding.appId,chatId:binding.participantChatId,recipient:binding.participantId,text},{idempotencyKey:'synthetic-key'}),{messageId:'om_local',chatId:binding.participantChatId});
 const calls=readFileSync(c.log,'utf8').trim().split('\n').map(JSON.parse),send=calls.at(-1);assert.equal(calls.length,5);assert.equal(send[send.indexOf('--text')+1],text);assert.equal(send[send.indexOf('--as')+1],'bot');
});
test('READY1 changed CLI bytes prevent every subprocess',async()=>{
 const c=client();writeFileSync(c.cli,'changed');await assert.rejects(c.transport.send({appId:binding.appId,chatId:binding.participantChatId,recipient:binding.participantId,text:'synthetic'},{idempotencyKey:'key'}),/CLI_BYTES_CHANGED/);
});
test('READY1 final pre-send revocation permits identity reads but no send process',async()=>{
 const c=client();await assert.rejects(c.transport.send({appId:binding.appId,chatId:binding.participantChatId,recipient:binding.participantId,text:'synthetic'},{idempotencyKey:'key',beforeSend:()=>{throw Error('REVOKED');}}),/REVOKED/);assert.equal(readFileSync(c.log,'utf8').trim().split('\n').length,4);
});
