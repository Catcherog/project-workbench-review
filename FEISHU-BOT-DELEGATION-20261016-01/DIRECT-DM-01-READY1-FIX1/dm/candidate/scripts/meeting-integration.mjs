import path from 'node:path';
import {readFile} from 'node:fs/promises';
import {MeetingMaterials, fileHash, meetingError, meetingHash} from './meeting-materials.mjs';
import {SourceRetrieval, retrievalAvailable, sourceFingerprint} from './source-retrieval-service.mjs';

export function meetingFiles(source) {
  const w=source.meetingWorkflow;
  return [w?.materials,w?.preview,...(w?.history||[]).map(h=>h.preview)].flatMap(value=>value?.files||[]);
}
export function validateMeetingBackup(source){
  const w=source.meetingWorkflow;if(w===undefined)return;
  if(!w||w.schemaVersion!==1||!Number.isInteger(w.draftVersion)||w.draftVersion<1||!w.intent||typeof w.intent.title!=='string'||!Array.isArray(w.intent.sourceIds)||!Array.isArray(w.intent.referenceNodeIds)||!Array.isArray(w.intent.attendeeIds)||!Array.isArray(w.history))throw meetingError('会议历史备份结构不完整',400);
  for(const value of [w.materials,w.preview,...w.history.map(h=>h?.preview)])if(value&&(!Array.isArray(value.files)||value.files.some(f=>!f||typeof f.id!=='string'||typeof f.name!=='string'||!Number.isSafeInteger(f.size)||f.size<0||!/^[a-f0-9]{64}$/.test(f.sha256))))throw meetingError('会议文件清单备份无效',400);
  if(w.execution&&(!w.execution.steps||typeof w.execution.steps!=='object'||Array.isArray(w.execution.steps)||Object.values(w.execution.steps).some(step=>!step||typeof step.key!=='string'||!['running','unknown','failed','done'].includes(step.status))))throw meetingError('会议步骤回执备份无效',400);
}

/** C consumes D's saved originals; this adapter never expands collection scope. */
export function managedMeetingMaterials({store,domain,analyse,readFile:reader}) {
  const retrieval=new SourceRetrieval({store,domain,...(reader?{readFile:reader}:{})});
  const register=(workspaceId,name,bytes)=>{
    const sha256=fileHash(bytes),existing=store.db.prepare('SELECT id FROM attachments WHERE workspace_id=? AND sha256=? AND size=? AND name=? LIMIT 1').get(workspaceId,sha256,bytes.length,name);
    if(existing){const a=store.attachment(workspaceId,existing.id);return {id:a.id,name:a.name,mime:a.mime,size:a.size,sha256:a.sha256};}
    return store.attach(workspaceId,{name,mime:'text/plain',base64:bytes.toString('base64')});
  };
  const resolve=async(file,{state})=>{
    if(!file.managedAttachmentId)throw meetingError('会议文件尚未登记到完整备份，请重新准备材料',409);
    const a=store.attachment(state.workspaceId,file.managedAttachmentId);
    if(a.sha256!==file.sha256||a.size!==file.size)throw meetingError('会议原件与保存版本不一致',409);
    return path.join(store.dir,a.path);
  };
  class ManagedMaterials extends MeetingMaterials {
    async resolve(file,context) {return file.managedAttachmentId?resolve(file,context):super.resolve(file,context);}
    async prepare(input) {
      const result=await super.prepare(input);
      for(const file of result.files)if(file.generated&&!file.managedAttachmentId){
        const bytes=await readFile(await super.resolve(file,input));
        file.managedAttachmentId=register(input.state.workspaceId,file.name,bytes).id;
      }
      return result;
    }
  }
  return new ManagedMaterials({dataDir:store.dir,resolveOriginal:resolve,...(analyse?{analyse}:{}),readContext:async({state,sourceIds,signal})=>{
    if(sourceIds.length>16)throw meetingError('本次最多选择16份原始资料，请缩小会议议题');
    const sources=[],files=[],versions=[];let characters=0;
    for(const id of sourceIds){
      signal?.throwIfAborted();
      const source=state.sources.find(s=>s.id===id);
      if(!retrievalAvailable(state,source,domain)||source.meetingWorkflow)throw meetingError('所选资料原文不可用，请核对来源：'+id,409);
      const {docs,gaps}=await retrieval.documents(state,source,signal);
      if(gaps.length||!docs.length||docs.some(d=>!d.complete||!d.text.trim()))throw meetingError('资料尚未完整读取：'+source.title+'；'+(gaps.join('；')||'缺少可引用正文，请补充原文或说明'),409);
      const text=docs.map(d=>d.title+'\n'+d.text).join('\n\n');characters+=text.length;
      if(characters>42000)throw meetingError('所选原文超过本次读取范围，请缩小议题或资料范围');
      const fingerprint=sourceFingerprint(state,source,domain);versions.push([id,fingerprint]);
      sources.push({id,text,availability:'available',fingerprint});
      // A cloud/chat/offline excerpt may have no file. Preserve its exact saved text
      // as an explicitly labelled original snapshot, separately from the AI draft.
      if(docs.some(d=>!d.attachmentId)){
        const bytes=Buffer.from(docs.filter(d=>!d.attachmentId).map(d=>d.text).join('\n\n'));
        const alreadyAttached=(source.attachments||[]).some(a=>store.attachment(state.workspaceId,a.id).sha256===fileHash(bytes));
        if(!alreadyAttached){const a=register(state.workspaceId,source.title.slice(0,120)+' · 原文快照.txt',bytes);
          files.push({id:id+':snapshot',sourceId:id,managedAttachmentId:a.id,name:a.name,sha256:a.sha256,size:a.size,role:'original',access:'当前保存原文快照；不是AI概括，参会人访问待回读'});}
      }
      for(const attachment of source.attachments||[]){
        const a=store.attachment(state.workspaceId,attachment.id);
        files.push({id:id+':'+a.id,sourceId:id,managedAttachmentId:a.id,name:a.name,sha256:a.sha256,size:a.size,role:'original',access:'已核对受管理原件内容；第三人访问尚待验收'});
      }
      if(!files.some(f=>f.sourceId===id))throw meetingError('所选来源缺少受管理原件：'+source.title,409);
    }
    return {version:meetingHash(versions),sources,files};
  }});
}

/** Restored external receipts remain evidence and never authorize a replay. */
export function restoreMeetingWorkflow(source,workspaceId,at) {
  const w=source.meetingWorkflow;if(!w)return;
  w.history ||= [];
  if(w.preview)w.history.push({preview:w.preview,execution:w.execution||null,status:w.status,at});
  w.restoredAt=at;w.restoredWorkspaceId=workspaceId;w.originalStatus=w.status;
  w.status='restored';w.preview=null;w.approvedFingerprint='';source.meetingApprovalHash='';
  for(const step of Object.values(w.execution?.steps||{}))if(step.status==='running')step.status=step.readOnly?'failed':'unknown';
  w.error='恢复副本仅保留原件和历史回执；真实外部对象请到原工作区核对，不会自动重放。';
}
