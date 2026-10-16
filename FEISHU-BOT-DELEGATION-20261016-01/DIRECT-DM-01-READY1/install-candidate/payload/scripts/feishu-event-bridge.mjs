import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {FeishuTaskClient} from './feishu-task-client.mjs';
import {mappedReply} from './core-feishu-input.mjs';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const keys=[['im.message.receive_v1','bot'],['vc.note.generated_v1','user']];
const fail=message=>Object.assign(Error(message),{status:409});

/** The CLI owns WebSocket authentication and the shared bus. This bridge owns
 * only its two consume subprocesses, and never stops another consumer's bus. */
export class FeishuEventBridge {
 constructor({store,domain,monitor,client=new FeishuTaskClient(),launch=spawn,testMode=false,onMessage}={}){Object.assign(this,{store,domain,monitor,client,launch,testMode,onMessage});this.children=new Map();this.retries=new Map();this.streams={};this.queue=Promise.resolve();this.queued=0;this.closed=false;}
 status(id){const c=this.monitor.control(id);return {enabled:!!c.eventPush?.enabled,revision:c.eventPush?.revision||0,streams:this.streams,lastEventAt:c.eventPush?.lastEventAt||'',received:c.eventPush?.received||0,error:c.eventPush?.error||'',coverage:'消息推送覆盖机器人可接收、且本人已授权采集的群；不覆盖本人全部私聊或没有机器人的群。用户纪要事件独立接收。未覆盖来源仍由原增量采集补齐。'};}
 enabled(){return this.store.list().filter(w=>w.type!=='restored'&&this.monitor.control(w.id).enabled&&this.monitor.control(w.id).eventPush?.enabled);}
 configure(id,input){const c=this.monitor.control(id);if(typeof input.enabled!=='boolean'||input.revision!==(c.eventPush?.revision||0))throw fail('事件接入设置已变化，请刷新');if(c.restored&&input.enabled)throw fail('恢复工作区不能接收实时事件');c.eventPush={...(c.eventPush||{}),enabled:input.enabled,revision:(c.eventPush?.revision||0)+1,error:''};this.monitor.save(id,c);this.sync();return this.status(id);}
 update(id,fn){const c=this.monitor.control(id);c.eventPush||={enabled:false,revision:0};fn(c.eventPush);this.monitor.save(id,c);}
 start(){this.sync();}
 sync(){
  if(this.closed)return;if(!this.enabled().length){for(const child of this.children.values())child.stdin.end();return;}
  for(const [key,identity]of keys)if(!this.children.has(key)&&!this.retries.has(key))this.consume(key,identity);
 }
 consume(key,identity,attempt=0){
  if(this.closed||!this.enabled().length)return;
  if(this.testMode){this.streams[key]={status:'simulation',identity};return;}
  const child=this.launch(this.client.cli,['event','consume',key,'--as',identity],{shell:false,stdio:['pipe','pipe','pipe']});this.children.set(key,child);this.streams[key]={status:'connecting',identity};
  let stdout='',stderr='',ready=false,authFailure=false;const pending=[];
  const diagnose=error=>{this.streams[key]={status:'error',identity,error:String(error).slice(0,1000)};};
  const event=line=>{try{const data=JSON.parse(line);if(ready)this.receive(key,data);else pending.push(data);}catch{diagnose('事件格式无法读取，需要核对增量补采范围');}};
  child.stdout.on('data',data=>{stdout+=data.toString();if(stdout.length>2*1024*1024){diagnose('事件输出超过限制，保留补采缺口');child.stdin.end();return;}let p;while((p=stdout.indexOf('\n'))>=0){const line=stdout.slice(0,p);stdout=stdout.slice(p+1);if(line.trim())event(line);}});
  child.stderr.on('data',data=>{stderr+=data.toString();let p;while((p=stderr.indexOf('\n'))>=0){const line=stderr.slice(0,p);stderr=stderr.slice(p+1);
   if(line.includes('[event] ready event_key='+key)){ready=true;this.streams[key]={status:'listening',identity,readyAt:new Date().toISOString()};for(const data of pending.splice(0))this.receive(key,data);}
   else if(line.startsWith('{'))try{const v=JSON.parse(line);if(v.ok===false){authFailure=['authorization','validation'].includes(v.error?.type);diagnose(v.error?.message||'事件连接失败');}}catch{/* Non-JSON diagnostics never become instructions. */}
   else if(/WARN|drop|overflow/i.test(line))diagnose('事件通道报告丢弃或读取缺口，请查看增量补采状态');
  }});
  child.on('error',error=>diagnose(error.message));
  child.on('close',code=>{this.children.delete(key);if(this.closed||!this.enabled().length)return;if(authFailure){this.streams[key].status='blocked';return;}diagnose('事件连接已断开，正在重连（'+code+'）');const timer=setTimeout(()=>{this.retries.delete(key);this.consume(key,identity,attempt+1);},Math.min(60000,1000*2**Math.min(attempt,6)));timer.unref();this.retries.set(key,timer);});
 }
 receive(key,event){
  if(this.closed)return;if(this.queued>=200){for(const w of this.enabled())this.update(w.id,c=>c.error='事件队列已满，已标记增量补采缺口');return;}
  this.queued++;this.queue=this.queue.then(async()=>{for(const w of this.enabled())try{await this.ingest(w.id,key,event);}catch(error){this.update(w.id,c=>c.error=error.message);}}).finally(()=>this.queued--);
 }
 async ingest(workspaceId,key,event){
  const control=this.monitor.control(workspaceId);if(!control.enabled||!control.eventPush?.enabled||control.restored)return;
  const identity=await this.client.identity({signal:AbortSignal.timeout(30000)});
  if(control.identity&&(control.identity.scope!==identity.scope||control.identity.userId!==identity.userId))throw fail('事件读取账号与已开启的采集身份不一致');
  if(key==='im.message.receive_v1'&&this.store.directDmIsolation?.hold({identity,message:event,channel:'event_bridge'})){
   // Durable quarantine wins even when the execution adapter is absent/fails.
   if(this.onIsolatedMessage)try{await this.onIsolatedMessage({identity,message:event});}catch{/* Never fall through to business storage. */}
   return;
  }
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
   source={id,title:(m.chat_name||'飞书群新消息').slice(0,160),type:'飞书事件消息',excerpt:m.content,occurredAt:stamp,url:m.message_app_link||'https://applink.feishu.cn/client/chat/open?openChatId='+event.chat_id,personalMessage:{messageId:event.message_id,chatId:event.chat_id,scope:identity.scope,accountId:identity.userId,senderId:event.sender_id,parentId:verified.parent_id||event.parent_id||'',rootId:verified.root_id||event.root_id||'',chatType:verified.chat_type||event.chat_type||'',channels:['group-discovery'],messageType:verified.msg_type,rawCreateTime:verified.create_time,rawUpdateTime:verified.update_time,deleted:false,history:[]}};
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
 async close(){this.closed=true;for(const timer of this.retries.values())clearTimeout(timer);this.retries.clear();await Promise.allSettled([...this.children.values()].map(child=>new Promise(resolve=>{child.once('close',resolve);child.stdin.end();const t=setTimeout(()=>{child.kill('SIGTERM');resolve();},10000);t.unref();child.once('close',()=>clearTimeout(t));})));await this.queue;}
}
