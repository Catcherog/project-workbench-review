import {resolveMeegleCli} from './cli-runtime.mjs';
import {OriginalAttachmentPort, originalAttachmentField, attachmentRows} from './data-center-attachments.mjs';
import {createHash} from 'node:crypto';
import {MeegleSyncAdapter, spawnMeegle} from './feishu-sync-cli.mjs';
import {FeishuTaskClient} from './feishu-task-client.mjs';

const fail = (message, status = 422) => Object.assign(new Error(message), {status});
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
const xml = value => String(value).replace(/[<>&"']/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&apos;'}[c]));
const documentField = 'field_d06ce2';
function documentMatches(document, draft) {
  if (document?.title && normalize(document.title) !== normalize(draft.title)) return false;
  let content = String(document?.content || '').trim();
  const first = content.split('\n')[0];
  if (normalize(first.replace(/^#+\s*/,'')) === normalize(draft.title)) content = content.slice(first.length).trim();
  return normalize(content) === normalize(draft.content);
}
const cloudUrl = value => {
  try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password && !u.port && (u.hostname === 'feishu.cn' || u.hostname.endsWith('.feishu.cn')) && /^\/(docx|wiki)\/[\w-]+\/?$/.test(u.pathname) ? u.href : ''; } catch { return ''; }
};
function links(value) {
  if (value === null || value === '') return [];
  const list = Array.isArray(value) ? value : typeof value === 'string' && value.startsWith('[') ? JSON.parse(value) : [value];
  return list.map(row => {
    const url = cloudUrl(typeof row === 'string' ? row : row.url || row.link || row.doc_url);
    if (!url) throw fail('交付物当前文档字段有无法识别的内容，已停止追加，避免覆盖');
    return {name: typeof row === 'object' ? row.name || row.title || '' : '', url};
  });
}

/** Only two explicit operations: append a comment, or append a document to an
 * existing deliverable's document carrier. No status/owner/node-completion writes. */
export class DataCenterFeishuPort {
  constructor({meegle = new MeegleSyncAdapter({cli: resolveMeegleCli()}), lark = new FeishuTaskClient(), runner = spawnMeegle, readAttachment} = {}) {
    Object.assign(this, {meegle, lark, runner}); this.originals=new OriginalAttachmentPort({owner:this,readAttachment});
  }
  async inspect({object, destination}) {
    const signal = AbortSignal.timeout(90000);
    const read = await this.meegle.readObject(object, {signal});
    if (!read.complete || read.remoteId !== object.remoteId || !['project', 'deliverable'].includes(object.remoteKind)) throw fail('飞书目标未完整读取，不能准备挂载');
    const actor = await this.meegle.auth({signal});
    let current = null, rawCurrent = null, cloudIdentity = null;
    if (destination === 'attachment') {
      const field=(read.fieldMetadata || []).find(row=>(row.key || row.field_key)===originalAttachmentField);
      if(object.remoteKind!=='deliverable'||(field?.valueType || field?.field_type)!=='multi-file'||!Object.prototype.hasOwnProperty.call(read.fields,originalAttachmentField))throw fail('目标交付物附件字段未完整核实');
      rawCurrent=structuredClone(read.fields[originalAttachmentField]);current=attachmentRows(rawCurrent);
    }
    if (destination === 'document') {
      const field = (read.fieldMetadata || []).find(row => (row.key || row.field_key) === documentField);
      if (object.remoteKind !== 'deliverable' || (field?.valueType || field?.field_type) !== 'link_cloud_doc') throw fail('目标没有已核实的交付物文档字段');
      if (!Object.prototype.hasOwnProperty.call(read.fields, documentField)) throw fail('交付物文档字段未返回，无法区分空值与无权限；请先核对该字段', 409);
      current = links(read.fields[documentField]);
      rawCurrent = structuredClone(read.fields[documentField]);
      cloudIdentity = await this.lark.identity({signal});
    }
    const identity = JSON.stringify([actor.host, actor.userKey, cloudIdentity?.scope || '', cloudIdentity?.userId || '']);
    return {verified: true, identity, fingerprint: hash([object.host, object.spaceKey, object.remoteId, destination, rawCurrent]), current, rawCurrent, field: destination === 'document' ? documentField : destination === 'attachment' ? originalAttachmentField : 'comment', checkedAt: new Date().toISOString()};
  }
  async comment(command, object, extra) {
    const signal = AbortSignal.timeout(40000);
    await this.meegle.auth({signal});
    if (!['add', 'list'].includes(command)) throw fail('不支持的评论命令');
    const args = [...(this.meegle.profile ? ['--profile', this.meegle.profile] : []), 'comment', command, '--params', JSON.stringify({project_key: object.spaceKey, work_item_id: object.remoteId, ...extra}), '--format', 'json'];
    const output = await this.runner(this.meegle.cli, args, {signal, shell: false, maxOutputBytes: 8 * 1024 * 1024});
    let value; try {value = JSON.parse(output.stdout);} catch {throw fail('评论返回内容无法核对');}
    if (output.status || value.error || value.ok === false || value.code && ![0, '0'].includes(value.code)) throw fail(value.error?.message || value.message || '评论操作未完成');
    return value.data || value;
  }
  commentBody(draft) { return `${draft.title}\n\n${draft.content}\n\n<!-- workbench-material:${draft.id} -->`; }
  async publish(draft, checkpoint) {
    if(draft.destination==='attachment')return this.originals.publish(draft,checkpoint);
    if (draft.destination === 'comment') {
      const result = await this.comment('add', draft.object, {content: this.commentBody(draft)});
      const artifact = {kind: 'comment', id: String(result.comment_id || result.id || result.comment?.id || ''), url: draft.object.url || '', body: this.commentBody(draft)};
      await checkpoint(artifact); return artifact;
    }
    const signal = AbortSignal.timeout(90000);
    const body = `<title>${xml(draft.title)}</title>\n` + draft.content.split('\n').map(line => `<p>${xml(line)}</p>`).join('\n');
    let artifact = draft.artifact;
    if (!artifact) {
      const result = await this.lark.run(['docs', '+create', '--doc-format', 'xml', '--content', body, '--as', 'user'], {signal});
      const document = result.document;
      if (!document?.document_id || !cloudUrl(document.url)) throw fail('云文档创建结果未返回可核对的文档身份');
      artifact = {kind: 'document', id: document.document_id, url: document.url, warnings: result.warnings || []};
    }
    await checkpoint(artifact);
    if (artifact.warnings.length) throw fail('云文档返回内容处理警告，请核对文档后再挂载');
    const fetched = await this.lark.run(['docs', '+fetch', '--doc', artifact.id, '--doc-format', 'markdown', '--scope', 'full', '--as', 'user'], {signal});
    if (fetched.document?.document_id !== artifact.id || !documentMatches(fetched.document,draft)) throw fail('新建文档正文尚未通过回读，已保留文档入口');
    const latest = await this.inspect(draft);
    if (latest.identity !== draft.inspected.identity || latest.fingerprint !== draft.inspected.fingerprint) throw fail('文档已创建，但目标内容或账号已改变；请核对后续办');
    const before = latest.rawCurrent == null || latest.rawCurrent === '' ? [] : Array.isArray(latest.rawCurrent) ? latest.rawCurrent : typeof latest.rawCurrent === 'string' && latest.rawCurrent.startsWith('[') ? JSON.parse(latest.rawCurrent) : [latest.rawCurrent];
    const after = [...before, typeof before[0] === 'string' ? artifact.url : {name: draft.title, url: artifact.url}];
    await this.meegle._run('workitem update', {project_key: draft.object.spaceKey, work_item_id: draft.object.remoteId, fields: [{field_key: documentField, field_value: JSON.stringify(after)}]}, {signal, writing: true});
    return artifact;
  }
  async readback(draft, artifact) {
    if(draft.destination==='attachment')return this.originals.readback(draft,artifact);
    const inspection = await this.inspect(draft);
    if (inspection.identity !== draft.inspected.identity) throw fail('账号已变化，无法核对原执行结果');
    if (draft.destination === 'document') {
      if (!artifact?.id || !artifact.url || artifact.warnings?.length) return {verified: false};
      const fetched = await this.lark.run(['docs', '+fetch', '--doc', artifact.id, '--doc-format', 'markdown', '--scope', 'full', '--as', 'user'], {signal: AbortSignal.timeout(60000)});
      const contentMatches = fetched.document?.document_id === artifact.id && documentMatches(fetched.document,draft);
      const attached = inspection.current.some(row => row.url === artifact.url);
      const verified = attached && (draft.inspected.current || []).every(old => inspection.current.some(row => row.url === old.url)) && contentMatches;
      return {verified, confirmedNotAttached: !attached && contentMatches, url: artifact.url, targetUrl: draft.object.url || '', documentId: artifact.id, revision: fetched.document?.revision_id, checkedAt: new Date().toISOString()};
    }
    for (let page = 1; page <= 30; page++) {
      const response = await this.comment('list', draft.object, {page_num: page, page_size: 50});
      const rows = response.comments || response.list || response.items || [];
      if (!Array.isArray(rows)) throw fail('评论回读格式无法识别');
      const found = rows.find(row => (artifact?.id ? String(row.comment_id || row.id) === artifact.id : String(row.content || row.text || '').includes(`workbench-material:${draft.id}`)) && normalize(row.content || row.text).includes(normalize(draft.content)));
      if (found) return {verified: true, url: draft.object.url || '', commentId: String(found.comment_id || found.id), checkedAt: new Date().toISOString()};
      if (!(response.pagination?.has_more || response.has_more)) break;
    }
    return {verified: false};
  }
}
