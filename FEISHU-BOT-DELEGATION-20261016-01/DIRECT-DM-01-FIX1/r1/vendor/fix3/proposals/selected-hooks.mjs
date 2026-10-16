// Generated from exact candidate hook bodies; imports/other methods are test doubles. Never used in production.
import {createHash,randomUUID} from 'node:crypto';
const hash=x=>createHash('sha256').update(JSON.stringify(x)).digest('hex');
const fail=(m,status=409)=>Object.assign(Error(m),{status});
const mappedReply=()=>'';
const fingerprint=x=>hash(x);
const queryTime=(x)=>new Date(x).toISOString();
class NewGroupReader{constructor(client){this.client=client;}read(input){return this.client.readGroup(input);}}
export class EventHook{
 async ingest(workspaceId,key,event){
  const control=this.monitor.control(workspaceId);if(!control.enabled||!control.eventPush?.enabled||control.restored)return;
  const identity=await this.client.identity({signal:AbortSignal.timeout(30000)});
  if(control.identity&&(control.identity.scope!==identity.scope||control.identity.userId!==identity.userId))throw fail('事件读取账号与已开启的采集身份不一致');
  const probeMatch=this.testIngress?.match({identity,event,key});
  if(probeMatch){await this.testIngress.handle(probeMatch);return;}
  let source,reply;
  if(key==='im.message.receive_v1'){
   if(!/^om_[\w-]+$/.test(event.message_id||''))throw fail('推送缺少可核对的消息身份');
   const s=this.store.load(workspaceId),scoped=s.sources.some(row=>row.chatScope?.state==='active'&&row.chatScope.chatId===event.chat_id)||s.cases.some(row=>!row.archived&&row.status!=='已关闭'&&row.chatBinding?.chatId===event.chat_id)||!!control.discoveryState?.groups?.[event.chat_id]||event.mentions?.some(m=>m.id===identity.userId);
   const linked=!!mappedReply(s,event.parent_id||event.root_id),selfPrivate=event.chat_type==='p2p'&&event.sender_id===identity.userId;
   if(!linked&&!selfPrivate&&(event.chat_type!=='group'||!scoped||event.sender_id===identity.userId))return;
   const raw=await this.client.run(['api','GET','/open-apis/im/v1/messages/mget','--params',JSON.stringify({message_ids:[event.message_id],with_sender_name:true}),'--as','user'],{signal:AbortSignal.timeout(30000)});
   const verified=raw.items?.find(m=>m.message_id===event.message_id);if(!verified||verified.chat_id!==event.chat_id||verified.deleted)throw fail('推送原消息无法按本人权限回读');
   const readable=await this.client.run(['im','+messages-mget','--message-ids',event.message_id,'--no-reactions','--as','user'],{signal:AbortSignal.timeout(30000)}),m=readable.messages?.find(m=>m.message_id===event.message_id);if(!m||typeof m.content!=='string')throw fail('推送原消息正文读取不完整');
   const senderId=verified.sender?.id||Object.values(m.sender||{}).find(v=>v===event.sender_id);if(!senderId||senderId!==event.sender_id)throw fail('推送发送人未通过原消息回读核对');
   const parentId=verified.parent_id||verified.root_id||'';if(parentId||selfPrivate)reply={parentId,senderId};
   const id='personal-message-'+hash([identity.scope,identity.userId,event.message_id]).slice(0,28),stamp=new Date(Number(verified.create_time)).toISOString();if(Date.parse(stamp)<Date.parse(control.startedAt))return;
   source={id,title:(m.chat_name||'飞书群新消息').slice(0,160),type:'飞书事件消息',excerpt:m.content,occurredAt:stamp,url:m.message_app_link||'https://applink.feishu.cn/client/chat/open?openChatId='+event.chat_id,personalMessage:{messageId:event.message_id,chatId:event.chat_id,scope:identity.scope,accountId:identity.userId,senderId:event.sender_id,channels:['group-discovery'],messageType:verified.msg_type,rawCreateTime:verified.create_time,rawUpdateTime:verified.update_time,deleted:false,history:[]}};
  }else if(key==='vc.note.generated_v1'){
   if(!/^[A-Za-z0-9]{8,160}$/.test(event.note_token||''))throw fail('纪要事件没有有效文档标识');const stamp=new Date(Number(event.timestamp)).toISOString();if(Date.parse(stamp)<Date.parse(control.startedAt))return;
   source={id:'risk-note-'+hash([identity.scope,identity.userId,event.note_token]).slice(0,32),title:'新生成的会议纪要',type:'飞书纪要事件',excerpt:'https://feishu.cn/docx/'+event.note_token,url:'https://feishu.cn/docx/'+event.note_token,occurredAt:stamp,riskEvent:{schemaVersion:1,eventId:event.event_id,eventType:key,scope:identity.scope,accountId:identity.userId}};
  }else return;
  const after=await this.client.identity({signal:AbortSignal.timeout(30000)});if(after.scope!==identity.scope||after.userId!==identity.userId)throw fail('事件读取期间登录身份变化');
  this.store.transaction(()=>{const c=this.monitor.control(workspaceId);if(!c.enabled||!c.eventPush?.enabled||c.generation!==control.generation)throw fail('事件接入范围已变化');
   const s=this.store.load(workspaceId),prior=s.sources.find(row=>row.id===source.id);if(prior?.excerpt===source.excerpt)return;
   const at=new Date().toISOString(),row={...(prior||{}),...source,projectIds:prior?.projectIds||[],sourceIds:prior?.sourceIds||[],objectIds:prior?.objectIds||[],version:(prior?.version||0)+1,collectedAt:at,updatedAt:at,confirmed:false};
   this.domain.applySourceSubjectAssociation(s,row);
   if(row.personalMessage&&prior?.personalMessage)row.personalMessage.history=[...(prior.personalMessage.history||[]),{excerpt:prior.excerpt,at:prior.collectedAt,version:prior.version}];
   if(prior)Object.assign(prior,row);else s.sources.push(row);s.revision++;const errors=this.domain.validateState(s);if(errors.length)throw fail(errors.map(e=>e.message).join('；'));this.store.save(s,s.revision-1);
   c.eventPush.received=(c.eventPush.received||0)+1;c.eventPush.lastEventAt=at;c.eventPush.error='';this.monitor.save(workspaceId,c);
  });
  if(reply&&this.onMessage)await this.onMessage({workspaceId,sourceId:source.id,identity,...reply});
 }
}
export class MonitorHook{
  async run(workspaceId, initial, signal) {
    const signalWithTimeout = AbortSignal.any([signal, AbortSignal.timeout(90000)]);
    this.capture(workspaceId);
    let c = this.control(workspaceId); c.lastAttemptAt = this.clock(); this.save(workspaceId, c);
    try {
      if (initial.personal) {
        const identity = await this.reader.identity({ signal: signalWithTimeout });
        if (initial.identity && (initial.identity.scope !== identity.scope || initial.identity.userId !== identity.userId)) throw fail('飞书登录账号或应用已变化，已停止个人消息采集', 409);
        this.store.transaction(()=>{const current=this.control(workspaceId);if(!current.enabled||current.revision!==initial.revision)throw fail('采集设置已变化',409);current.identity={scope:identity.scope,userId:identity.userId};this.save(workspaceId,current);});
        const windowSeconds=Math.max(30,Math.min(3600,initial.windowSeconds||3600)),wall=this.clock();
        const start=new Date(Math.max(Date.parse(initial.startedAt),Date.parse(initial.personalThrough||initial.startedAt)-Math.min(15*60,windowSeconds/4)*1000)).toISOString();
        const end=new Date(Math.min(Date.parse(wall),Date.parse(start)+windowSeconds*1000)).toISOString();
        const result = await this.reader.read({ start, end, signal: signalWithTimeout, discoverGroups:!!initial.discoverGroups, discoveryState:initial.discoveryState||{}, filterTestMessages:this.testIngress?messages=>this.testIngress.filterPolled({identity,messages}):undefined });
        const afterIdentity=await this.reader.identity({signal:signalWithTimeout});
        if(afterIdentity.scope!==identity.scope||afterIdentity.userId!==identity.userId)throw fail('读取期间飞书账号发生变化，本轮消息未保存',409);
        if (signalWithTimeout.aborted) throw fail('本轮读取已取消');
        if(this.testIngress)result.messages=await this.testIngress.filterPolled({identity,messages:result.messages});
        this.store.transaction(() => {
          c = this.control(workspaceId);
          if (!c.enabled || c.revision !== initial.revision || c.generation !== initial.generation) throw fail('采集设置已变化，本轮结果未写入', 409);
          const before = this.store.load(workspaceId), next = structuredClone(before); let changed = 0;
          for (const message of result.messages) {
            const sender = typeof message.sender.id === 'string' ? message.sender.id : message.sender.id?.open_id || message.sender.open_id;
            if (!sender) throw fail('无法确认消息发送人，未保存本轮结果');
            if (sender === identity.userId) continue;
            const stamp = /^\d+$/.test(String(message.create_time)) ? new Date(Number(message.create_time) * (String(message.create_time).length <= 10 ? 1000 : 1)).toISOString() : new Date(message.create_time).toISOString();
            if (Date.parse(stamp) < Date.parse(initial.startedAt) || Date.parse(stamp) > Date.parse(end)) continue;
            const shared=next.sources.find(row=>{const m=row.personalMessage||row.caseChat;return m?.scope===identity.scope&&m.accountId===identity.userId&&m.messageId===message.message_id;});
            const id = shared?.id || 'personal-message-' + hash([identity.scope, identity.userId, message.message_id]).slice(0, 28);
            const old = next.sources.find(s => s.id === id), personalMessage = { messageId: message.message_id, chatId: message.chat_id,
              accountId: identity.userId, scope: identity.scope, senderId: sender, channels: message.channels, discovery:message.discovery, deleted: !!message.deleted, messageType: message.msg_type || 'unknown',rawCreateTime:message.create_time,rawUpdateTime:message.update_time||'',history:old?[...(old.personalMessage?.history||[]),{version:old.version,excerpt:old.excerpt,at:old.collectedAt}]:[] };
            const title = (message.chat_name || message.chat_partner?.name || message.sender.name || '飞书消息').slice(0, 160);
            const source = { ...(old || {}), id, title, projectIds: old?.projectIds || [], sourceIds: [], objectIds: old?.objectIds || [],
              type: message.channels.includes('group-discovery') ? '飞书新群消息' : message.channels.includes('private') ? '飞书私聊' : '飞书@消息', excerpt: message.deleted ? '' : message.content,
              occurredAt: stamp, collectedAt: end, updatedAt: end, createdAt: old?.createdAt || end, archived: !!message.deleted,
              confirmed: false, author: message.sender.name || sender, version: (old?.version || 0) + 1, personalMessage,
              url: this.domain.safeFeishuUrl(message.message_app_link||'') };
            this.domain.applySourceSubjectAssociation(next,source);
            if (old && fingerprint(old) === fingerprint(source)) continue;
            if (old) Object.assign(old, source); else next.sources.push(source); changed++;
          }
          if (changed) {
            next.revision++; next.audit.push({ id: 'personal-intake-' + randomUUID(), time: end, operation: 'personal.message.read', actor: '个人消息采集', objectId: workspaceId, revision: next.revision, before: null, after: { changed, from: start, to: end } });
            const errors = this.domain.validateState(next); if (errors.length) throw fail('个人消息入库校验失败：' + errors.map(e => e.message).join('；'));
            this.store.save(next, before.revision);
          }
          c.identity = { scope: identity.scope, userId: identity.userId };
          if(initial.discoverGroups&&result.discoveryState)c.discoveryState=result.discoveryState;
          if (result.complete) c.personalThrough = new Date(Math.max(Date.parse(c.personalThrough||c.startedAt),Date.parse(end))).toISOString();
          c.windowSeconds=result.complete?Math.min(3600,windowSeconds*2):Math.max(30,Math.floor(windowSeconds/2));
          c.lastError = (result.issues || []).join('；'); c.lastSucceededAt = result.complete ? end : c.lastSucceededAt;
          this.save(workspaceId, c);
        });
      }
      this.capture(workspaceId);
      c = this.control(workspaceId); c.failures = 0;
      if (!initial.personal) { c.lastSucceededAt = this.clock(); c.lastError = ''; }
      this.save(workspaceId, c);
    } catch (error) {
      c = this.control(workspaceId);
      if (!signal.aborted) { c.failures++; c.lastError = error.message; }
      this.save(workspaceId, c);
    } finally {
      c = this.control(workspaceId);
      c.nextReadAt = c.enabled ? new Date(Date.parse(this.clock()) + Math.min(3600, c.intervalSeconds * 2 ** Math.min(c.failures, 5)) * 1000).toISOString() : '';
      this.save(workspaceId, c);
    }
    return this.status(workspaceId);
  }
}
export class ReaderHook{
  async read({ start, end, signal, discoverGroups = false, discoveryState = {}, filterTestMessages }) {
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
          const prior = messages.get(row.message_id);
          messages.set(row.message_id, { ...row,display_time:row.create_time,create_time:original.create_time,update_time:original.update_time,
            deleted:!!row.deleted||!!original.deleted,channels: [...new Set([...(prior?.channels || []), channel])] });
        }
        if (!data.has_more) break;
        if (!data.page_token || seen.has(data.page_token)) throw fail('个人消息分页游标异常，未推进读取起点');
        token = data.page_token; seen.add(token);
        if (page === 19) issues.push(`${channel === 'private' ? '私聊' : '@消息'}超出本轮分页范围；保留读取起点，下轮继续核对`);
      }
    }
    if(filterTestMessages){const ordinary=await filterTestMessages([...messages.values()]);messages.clear();for(const row of ordinary)messages.set(row.message_id,row);}
    let discovered;
    if(discoverGroups){
      try{
        discovered=await new NewGroupReader(this.client).read({start,end,signal,state:discoveryState,triggers:[...messages.values()].filter(row=>row.channels.includes('mention'))});
        issues.push(...discovered.issues);
        for(const row of discovered.messages){const prior=messages.get(row.message_id);messages.set(row.message_id,{...prior,...row,channels:[...new Set([...(prior?.channels||[]),...row.channels])]});}
      }catch(error){if(signal?.aborted)throw error;issues.push('新群发现：'+error.message);}
    }
    return { messages: [...messages.values()], complete: !issues.length, issues, ...(discovered?{discoveryState:discovered.state}:{}) };
  }
}
