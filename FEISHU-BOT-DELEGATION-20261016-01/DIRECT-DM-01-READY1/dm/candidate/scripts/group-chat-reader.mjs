import {createHash} from 'node:crypto';
const fail=message=>Object.assign(Error(message),{status:409});
function bodyText(raw){
  for(const input of [raw.body?.content,raw.content]){
    if(typeof input!=='string')continue;
    try{const value=JSON.parse(input);if(typeof value.text==='string')return value.text;if(value.file_key)return JSON.stringify({file_key:value.file_key,file_name:value.file_name||''});}catch{/* Shortcut text may already be decoded. */}
    const file=input.match(/<file\b[^>]*key="([^"]+)"[^>]*name="([^"]*)"[^>]*>/i);
    if(file)return JSON.stringify({file_key:file[1],file_name:file[2].replace(/&quot;/g,'"').replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>')});
  }
  return typeof raw.content==='string'?raw.content:raw.body?.content||'';
}
export function normalizeGroupMessage(raw,shortcut=raw){
  const sender=raw.sender||shortcut.sender||{},id=typeof sender.id==='string'?sender.id:sender.id?.open_id||sender.open_id||'';
  return {...shortcut,...raw,content:bodyText({...raw,content:shortcut.content??raw.content}),thread_id:raw.thread_id||shortcut.thread_id||'',sender:{...sender,id,name:shortcut.sender?.name||sender.name||''},deleted:!!raw.deleted||!!shortcut.deleted};
}
export function groupMessageFingerprint(raw){
  const value=normalizeGroupMessage(raw);
  return createHash('sha256').update(JSON.stringify([value.message_id,value.chat_id,value.msg_type,value.content,value.thread_id||'',!!value.deleted])).digest('hex');
}
export async function verifiedGroupMessages(client,messages,chatId,{signal}={}){
  const visible=messages.filter(message=>message.msg_type!=='system'),ids=visible.map(message=>message.message_id);
  if(ids.some(id=>typeof id!=='string'||!/^om_[\w-]+$/.test(id)))throw fail('群消息身份不完整');
  const result=ids.length?await client.run(['api','GET','/open-apis/im/v1/messages/mget','--params',JSON.stringify({message_ids:ids,with_sender_name:true}),'--as','user'],{signal}):{items:[]};
  if(!Array.isArray(result.items))throw fail('群消息原始正文和时间未完整返回');
  return visible.map(shortcut=>{
    const raw=result.items.find(item=>item.message_id===shortcut.message_id);
    if(!raw||raw.chat_id!==chatId||!/^\d{13}$/.test(raw.create_time||''))throw fail('群消息所属会话或原始时间无法核对');
    return normalizeGroupMessage(raw,shortcut);
  });
}
