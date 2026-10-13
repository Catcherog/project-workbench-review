import { readIntakeFile } from './intake-files.mjs';
import { assistantError, assistantHash } from './assistant-sessions.mjs';

const safeUrl = value => { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : ''; } catch { return ''; } };
const present = text => typeof text === 'string' && text.trim();
const tokens = text => [...new Set((text.toLowerCase().match(/[a-z0-9_-]{2,}|[\p{Script=Han}]{2,}/gu) || []).flatMap(t => /^[\p{Script=Han}]+$/u.test(t) ? Array.from({ length: t.length - 1 }, (_, i) => t.slice(i, i + 2)) : [t]))];
const score = (query, text) => tokens(query).reduce((n, token) => n + (text.toLowerCase().includes(token) ? 1 : 0), 0);

export function sourceFingerprint(state, source, domain) {
  return assistantHash([domain.materialSourceIdentityKey(state, source), source.intakeDocument || null,
    (source.meetingContext?.minutes?.documents || []).map(d => [d.id, d.documentKey, d.revision, d.content, d.stale]),
    ...(source.meetingWorkflow?[(source.meetingWorkflow.minutes?.documents || []).map(d => [d.token,d.revision,d.content,d.stale])]:[]),
    source.resultReview?.documents || [], source.archived || false]);
}

/** Reuse collection's availability and time/scope gates. Never initiate collection. */
export function retrievalAvailable(state, source, domain, seen = []) {
  if (!source || source.intakeBatch || seen.includes(source.id) || !domain.caseEvidenceAvailable(state, source)) return false;
  if (source.intakeDocument?.originalSourceId) return retrievalAvailable(state, state.sources.find(s => s.id === source.intakeDocument.originalSourceId), domain, [...seen, source.id]);
  if (source.feedback || source.caseChat || source.caseFile || source.meetingContext) return !!domain.collectedMaterial(state, source);
  return true;
}

export function evidenceCurrent(state, evidence, domain, library) {
  if(evidence.workspaceId && evidence.workspaceId!==state.workspaceId)return false;
  if(evidence.library)return !!library?.current(evidence);
  const source = state.sources.find(s => s.id === evidence.sourceId);
  return retrievalAvailable(state, source, domain) && sourceFingerprint(state, source, domain) === evidence.fingerprint;
}

function linked(source, contextRef, projectId) {
  if (contextRef.kind === 'cases') return source.caseId === contextRef.id || (source.caseIds || []).includes(contextRef.id) || (source.objectIds || []).includes(contextRef.id);
  if (contextRef.kind !== 'workspace' && (source.objectIds || []).includes(contextRef.id)) return true;
  return !!projectId && (source.projectIds || []).includes(projectId);
}

/** Offsets refer to the saved/extracted text, never invented PDF page numbers. */
export function textLocations(text, supplied = []) {
  const valid = supplied.filter(l => Number.isInteger(l.start) && Number.isInteger(l.end) && l.start >= 0 && l.end > l.start && l.end <= text.length && ['page', 'paragraph', 'table', 'cell'].includes(l.kind));
  if (valid.length) return valid.flatMap(loc => chunks(text, loc.start, loc.end, loc));
  return chunks(text, 0, text.length);
}

function chunks(text, start, end, base) {
  const parts = [];
  for (let pos = start; pos < end;) {
    const stop = Math.min(end, pos + 1400);
    const line = text.slice(0, pos).split('\n').length, endLine = line + text.slice(pos, stop).split('\n').length - 1;
    if (text.slice(pos, stop).trim()) parts.push({ ...(base || { kind: 'text', label: '已保存正文第' + line + (line === endLine ? '' : '–' + endLine) + '行', line, endLine }), start: pos, end: stop });
    pos = stop;
  }
  return parts;
}

export class SourceRetrieval {
  constructor({ store, domain, readFile = readIntakeFile, maxSources = 16, maxCharacters = 42000, library = null }) {
    Object.assign(this, { store, domain, readFile, maxSources, maxCharacters, library });
  }
  async documents(state, source, signal) {
    const docs = [], gaps = [], idoc = source.intakeDocument;
    const add = (key, title, text, options = {}) => { if (present(text) || options.images?.length) docs.push({ key, title, text: text || '', complete: true, limitations: [], locations: [], images: [], ...options }); };
    if (source.meetingWorkflow) {
      const minutes=source.meetingWorkflow.minutes;
      if(minutes?.status==='ready')for(const doc of minutes.documents||[])if(!doc.stale)add(doc.token,doc.title,doc.content,{complete:true});
      if(!docs.length)gaps.push('会议准备与AI讨论稿不是原始纪要，尚无可引用的会后正文');
    } else if (source.resultReview) {
      for (const [index, doc] of (source.resultReview.documents || []).entries()) {
        if (!doc.stale) add(doc.documentKey || String(index), doc.name || source.title, doc.content, { complete: doc.complete !== false && !doc.truncated, limitations: doc.limitations || [], locations: doc.locations || [] });
      }
      if (!docs.length) gaps.push('预审只有 AI 摘要，尚无可用原文');
    } else if (source.meetingContext) {
      for (const [index, doc] of (source.meetingContext.minutes?.documents || []).entries()) {
        if (!doc.stale) add(doc.documentKey || doc.id || String(index), doc.title || source.title, doc.content, { complete: source.meetingContext.minutes.status === 'ready' && doc.complete !== false, limitations: source.meetingContext.minutes.status === 'ready' ? [] : ['部分纪要不可用'] });
      }
    } else if (source.taskContext) {
      const raw = source.taskContext.raw || {};
      add('task-description', source.title, typeof raw.description === 'string' ? raw.description : '', { complete: false, limitations: ['仅已保存任务描述，不以聚合摘要代替附件原文'] });
    } else if (idoc) {
      const images = [];
      for (const image of idoc.images || []) {
        signal?.throwIfAborted();
        try { const a = this.store.attachment(state.workspaceId, image.id); images.push({ label: image.label, attachmentId: a.id, sha256: a.sha256, bytes: a.bytes }); }
        catch { gaps.push('已保存图像暂不可读：' + image.label); }
      }
      add('body', source.title, source.excerpt, { complete: idoc.complete !== false, limitations: idoc.limitations || [], locations: idoc.locations || [], images });
    } else if (!source.aiGenerated && !source.assistantAnswer && !['AI摘要', 'AI分析', '资料处理批次'].includes(source.type)) {
      add('body', source.title, source.excerpt, { complete: !source.truncated && source.readStatus !== 'partial', limitations: source.truncated ? ['来源正文已截断'] : [] });
    } else gaps.push('仅有 AI 判断，不能作为原文引用');

    if (!idoc&&!source.meetingWorkflow) for (const attachment of (source.attachments || []).slice(0, 5)) {
      signal?.throwIfAborted();
      // Reuse already-read originals before invoking the existing parser.
      const saved = attachment.sha256 && state.sources.find(s => s.intakeDocument && s.id !== source.id && s.intakeDocument.inputHash === attachment.sha256 && retrievalAvailable(state, s, this.domain));
      try {
        if (saved) {
          const existing = await this.documents(state, saved, signal);
          docs.push(...existing.docs.map(d => ({ ...d, key: 'attachment:' + attachment.id, attachmentId: attachment.id }))); gaps.push(...existing.gaps);
        } else {
          const original = this.store.attachment(state.workspaceId, attachment.id);
          const parsed = await this.readFile(original, { signal });
          add('attachment:' + original.id, original.name, parsed.text, { complete: parsed.complete, limitations: parsed.limitations || [], locations: parsed.locations || [], attachmentId: original.id, images: (parsed.images || []).map((im, i) => ({ ...im, label: im.label || '图' + (i + 1), attachmentId: original.id })) });
        }
      } catch (error) { if (signal?.aborted) throw error; gaps.push('附件“' + attachment.name + '”未读，原件仍保留'); }
    }
    if ((source.attachments?.length || 0) > 5 && !idoc) gaps.push('本轮仅解析前5份普通附件');
    if (!docs.length && !gaps.length) gaps.push('缺少已保存原文或可读附件');
    return { docs, gaps };
  }
  async retrieve({ state, contextRef, projectId = '', query, sourceIds = [], history = [], signal }) {
    const gaps = [], coverage = [], evidence = [], passages = [], images = [];
    const selected = new Set(sourceIds);
    const focus = state[contextRef.kind]?.find?.(row => row.id === contextRef.id);
    const caseRef = focus?.caseId ? { kind: 'cases', id: focus.caseId } : null;
    const queryText = [query, ...history.slice(-2).map(h => h.question)].join('\n');
    const librarySnapshot=this.library?.snapshot();
    const knowledge=(librarySnapshot?.documents||[]).map(d=>({id:d.id,title:d.title,excerpt:d.text,version:d.version,url:d.url,library:d.library,libraryFingerprint:d.fingerprint,libraryLimitations:d.limitations}));
    gaps.push(...(librarySnapshot?.gaps||[]));
    const candidates = [...state.sources.filter(s=>!s.library),...knowledge].filter(s => !s.intakeBatch && !s.workItem).map(source => {
      const related = !!focus?.workItem?.evidence?.some(proof=>proof.sourceId===source.id) || linked(source, contextRef, projectId) || caseRef && linked(source, caseRef, '');
      const rule = !!source.library || source.intakeDocument?.nature === 'rule' || source.intakeDocument?.knownCarrier === 'template' || ['制度', '规则', '制度文件', '模板'].includes(source.type);
      const relevance = score(queryText, source.title + '\n' + (source.excerpt || ''));
      const admitted = selected.has(source.id) || related || rule && relevance > 0 || relevance >= 3;
      return { source, related, relevance, admitted, rank: (selected.has(source.id) ? 10000 : 0) + (related ? 100 : 0) + (rule ? 30 : 0) + relevance };
    }).filter(c => c.admitted).sort((a, b) => b.rank - a.rank || a.source.id.localeCompare(b.source.id));
    const available = [];
    for (const c of candidates) {
      if (c.source.library || retrievalAvailable(state, c.source, this.domain)) available.push(c);
      else if (selected.has(c.source.id) || c.related) gaps.push('“' + c.source.title + '”已失效、归属或采集时间不符合范围，本轮不引用');
    }
    // Reserve space for relevant knowledge and project evidence in mixed questions.
    const knowledgeTop=available.filter(c=>c.source.library).slice(0,Math.max(1,Math.floor(this.maxSources/3)));
    const businessTop=available.filter(c=>!c.source.library).slice(0,Math.max(1,Math.floor(this.maxSources/2)));
    const ordered=[...knowledgeTop,...businessTop,...available.filter(c=>!c.source.library)].filter((c,i,a)=>a.findIndex(x=>x.source.id===c.source.id)===i);
    const chosen=ordered.slice(0,this.maxSources);
    if (available.length > chosen.length) gaps.push('本轮仅选择' + chosen.length + '份相关资料，其他资料尚未读取');
    let used = 0,libraryCharacters=0;
    const libraryBudget=Math.floor(this.maxCharacters*(businessTop.length?0.45:1));
    for (const { source } of chosen) {
      signal?.throwIfAborted();
      const fingerprint = source.libraryFingerprint || sourceFingerprint(state, source, this.domain);
      const { docs, gaps: missing } = source.library ? {docs:[{key:source.library.id,title:source.title,text:source.excerpt,complete:true,limitations:source.libraryLimitations,locations:[],images:[]}],gaps:[]} : await this.documents(state, source, signal);
      const limitations = [...missing]; let complete = !!docs.length && !missing.length;
      const identity = { workspaceId: state.workspaceId, sourceId: source.id, version: source.version || 1, fingerprint,
        title: source.title, ...(source.library?{library:source.library}:{}), url: safeUrl(source.url), projectIds: source.projectIds || [], caseIds: source.caseIds || [],
        occurredAt: source.occurredAt || '', collectedAt: source.collectedAt || '',
        timeUncertain: !!source.feedback?.timeUncertain || !!source.intakeDocument?.timeUncertain };
      const passageStart=passages.length;
      for (const doc of docs) {
        complete &&= doc.complete; limitations.push(...doc.limitations);
        const ranked = textLocations(doc.text, doc.locations).sort((a, b) => score(queryText, doc.text.slice(b.start, b.end)) - score(queryText, doc.text.slice(a.start, a.end)) || a.start - b.start);
        let read = 0;
        for (const locator of ranked) {
          const text = doc.text.slice(locator.start, locator.end);
          if (used + text.length > this.maxCharacters || source.library && (libraryCharacters+text.length>libraryBudget || read*1400+text.length > Math.min(8400,libraryBudget))) { complete = false; continue; }
          const loc = { ...locator, documentKey: doc.key, ...(doc.attachmentId ? { attachmentId: doc.attachmentId } : {}) };
          passages.push({ ...identity, citationId: 'ref-' + assistantHash([fingerprint, loc]).slice(0, 20), documentTitle: doc.title, locator: loc, text, kind: 'text' });
          used += text.length; if(source.library)libraryCharacters+=text.length; read++;
        }
        if (read < ranked.length) limitations.push('本轮只发送与问题相关的部分正文');
        for (const im of doc.images) {
          if (images.length >= 8) { complete = false; limitations.push('本轮图像最多8张，另有图像未分析'); continue; }
          const locator = { kind: 'image', label: im.label, documentKey: doc.key, ...(im.attachmentId ? { attachmentId: im.attachmentId } : {}) };
          const citationId = 'ref-' + assistantHash([fingerprint, locator]).slice(0, 20);
          images.push({ ...im, citationId });
          passages.push({ ...identity, citationId, documentTitle: doc.title, locator, text: '', kind: 'image', imageNumber: images.length });
        }
      }
      const wasRead=passages.length>passageStart;
      if(wasRead)evidence.push(identity);
      else{complete=false;limitations.push('本轮没有读取可引用正文或图像');}
      coverage.push({ sourceId: source.id, title: source.title, complete, read:wasRead, limitations: [...new Set(limitations)] });
      for (const item of missing) gaps.push(source.title + '：' + item);
    }
    for (const p of passages) p.coverage = coverage.find(c => c.sourceId === p.sourceId)?.complete ? 'complete' : 'partial';
    if (!passages.length) gaps.push('当前范围没有可引用的已读取原文；回答需要明确依据不足');
    return { evidence, passages, images, coverage, gaps: [...new Set(gaps)], retrieval: { availableCount: available.length, readCount: coverage.filter(c=>c.read).length, characters: used, strategy: '当前对象、已获准相关资料及制度；按原文词项检索', libraryCount:coverage.filter(c=>c.read&&c.sourceId.startsWith('library:')).length, complete: !gaps.length && available.length <= this.maxSources && coverage.every(c => c.complete) } };
  }
}

export function validateAssistantEvidence(result, retrieved) {
  const bounded = (v, limit) => typeof v === 'string' && v.length <= limit;
  if (!Array.isArray(result.citations) || result.citations.length > 40 || !Array.isArray(result.gaps) || result.gaps.length > 12 || result.gaps.some(g => !bounded(g, 800)) || !Array.isArray(result.nextSteps) || result.nextSteps.length > 8 || result.nextSteps.some(g => !bounded(g, 800)) || !Array.isArray(result.conflicts) || result.conflicts.length > 8) throw assistantError('助手的引用或缺口格式无效');
  const citations = result.citations.map(c => {
    const proof = retrieved.passages.find(p => p.citationId === c.citationId);
    if (!proof || !bounded(c.quote, 1400) || !bounded(c.interpretation, 1000) || (proof.kind === 'image' ? c.quote !== '' : c.quote.trim().length < 2 || !proof.text.includes(c.quote))) throw assistantError('助手引用不在本轮原文或图像范围内，回答已拦截');
    const { text, imageNumber, kind, ...identity } = proof;
    return { ...identity, quote: c.quote, interpretation: c.interpretation, availability: 'current' };
  });
  for (const conflict of result.conflicts) if (!bounded(conflict.reason, 1000) || !Array.isArray(conflict.citationIds) || new Set(conflict.citationIds).size < 2 || conflict.citationIds.some(id => !citations.some(c => c.citationId === id))) throw assistantError('资料冲突必须同时提供两侧可核对依据');
  if (retrieved.passages.length && !citations.length && !result.gaps.length) throw assistantError('回答没有提供可核对引用或说明依据缺口');
  if (result.operations?.length && (!citations.length || result.conflicts.length || citations.some(c => c.coverage !== 'complete'))) throw assistantError('资料不完整或冲突时仅保留核对建议，不能准备正式修改');
  return citations;
}

/** Read-only projection for B/C/A. Ordinary feedback remains in MaterialIntake. */
export function assistantEvidencePacket(job, state, domain, library) {
  const citations = (job.citations || []).map(c => ({ ...c, availability: !job.restored && evidenceCurrent(state, c, domain, library) ? 'current' : 'stale' }));
  const valid = new Set(citations.filter(c => c.availability === 'current').map(c => c.sourceId));
  const batches = state.sources.filter(s => !s.archived && s.intakeBatch && !s.intakeBatch.revertedAt);
  const project = field => batches.flatMap(s => (s.intakeBatch[field] || []).filter(u => valid.has(u.sourceId)).map(u => ({ ...u, batchId: s.id })));
  const feedback = project('autoUpdates'), signals = project('signals'), pending = project('pending');
  return { schemaVersion: 1, workspaceId: job.workspaceId, sessionId: job.sessionId, jobId: job.id, contextRef: job.contextRef,
    projectId: job.projectId, baseRevision: job.baseRevision, citations, gaps: [...(job.gaps || []), ...(citations.some(c => c.availability === 'stale') ? ['历史引用已变化或撤回，请重新提问'] : [])], conflicts: job.conflicts || [], coverage: job.coverage || [], feedback, signals, pending };
}
