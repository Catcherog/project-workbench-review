import {createHash} from 'node:crypto';
import {mkdtemp, writeFile, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';

export const originalAttachmentField = 'field_a38c57';
const fail = message => Object.assign(Error(message), {status:409});
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
export function attachmentRows(value) {
  const rows = value == null || value === '' ? [] : typeof value === 'string' ? JSON.parse(value) : value;
  if (!Array.isArray(rows) || rows.some(row => !row || typeof row !== 'object' || !row.name || !['string','number'].includes(typeof row.size))) throw fail('交付物附件字段格式无法核对，停止追加');
  return structuredClone(rows);
}

/** Upload one original at a time, retaining every existing server field.
 * Checkpoints survive uncertain writes. Reconciliation never uploads or binds. */
export class OriginalAttachmentPort {
  constructor({owner, readAttachment}) { Object.assign(this, {owner, readAttachment}); }
  async command(args) {
    const m = this.owner.meegle;
    const output = await this.owner.runner(m.cli, [...(m.profile ? ['--profile',m.profile] : []),...args,'--format','json'], {signal:AbortSignal.timeout(90000),shell:false,maxOutputBytes:2*1024*1024});
    let value; try { value = JSON.parse(output.stdout); } catch { throw fail('原件传输结果无法核对，保留原请求并核对实际结果'); }
    if (output.status || value.error || value.ok === false || value.code && ![0,'0'].includes(value.code)) throw fail(value.error?.message || value.message || '原件传输失败');
    return value.data || value;
  }
  async verify(draft, row, file) {
    const ref = row.url || row.file_url;
    if (!ref) throw fail('附件字段尚未返回下载引用，不能声称原件已验收');
    const folder = await mkdtemp(path.join(tmpdir(),'pm-attachment-readback-'));
    try {
      const output = path.join(folder,'original');
      await this.command(['attachment','+download',ref,'--project-key',draft.object.spaceKey,'--work-item-id',draft.object.remoteId,'--output',output]);
      const bytes = await readFile(output);
      if (bytes.length !== file.size || sha(bytes) !== file.sha256) throw fail('远端原件与本次审核文件的大小或哈希不一致');
      return {name:file.name,size:file.size,sha256:file.sha256,method:'download-sha256'};
    } finally { await rm(folder,{recursive:true,force:true}); }
  }
  async publish(draft, checkpoint) {
    if (!this.readAttachment) throw fail('原件读取器未接入');
    const artifact = structuredClone(draft.artifact || {kind:'attachments',files:[]});
    let expected = draft.inspected.fingerprint;
    for (const file of draft.files) {
      let saved = artifact.files.find(row => row.id === file.id);
      let current = await this.owner.inspect(draft);
      if (current.identity !== draft.inspected.identity || current.fingerprint !== expected) throw fail('远端附件或账号已变化，先核对已上传原件再续办');
      const existing = current.current.filter(row => row.name === file.name);
      if (existing.length) {
        if (!saved || existing.length !== 1) throw fail('目标已存在同名附件，请先核对版本');
        saved.receipt = await this.verify(draft,existing[0],file); saved.bound = true; await checkpoint(artifact); continue;
      }
      if (!saved) {
        const original = await this.readAttachment(draft.workspaceId,file.id);
        if (original.name !== file.name || original.bytes.length !== file.size || sha(original.bytes) !== file.sha256) throw fail('本地原件在审核后已变化');
        const folder = await mkdtemp(path.join(tmpdir(),'pm-attachment-upload-'));
        try {
          const input = path.join(folder,'original'); await writeFile(input,original.bytes,{mode:0o600});
          const uploaded = await this.command(['attachment','+upload',input,'--resource-type','15','--project-key',draft.object.spaceKey,'--work-item-id',draft.object.remoteId,'--field-key',originalAttachmentField,'--filename',file.name,'--content-type',file.mime]);
          if (!uploaded.file_token) throw fail('上传结果缺少文件身份，不能自动重试');
          saved = {...file,value:{name:file.name,type:uploaded.mime_type || file.mime,size:String(file.size),fileToken:uploaded.file_token},bound:false};
          artifact.files.push(saved); await checkpoint(artifact);
        } finally { await rm(folder,{recursive:true,force:true}); }
      }
      current = await this.owner.inspect(draft);
      if (current.identity !== draft.inspected.identity || current.fingerprint !== expected) throw fail('原件已上传，但目标附件在上传期间变化，请核对后续办');
      const after = [...current.current,saved.value];
      await this.owner.meegle._run('workitem update',{project_key:draft.object.spaceKey,work_item_id:draft.object.remoteId,fields:[{field_key:originalAttachmentField,field_value:JSON.stringify(after)}]},{signal:AbortSignal.timeout(60000),writing:true});
      const readback = await this.owner.inspect(draft);
      if (readback.identity !== draft.inspected.identity || readback.current.length !== after.length || !current.current.every(old=>readback.current.some(row=>Object.keys(old).every(k=>JSON.stringify(row[k])===JSON.stringify(old[k]))))) throw fail('原附件保留情况或新增数量未通过回读');
      const rows = readback.current.filter(row=>row.name===file.name);
      if (rows.length !== 1) throw fail('新增附件身份不唯一，请核对');
      saved.receipt=await this.verify(draft,rows[0],file);saved.bound=true;expected=readback.fingerprint;await checkpoint(artifact);
    }
    return artifact;
  }
  async readback(draft,artifact) {
    const current = await this.owner.inspect(draft);
    if (current.identity !== draft.inspected.identity) throw fail('附件回读账号已变化');
    const receipts=[];let missing=0;
    for (const file of draft.files) {
      const saved=artifact?.files?.find(row=>row.id===file.id),rows=current.current.filter(row=>row.name===file.name);
      if (!saved && rows.length) return {verified:false};
      if (!rows.length) {missing++;continue;}
      if (rows.length!==1) throw fail('同名附件不唯一，不能自动认领结果');
      receipts.push(await this.verify(draft,rows[0],file));
    }
    const preserved=(draft.inspected.current || []).every(old=>current.current.some(row=>Object.keys(old).every(k=>JSON.stringify(row[k])===JSON.stringify(old[k]))));
    return {verified:preserved&&receipts.length===draft.files.length,confirmedNotAttached:preserved&&missing>0,
      files:receipts,fieldKey:originalAttachmentField,url:draft.object.url || '',checkedAt:new Date().toISOString()};
  }
}
