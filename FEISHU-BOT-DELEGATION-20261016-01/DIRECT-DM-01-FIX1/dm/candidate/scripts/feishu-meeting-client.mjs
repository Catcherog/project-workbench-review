import {createHash} from 'node:crypto';
import {readFile, mkdtemp, rm} from 'node:fs/promises';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {FeishuTaskClient} from './feishu-task-client.mjs';

const fail=(message,status=502)=>Object.assign(new Error(message),{status});
const tokenPattern=/^[A-Za-z0-9_-]{8,160}$/;
export function meetingDocumentToken(value){
  if(typeof value==='string'&&tokenPattern.test(value))return value;
  try{const u=new URL(value);if(u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&(u.hostname==='feishu.cn'||u.hostname.endsWith('.feishu.cn'))){const match=u.pathname.match(/^\/docx\/([A-Za-z0-9_-]{8,160})\/?$/);if(match)return match[1];}}catch{}
  throw fail('请使用飞书 docx 纪要链接；当前入口不支持其他类型链接。',422);
}
export class FeishuMeetingClient {
  constructor({client=new FeishuTaskClient()}={}){this.client=client;}
  identity(options){return this.client.identity(options);}
  run(args,options){return this.client.run([...args,'--as','user'],options);}
  async event(calendarId,eventId,options){
    const data=await this.run(['calendar','events','get','--params',JSON.stringify({calendar_id:calendarId,event_id:eventId,user_id_type:'open_id',need_meeting_settings:true,need_attendee:true})],options);
    if(data?.event?.event_id!==eventId)throw fail('日程回读身份不一致',409);
    const event=data.event;
    // Never infer that a truncated attendee list is complete.
    if(event.has_more_attendee||!Array.isArray(event.attendees)||typeof event.has_more_attendee!=='boolean')event.attendees=await this.attendees(calendarId,eventId,options);
    event.has_more_attendee=false;
    return event;
  }
  async attendees(calendarId,eventId,options){
    const items=[],seen=new Set();let token='';
    for(let page=0;page<100;page++){
      const data=await this.run(['calendar','event.attendees','list','--params',JSON.stringify({calendar_id:calendarId,event_id:eventId,user_id_type:'open_id',page_size:100,...(token?{page_token:token}:{})})],options);
      if(!Array.isArray(data?.items)||typeof data.has_more!=='boolean')throw fail('参会人列表未完整返回');
      items.push(...data.items);if(!data.has_more)return items;
      if(!data.page_token||seen.has(data.page_token))throw fail('参会人分页未完成');
      token=data.page_token;seen.add(token);
    }throw fail('参会人超过读取上限');
  }
  async createEvent(calendarId,body,key,options){
    const data=await this.run(['calendar','events','create','--params',JSON.stringify({calendar_id:calendarId,idempotency_key:key,user_id_type:'open_id'}),'--data',JSON.stringify(body)],options);
    if(!data?.event?.event_id)throw fail('创建返回缺少日程身份，结果待核对');
    return data.event;
  }
  async patchEvent(calendarId,eventId,body,options){
    const data=await this.run(['calendar','events','patch','--params',JSON.stringify({calendar_id:calendarId,event_id:eventId,user_id_type:'open_id'}),'--data',JSON.stringify(body)],options);
    if(data?.event?.event_id!==eventId)throw fail('更新返回缺少匹配日程，结果待核对');
    return data.event;
  }
  async cancelEvent(calendarId,eventId,notify,options){
    await this.run(['calendar','events','delete','--params',JSON.stringify({calendar_id:calendarId,event_id:eventId,need_notification:String(notify)})],options);
    return {eventId}; // Only a subsequent get with status=cancelled is a cancellation receipt.
  }
  async addAttendee(calendarId,eventId,userId,notify,options){
    return this.run(['calendar','event.attendees','create','--params',JSON.stringify({calendar_id:calendarId,event_id:eventId,user_id_type:'open_id'}),'--data',JSON.stringify({attendees:[{type:'user',user_id:userId}],add_operator_to_attendee:false,need_notification:notify})],options);
  }
  async removeAttendee(calendarId,eventId,attendeeId,notify,options){
    return this.run(['calendar','event.attendees','batch_delete','--params',JSON.stringify({calendar_id:calendarId,event_id:eventId,user_id_type:'open_id'}),'--data',JSON.stringify({attendee_ids:[attendeeId],need_notification:notify})],options);
  }
  async upload(calendarId,file,filename,options){
    const bytes=await readFile(filename);
    if(bytes.length!==file.size||createHash('sha256').update(bytes).digest('hex')!==file.sha256)throw Object.assign(fail('附件已变化，停止上传',409),{definiteFailure:true});
    const data=await this.run(['api','POST','/open-apis/drive/v1/medias/upload_all','--data',JSON.stringify({file_name:file.name,parent_type:'calendar',parent_node:calendarId,size:file.size}),'--file',filename],options);
    if(!data?.file_token)throw fail('上传返回缺少文件身份，结果待核对');
    return {file_token:data.file_token};
  }
  async verifyMedia(token,file,options){
    const folder=await mkdtemp(path.join(tmpdir(),'pm-calendar-preview-'));
    try{
      const filename=path.join(folder,'content');
      await this.run(['docs','+media-preview','--token',token,'--output',filename],options);
      const bytes=await readFile(filename),sha256=createHash('sha256').update(bytes).digest('hex');
      if(bytes.length!==file.size||sha256!==file.sha256)throw fail('附件预览内容与原件不一致',409);
      return {file_token:token,sha256,size:bytes.length,method:'media-preview'};
    }finally{await rm(folder,{recursive:true,force:true});}
  }
  async calendars(options){
    const items=[],seen=new Set();let pageToken='';
    for(let page=0;page<40;page++){
      const data=await this.run(['calendar','calendars','list','--params',JSON.stringify({page_size:1000,...(pageToken?{page_token:pageToken}:{})})],options);
      if(!Array.isArray(data?.calendar_list)||typeof data.has_more!=='boolean')throw fail('日历列表未完整返回');
      items.push(...data.calendar_list);if(!data.has_more)return items.filter(c=>!c.is_deleted);
      if(!data.page_token||seen.has(data.page_token))throw fail('日历列表分页未完成');
      pageToken=data.page_token;seen.add(pageToken);
    }throw fail('日历列表超过本次读取上限');
  }
  async events(calendarId,start,end,options){
    const data=await this.run(['calendar','events','instance_view','--params',JSON.stringify({calendar_id:calendarId,start_time:String(Math.floor(Date.parse(start)/1000)),end_time:String(Math.ceil(Date.parse(end)/1000)),user_id_type:'open_id'})],options);
    // The live API omits the optional items field for an empty successful window.
    if(data&&typeof data==='object'&&!Array.isArray(data)&&Object.keys(data).length===0)return [];
    if(!Array.isArray(data?.items)||data.items.some(e=>!e.event_id))throw fail('日历事件未完整返回');
    return data.items;
  }
  async document(reference,options){
    const token=meetingDocumentToken(reference);
    const data=await this.run(['docs','+fetch','--doc',token,'--doc-format','markdown','--scope','full'],options),doc=data?.document;
    if(doc?.document_id!==token||typeof doc.content!=='string')throw fail('纪要正文或稳定身份未通过核对');
    if(Buffer.byteLength(doc.content)>2*1024*1024)throw fail('纪要超过 2 MB，请打开飞书原文查看',422);
    return {token,url:'https://www.feishu.cn/docx/'+token,title:doc.title||'会议纪要',content:doc.content,revision:doc.revision_id??null,sha256:createHash('sha256').update(doc.content).digest('hex'),readAt:new Date().toISOString()};
  }
  async minutes(calendarId,eventId,options){
    const errors=[],refs=[],data=await this.run(['calendar','+meeting','--calendar-id',calendarId,'--event-ids',eventId],options);
    if(!Array.isArray(data?.meetings))throw fail('会议关联未完整返回');
    const meeting=data.meetings.find(m=>m.event_id===eventId);
    if(!meeting)throw fail('返回的会议关联缺少当前日程，保留原纪要');
    if(meeting.error)throw fail('日程会议关联读取失败：'+String(meeting.error).slice(0,200));
    if(meeting.meeting_note){if(typeof meeting.meeting_note!=='string')errors.push('日程纪要引用格式待核对');else refs.push({token:meeting.meeting_note,origin:'calendar_note'});}
    let noteId='',minuteToken='',generating=false;
    if(meeting.meeting_id){
      try{
        const details=await this.run(['vc','+detail','--meeting-ids',meeting.meeting_id],options);
        const detail=details?.meetings?.find(m=>m.meeting_id===meeting.meeting_id);
        if(!detail)throw fail('会议详情缺少匹配身份');
        if(detail.error)throw fail('会议详情读取失败：'+String(detail.error).slice(0,200));
        if(detail.hint?.includes('failed to query'))errors.push('会议附属资料部分读取失败：'+detail.hint.slice(0,200));
        noteId=detail.note_id||'';minuteToken=detail.minute_token||'';
        if(noteId){
          const noteData=await this.run(['note','+detail','--note-id',noteId],options),note=noteData?.note;
          // The official CLI wraps note fields under data.note.
          if(!note||typeof note!=='object'||!('note_doc_token' in note||'note_display_type' in note||'status' in note))throw fail('纪要关联结构待核对');
          if(note.note_id&&note.note_id!==noteId)throw fail('返回的纪要身份不一致');
          if(note.note_doc_token)refs.push({token:note.note_doc_token,origin:'ai_note'});
          generating=note.status==='generating';
        }
      }catch(error){if(options?.signal?.aborted)throw error;errors.push(error.message);}
    }
    const documents=[];
    for(const ref of [...new Map(refs.map(r=>[r.token,r])).values()]){
      try{documents.push({...await this.document(ref.token,options),origin:ref.origin});}catch(error){if(options?.signal?.aborted)throw error;errors.push(error.message);}
    }
    if(minuteToken&&!documents.length)errors.push('已找到妙记引用，正文尚未接入；可打开飞书核对或补充对应纪要文档链接');
    return {meetingId:meeting.meeting_id||'',noteId,minuteToken,documents,errors,status:errors.length?(documents.length?'partial':'unavailable'):documents.length?'ready':generating?'generating':'not_found'};
  }
}
