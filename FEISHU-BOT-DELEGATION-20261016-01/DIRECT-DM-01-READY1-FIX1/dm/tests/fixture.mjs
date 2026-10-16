import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash,randomBytes} from 'node:crypto';
import {DirectDmIsolation,createIsolationLedger} from '../candidate/scripts/direct-dm-isolation.mjs';
export const digest=s=>createHash('sha256').update(s).digest('hex');
export function fixture() {
  const directory=mkdtempSync(join(tmpdir(),'direct-dm-offline-')),file=join(directory,'isolation.sqlite');
  createIsolationLedger(file);let now=1792137600000;
  const gate=new DirectDmIsolation(file,{clock:()=>now});
  const id='DIRECT-DM-'+randomBytes(16).toString('hex'),nonce=randomBytes(12).toString('hex');
  const summary='合成测试：计划 10 项，通过 7 项，失败 2 项，阻塞 1 项，通过率 70%。不附原始日志。';
  const preview=`仅合成测试。请使用回复功能回应此预览。${summary}\n确认 ${id} ${nonce}`;
  const manifest={id,scope:'fixture-tenant/fixture-app',appId:'fixture-app',tenantKey:'fixture-tenant',ownerId:'ou_fixture_owner',participantId:'ou_fixture_participant',botId:'ou_fixture_bot',participantChatId:'oc_fixture_bot_participant',ownerChatId:'oc_fixture_bot_owner',nonce,summary,preview,summaryHash:digest(summary),previewHash:digest(preview),resourceVersion:'v1',policyVersion:'direct-dm-v1',purpose:'synthetic-test-only',issuedAt:now,expiresAt:now+300000};
  gate.register(manifest);
  const identity={scope:manifest.scope,appId:manifest.appId,tenantKey:manifest.tenantKey,userId:manifest.ownerId};
  const policy={...manifest,reviewApproved:true,exactTextApproved:true,isolationInstalled:true,memberVisible:true,bindingVerified:true,readAllowed:true,discloseAllowed:true};
  const event={message_id:'om_fixture_confirmation',chat_id:manifest.participantChatId,sender_id:manifest.participantId,sender_type:'user',chat_type:'p2p',parent_id:'om_fixture_preview',create_time:now+100,content:`确认 ${id} ${nonce}`};
  const previewRead={message_id:'om_fixture_preview',chat_id:manifest.participantChatId,sender_id:manifest.botId,chat_type:'p2p',sender_type:'app',create_time:now,content:preview};
  function sentPreview(){gate.reserveEffect(id,'preview',policy);gate.recordEffect(id,'preview',{messageId:'om_fixture_preview',chatId:manifest.participantChatId});gate.readbackEffect(id,'preview',previewRead);}
  return {directory,file,gate,manifest,identity,policy,event,previewRead,sentPreview,setTime:t=>now=t,confirm:()=>gate.confirm(id,event,{identity,verify:async()=>event,current:()=>policy}),close:()=>gate.close()};
}
