import { FeishuTaskClient } from './feishu-task-client.mjs';
import { NewGroupReader } from './new-group-reader.mjs';

const fail = message => Object.assign(new Error(message), { status: 502 });
// Feishu rejects fractional seconds in these search filters. Use explicit UTC
// offsets; retain millisecond timestamps from raw mget for boundary checks.
const queryTime = (value, upper=false) => {
  const stamp=Date.parse(value);if(!Number.isFinite(stamp))throw fail('消息读取时段无效');
  return new Date((upper?Math.ceil(stamp/1000):Math.floor(stamp/1000))*1000).toISOString().replace(/\.\d{3}Z$/, '+00:00');
};
export class PersonalMessageReader {
  constructor({ client = new FeishuTaskClient() } = {}) { this.client = client; }
  identity(options) { return this.client.identity(options); }
  async read({ start, end, signal, discoverGroups = false, discoveryState = {}, identity, isolation }) {
    const messages = new Map(), issues = [];
    const from=queryTime(start),to=queryTime(end,true);
    for (const [channel, filter] of [['private', ['--chat-type', 'p2p']], ['mention', ['--is-at-me']]]) {
      let token = ''; const seen = new Set();
      for (let page = 0; page < 20; page++) {
        const data = await this.client.run(['im', '+messages-search', '--query', '', ...filter, '--start', from, '--end', to, '--page-size', '50', '--no-reactions', '--as', 'user', ...(token ? ['--page-token', token] : [])], { signal });
        if (!Array.isArray(data?.messages) || typeof data.has_more !== 'boolean') throw fail('个人消息读取结果不完整，未推进读取起点');
        // The shortcut renders create_time as YYYY-MM-DD HH:mm, losing seconds
        // and timezone. Never parse that display string as an exact timestamp.
        const ids=data.messages.map(row=>row.message_id);
        if(ids.some(id=>!/^om_[\w-]+$/.test(id||'')))throw fail('消息身份缺失，未推进读取起点');
        const raw=ids.length?await this.client.run(['api','GET','/open-apis/im/v1/messages/mget','--params',JSON.stringify({message_ids:ids,card_msg_content_type:'raw_card_content',with_sender_name:true}),'--as','user'],{signal}):{items:[]};
        if(!Array.isArray(raw.items))throw fail('消息原始时间未完整返回');
        const stamps=new Map(raw.items.map(row=>[row.message_id,row]));
        for (const row of data.messages) {
          if (!/^om_[\w-]+$/.test(row.message_id || '') || !row.chat_id || !row.sender || typeof row.content !== 'string') throw fail('消息身份或正文缺失，未推进读取起点');
          const original=stamps.get(row.message_id);
          if(!original||original.chat_id!==row.chat_id||!/^\d{13}$/.test(original.create_time||''))throw fail('消息原始时间或所属会话无法核对，未推进读取起点');
          if(isolation?.hold({identity,message:{...row,...original,content:row.content},channel:'personal_'+channel}))continue;
          const prior = messages.get(row.message_id);
          messages.set(row.message_id, { ...row,display_time:row.create_time,create_time:original.create_time,update_time:original.update_time,
            parent_id:original.parent_id||row.parent_id||'',root_id:original.root_id||row.root_id||'',chat_type:original.chat_type||row.chat_type||(channel==='private'?'p2p':''),
            deleted:!!row.deleted||!!original.deleted,channels: [...new Set([...(prior?.channels || []), channel])] });
        }
        if (!data.has_more) break;
        if (!data.page_token || seen.has(data.page_token)) throw fail('个人消息分页游标异常，未推进读取起点');
        token = data.page_token; seen.add(token);
        if (page === 19) issues.push(`${channel === 'private' ? '私聊' : '@消息'}超出本轮分页范围；保留读取起点，下轮继续核对`);
      }
    }
    let discovered;
    if(discoverGroups){
      try{
        discovered=await new NewGroupReader(this.client).read({start,end,signal,state:discoveryState,identity,isolation,triggers:[...messages.values()].filter(row=>row.channels.includes('mention'))});
        issues.push(...discovered.issues);
        for(const row of discovered.messages){const prior=messages.get(row.message_id);messages.set(row.message_id,{...prior,...row,channels:[...new Set([...(prior?.channels||[]),...row.channels])]});}
      }catch(error){if(signal?.aborted)throw error;issues.push('新群发现：'+error.message);}
    }
    return { messages: [...messages.values()], complete: !issues.length, issues, ...(discovered?{discoveryState:discovered.state}:{}) };
  }
}
