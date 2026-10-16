import {createHash, randomUUID} from 'node:crypto';

const fail = (message, status = 422) => Object.assign(new Error(message), {status});
const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const now = () => new Date().toISOString();
export const publicationSourceKey = (domain, state, source) => digest([
  domain.materialSourceIdentityKey(state, source), source.intakeBatch?.summary || '',
  (source.intakeBatch?.documents || []).map(id => {
    const doc = state.sources.find(row => row.id === id);
    return doc && !doc.archived ? domain.materialSourceIdentityKey(state, doc) : null;
  }),
]);
const targetKey = (target, object) => digest([target.id, target.projectIds, target.flowNodeIds || [], object.system, object.host, object.spaceKey, object.remoteKind, object.remoteId, object.localObjectId]);

/** A reviewed publication is stored with the source, so normal backups include it.
 * Approval is bound to exact content, source, target, account and remote field value.
 * Unknown writes can only be reconciled; they are never blindly replayed. */
export class DataCenterPublication {
  constructor({store, domain, port, mode = 'disabled', clock = now}) {
    Object.assign(this, {store, domain, port, mode, clock}); this.jobs = new Map();
    for (const workspace of store.list()) for (const source of store.load(workspace.id).sources) {
      if (source.dataPublication?.status === 'publishing') this.save(workspace.id, source.id, row => {
        row.dataPublication.status = 'unknown'; row.dataPublication.error = '上次挂载中断，请先核对实际结果，不会自动重发。';
      });
    }
  }
  capabilities() { return {mode: this.mode, available: !!this.port && this.mode !== 'disabled', destinations: ['comment', 'document', 'attachment'], existingTargetsOnly: true}; }
  record(workspaceId, sourceId) {
    const state = this.store.load(workspaceId), source = state.sources.find(row => row.id === sourceId && !row.archived);
    if (!source || source.reminderRun || source.meetingWorkflow || source.importedFrom?.readonly && !source.intakeBatch && !source.intakeDocument && !source.feedback && !source.caseChat && !source.caseFile && !source.meetingContext && !source.taskContext) throw fail('请选择收到的业务资料或整理批次，历史同步快照不作为新资料挂载');
    if (!this.domain.caseEvidenceAvailable(state, source)) throw fail('原始资料已失效，请重新读取后核对', 409);
    if (source.intakeBatch && this.domain.intakeActive(source.intakeBatch.status)) throw fail('资料仍在整理，请完成后审核', 409);
    if (source.intakeBatch && this.domain.intakeStaleDocuments(state, source).length) throw fail('整理稿引用的资料已经变化，请重新整理', 409);
    return {state, source};
  }
  target(state, id, mode) {
    const target = [...state.deliverables, ...state.projects].find(row => row.id === id && !row.archived);
    const objects = state.externalObjects.filter(row => row.localObjectId === id && row.system === 'meegle' && row.mappingStatus === 'mapped' && row.verificationStatus === 'verified');
    if (!target || objects.length !== 1) throw fail('挂载目标缺少唯一、已核实的飞书关联，请先核对数据来源', 409);
    const object = objects[0];
    if (['document','attachment'].includes(mode) && object.remoteKind !== 'deliverable') throw fail('成果文档应选择已有交付物；项目沟通可选择评论');
    return {target, object};
  }
  save(workspaceId, sourceId, change) {
    return this.store.transaction(() => {
      const state = this.store.load(workspaceId), source = state.sources.find(row => row.id === sourceId && !row.archived);
      if (!source) throw fail('资料已不存在', 409);
      change(source, state); source.version++; source.updatedAt = this.clock();
      const revision = state.revision; state.revision++;
      const errors = this.domain.validateState(state); if (errors.length) throw fail(errors.map(row => row.message).join('；'));
      this.store.save(state, revision); return {state, publication: source.dataPublication};
    });
  }
  async locked(workspaceId, sourceId, fn) {
    const key = workspaceId + ':' + sourceId;
    if (this.jobs.has(key)) throw fail('这份资料正在处理，请等待当前结果', 409);
    const job = Promise.resolve().then(fn); this.jobs.set(key, job);
    try { return await job; } finally { this.jobs.delete(key); }
  }
  requirePort(state) {
    if (!this.port || this.mode === 'disabled') throw fail('本环境尚未接入挂载执行器，整理稿已保留', 503);
    if (this.mode === 'live' && state.workspaceType !== 'official') throw fail('仅正式工作区可以执行真实挂载；恢复或演示区不会外发', 403);
  }
  async cancel(input) {
    const {workspaceId,sourceId,fingerprint}=input;
    return this.locked(workspaceId,sourceId,async()=>{
      const current=this.store.load(workspaceId),existing=current.sources.find(row=>row.id===sourceId&&!row.archived)?.dataPublication;
      if(existing?.status==='cancelled')return {state:current,publication:existing};
      return this.save(workspaceId,sourceId,(row,state)=>{
      const draft=row.dataPublication;
      if(state.workspaceType==='restored')throw fail('恢复记录仅供查看，不能恢复原挂载授权',409);
      if(!draft||draft.artifact||!['prepared','stale','failed','cancelled'].includes(draft.status))throw fail('已有执行记录，请先核对真实结果；不能以取消代替回读',409);
      if(draft.status==='cancelled')return;
      if(!fingerprint||fingerprint!==draft.fingerprint)throw fail('挂载准备已变化，请刷新后核对',409);
      const before={status:draft.status,targetId:draft.targetId,destination:draft.destination};
      draft.status='cancelled';draft.cancelledAt=this.clock();draft.approvedAt='';draft.error='';
      state.audit.push({id:'data-publication-cancel-'+draft.id+'-'+state.revision,time:this.clock(),operation:'data.publication.cancel',kind:'sources',objectId:sourceId,actor:'本人',before,after:{status:'cancelled'},revision:state.revision+1});
      });
    });
  }
  async prepare(input) {
    const {workspaceId, sourceId, targetId, destination, title, content} = input;
    if (!['comment', 'document', 'attachment'].includes(destination) || typeof title !== 'string' || !title.trim() || title.length > 150 || typeof content !== 'string' || destination !== 'attachment' && !content.trim() || content.length > 30000) throw fail('请填写标题、整理正文和挂载位置（正文最多30000字）');
    return this.locked(workspaceId, sourceId, async () => {
      const {state, source} = this.record(workspaceId, sourceId); this.requirePort(state);
      if(source.workItem&&this.domain.workItemState(state,source).stale)throw fail('整合事项的原依据已变化，请重新理解后再准备挂载',409);
      if (!Array.isArray(input.sourceIds || [])) throw fail('合并资料列表格式无效');
      const sourceIds = [...new Set([sourceId,...(source.dataPublication?.artifact ? source.dataPublication.sourceIds || [] : input.sourceIds || [])])];
      if (sourceIds.length > 128 || sourceIds.some(id => typeof id !== 'string')) throw fail('一份整理稿最多引用128份资料');
      const sourceKeys = Object.fromEntries(sourceIds.map(id => {
        const item = this.record(workspaceId,id);
        return [id,publicationSourceKey(this.domain,item.state,item.source)];
      }));
      if (state.sources.some(row => row.id !== sourceId && row.dataPublication && !['stale','restored','cancelled'].includes(row.dataPublication.status) && (row.dataPublication.sourceIds || [row.id]).some(id => sourceIds.includes(id)))) throw fail('这些资料已有另一份挂载审核或执行记录，请继续处理原记录',409);
      const files=[];
      if(destination==='attachment'){
        if(!Array.isArray(input.attachmentIds)||!input.attachmentIds.length||input.attachmentIds.length>16||new Set(input.attachmentIds).size!==input.attachmentIds.length)throw fail('请选择1至16份不重复的原件');
        const documents=sourceIds.flatMap(id=>{const row=this.record(workspaceId,id).source;return [row,...(row.intakeBatch?.documents || []).map(key=>state.sources.find(v=>v.id===key&&!v.archived)).filter(Boolean)];});
        const allowed=new Set(documents.flatMap(row=>(row.attachments||[]).filter(a=>!row.intakeDocument?.images?.some(im=>im.id===a.id)).map(a=>a.id)));
        for(const id of input.attachmentIds){if(!allowed.has(id))throw fail('原件不属于本次审核资料');const a=this.store.attachment(workspaceId,id);files.push({id:a.id,name:a.name,mime:a.mime,size:a.size,sha256:a.sha256});}
        if(new Set(files.map(f=>f.name)).size!==files.length)throw fail('本批含同名原件，请分别核对版本后挂载');
      }
      const prior = source.dataPublication;
      if(prior?.artifact&&destination==='attachment'&&digest(files)!==digest(prior.files))throw fail('已有上传记录，续办须保留同一批原件',409);
      if (['publishing', 'unknown', 'verified', 'restored'].includes(prior?.status) || prior?.artifact && prior.status !== 'partial') throw fail('这份资料已有执行记录，请先核对执行结果；不能重复发布或覆盖原记录', 409);
      if (prior?.artifact && [title.trim(), content.trim(), targetId, destination].some((value, index) => value !== [prior.title, prior.content, prior.targetId, prior.destination][index])) throw fail('已创建文档的续办保留原正文与目标，请先核对原执行记录', 409);
      const {target, object} = this.target(state, targetId, destination);
      const sourceKey = publicationSourceKey(this.domain, state, source), targetFingerprint = targetKey(target, object);
      const inspected = await this.port.inspect({object, destination});
      if (!inspected?.verified || !inspected.identity || !inspected.fingerprint) throw fail('未取得挂载目标与账号的核对结果', 409);
      const current = this.record(workspaceId, sourceId), currentTarget = this.target(current.state, targetId, destination);
      if (sourceKey !== publicationSourceKey(this.domain, current.state, current.source) || targetFingerprint !== targetKey(currentTarget.target, currentTarget.object)) throw fail('读取期间资料或目标已变化，请重新准备', 409);
      const project = state.projects.find(row => row.id === target.projectIds?.[0]);
      const nodes = state.flowNodes.filter(row => (target.flowNodeIds || []).includes(row.id));
      for (const id of sourceIds) {const item=this.record(workspaceId,id);if(sourceKeys[id]!==publicationSourceKey(this.domain,item.state,item.source))throw fail('合并资料在读取期间发生变化，请重新核对',409);}
      if (this.store.load(workspaceId).sources.some(row => row.id !== sourceId && row.dataPublication && !['stale','restored','cancelled'].includes(row.dataPublication.status) && (row.dataPublication.sourceIds || [row.id]).some(id => sourceIds.includes(id)))) throw fail('这些资料刚刚进入另一份审核，请继续处理原记录',409);
      const draft = {workspaceId,files,id: prior?.artifact ? prior.id : randomUUID(), ...(prior?.artifact ? {artifact: prior.artifact} : {}), status: 'prepared', sourceId, sourceIds, sourceKeys, sourceKey, targetId, targetFingerprint, object: structuredClone(object), destination, title: title.trim(), content: content.trim(), targetPath: [project?.title, ...nodes.map(row => row.title), target.title, destination === 'document' ? '交付物文档' : destination === 'attachment' ? '交付物附件' : '评论'].filter(Boolean).join(' → '), inspected, preparedAt: this.clock(), mode: this.mode};
      draft.fingerprint = digest(draft);
      return this.save(workspaceId, sourceId, row => { row.dataPublication = draft; });
    });
  }
  checkCurrent(state, source, draft) {
    const {target, object} = this.target(state, draft.targetId, draft.destination);
    if (draft.sourceKey !== publicationSourceKey(this.domain, state, source) || draft.targetFingerprint !== targetKey(target, object)) throw fail('审核后原文或挂载位置已变化，请重新准备', 409);
    for (const id of draft.sourceIds || [source.id]) {
      const item = this.record(state.workspaceId,id);
      if (draft.sourceKeys?.[id] && draft.sourceKeys[id] !== publicationSourceKey(this.domain,item.state,item.source)) throw fail('合并资料在审核后发生变化，请重新准备',409);
    }
  }
  async publish({workspaceId, sourceId, fingerprint, confirmed}) {
    if (confirmed !== true) throw fail('请先审核整理正文和挂载位置', 403);
    return this.locked(workspaceId, sourceId, async () => {
      const {state, source} = this.record(workspaceId, sourceId); this.requirePort(state);
      const draft = source.dataPublication;
      if (!draft || draft.fingerprint !== fingerprint) throw fail('本次审核内容已变化，请刷新', 409);
      if (draft.status === 'verified') return {state, publication: draft};
      if (draft.status !== 'prepared') throw fail('当前记录不可重复执行，请先核对结果', 409);
      this.checkCurrent(state, source, draft);
      const latest = await this.port.inspect({object: draft.object, destination: draft.destination});
      if (latest.identity !== draft.inspected.identity || latest.fingerprint !== draft.inspected.fingerprint) {
        this.save(workspaceId, sourceId, row => {row.dataPublication.status = 'stale'; row.dataPublication.error = '飞书内容或账号已变化，请重新准备审核';});
        throw fail('飞书内容或账号已变化，请重新准备审核', 409);
      }
      const current = this.record(workspaceId, sourceId); this.checkCurrent(current.state, current.source, draft);
      this.save(workspaceId, sourceId, row => {row.dataPublication.status = 'publishing'; row.dataPublication.approvedAt = this.clock(); row.dataPublication.error = '';});
      try {
        const artifact = await this.port.publish(draft, async partial => {
          this.save(workspaceId, sourceId, row => {row.dataPublication.artifact = partial;});
        });
        this.save(workspaceId, sourceId, row => {row.dataPublication.artifact = artifact;});
        const receipt = await this.port.readback(draft, artifact);
        if (!receipt?.verified) throw fail('已提交，尚未确认飞书实际内容与挂载关系');
        return this.finish(workspaceId, sourceId, receipt);
      } catch (error) {
        return this.save(workspaceId, sourceId, row => {row.dataPublication.status = 'unknown'; row.dataPublication.error = error.message + '；请核对结果，不会自动重发。';});
      }
    });
  }
  finish(workspaceId, sourceId, receipt) {
    return this.save(workspaceId, sourceId, (row, state) => {
      row.dataPublication.status = 'verified'; row.dataPublication.receipt = receipt;
      row.dataPublication.verifiedAt = this.clock(); row.dataPublication.error = '';
      if (row.intakeBatch) {row.intakeBatch.reviewedAt = this.clock(); row.intakeBatch.reviewedBy = '本人';}
      state.audit.push({id: 'data-publication-' + row.dataPublication.id, time: this.clock(), operation: 'data.publication.verified', kind: 'sources', objectId: sourceId, actor: this.mode === 'simulation' ? '本人（模拟挂载）' : '本人', before: {}, after: {targetId: row.dataPublication.targetId, destination: row.dataPublication.destination, receipt}, revision: state.revision + 1});
    });
  }
  async reconcile({workspaceId, sourceId}) {
    return this.locked(workspaceId, sourceId, async () => {
      const {state, source} = this.record(workspaceId, sourceId); this.requirePort(state);
      const draft = source.dataPublication;
      if (!draft || !['unknown', 'publishing'].includes(draft.status)) throw fail('当前没有结果未知的执行');
      const receipt = await this.port.readback(draft, draft.artifact);
      if (receipt?.confirmedNotAttached && (draft.destination === 'document' && draft.artifact?.id || draft.destination === 'attachment' && draft.artifact?.files?.length)) {
        return this.save(workspaceId, sourceId, row => {row.dataPublication.status = 'partial'; row.dataPublication.error = '已有文件已保留，部分挂载待续办。重新审核后复用已上传文件，不重复上传。';});
      }
      if (!receipt?.verified) throw fail('尚未找到与本次内容和目标一致的挂载结果，保持待核对', 409);
      return this.finish(workspaceId, sourceId, receipt);
    });
  }
}
