import {createHash} from 'node:crypto';

export class LedgerError extends Error {
  constructor(code, message = code) { super(message); this.name = 'LedgerError'; this.code = code; }
}
export const clone = value => structuredClone(value);
export const asArray = value => Array.isArray(value) ? value : [];
export const nonempty = value => typeof value === 'string' && value.trim().length > 0;
export const string = value => typeof value === 'string' ? value : '';
export const unique = values => [...new Set(values)];
export function canonical(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value ?? null);
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
}
export const hash = value => createHash('sha256').update(canonical(value)).digest('hex');
export function reviewSourceBasis(review) {
  const byCanonical=new Map();
  for(const e of asArray(review.evidence)){
    const value={sourceId:string(e.sourceId),objectId:string(e.objectId),version:string(e.version)};
    byCanonical.set(canonical(value),value);
  }
  const sorted=[...byCanonical].sort((a,b)=>Buffer.compare(Buffer.from(a[0],'utf8'),Buffer.from(b[0],'utf8'))).map(([,v])=>v);
  return hash(sorted);
}
export function dateString(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return new Date(value).toISOString();
  if (typeof value !== 'string' || !value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}
export function assertSnapshot(s) {
  if (!s || s.schemaVersion !== 1 || !nonempty(s.workspaceId) || !nonempty(s.viewerId))
    throw new LedgerError('snapshot_schema');
  for (const key of ['projects','items','facts','reviews','reminders']) {
    if (!Array.isArray(s[key])) throw new LedgerError('snapshot_schema');
    const ids = s[key].map(v => v?.id);
    if (ids.some(id => !nonempty(id)) || new Set(ids).size !== ids.length) throw new LedgerError('duplicate_or_missing_id');
  }
  return s;
}
export function sourceKey(ref) { return [ref.sourceId, ref.objectId, ref.version].map(string).join('\u0000'); }
export function mergeEvidence(...groups) {
  const byKey = new Map();
  for (const ref of groups.flat()) {
    const key = sourceKey(ref);
    const previous = byKey.get(key);
    // Do not reconstruct expired raw text from an old projection.
    byKey.set(key, previous && ref.rawAvailable !== false ? {...previous,...ref} : {...ref});
  }
  return [...byKey.values()];
}
export function currentFacts(s, projectId) {
  return s.facts.filter(f => (projectId === undefined || f.projectId === projectId)
    && !['superseded','withdrawn','background'].includes(f.status));
}
export function fieldBasis(s, itemId, field) {
  return hash({workspaceId:s.workspaceId,itemId,field,
    facts:currentFacts(s).filter(f => f.itemId === itemId && f.field === field)
      .map(f => ({id:f.id,value:f.value,authority:f.authority,status:f.status,protected:f.protected,
        evidence:f.sourceRefs?.map(sourceKey)})).sort((a,b)=>a.id.localeCompare(b.id)),
    decisions:asArray(s.decisions).filter(d => d.itemId === itemId && d.field === field),
  });
}
export function snapshotBasis(s, projectId) {
  assertSnapshot(s);
  const subset = projectId === undefined ? s : {
    ...s, projects:s.projects.filter(p=>p.id===projectId), items:s.items.filter(i=>i.projectId===projectId),
    facts:s.facts.filter(f=>f.projectId===projectId), reviews:s.reviews.filter(r=>r.projectId===projectId),
    reminders:s.reminders.filter(r=>r.projectId===projectId),
  };
  // Wall-clock generation time and unrelated operation receipts are not business dependencies.
  return hash({workspaceId:s.workspaceId,viewerId:s.viewerId,projects:subset.projects,items:subset.items,
    facts:subset.facts,reviews:subset.reviews,reminders:subset.reminders,
    coverage:projectId===undefined?s.coverage:s.projectCoverage?.[projectId]??s.coverage});
}
export function valueText(value) {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    for (const key of ['text','summary','description','title']) if (nonempty(value[key])) return value[key];
  }
  return '';
}
export function changeReceipt(s, requestId, operation, result, now) {
  if (!nonempty(requestId)) throw new LedgerError('request_id_required');
  const operationHash = hash(operation);
  const old = asArray(s.receipts).find(r => r.requestId === requestId);
  if (old) {
    if (old.operationHash !== operationHash) throw new LedgerError('request_id_reused');
    return {duplicate:true, receipt:old};
  }
  return {duplicate:false,receipt:{requestId,operationHash,result,at:now}};
}
export function finishMutation(s, receipt, now) {
  s.receipts = [...asArray(s.receipts),receipt];
  s.revision = typeof s.revision === 'number' ? s.revision + 1 : hash([s.revision,receipt.operationHash]);
  s.generatedAt = now;
  return s;
}
