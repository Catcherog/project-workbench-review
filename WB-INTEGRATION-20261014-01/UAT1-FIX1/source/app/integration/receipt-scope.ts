import type { V2State } from '../../lib/v2-types';
import type { Item } from '../../lib/domain';

type Receipt = Omit<Item, 'id' | 'title' | 'projectIds' | 'sourceIds'>;

/** The caller binds an originating workspace; cached content is never save evidence. */
export function receiptInScope(s: V2State | undefined, receipt: Receipt | null | undefined): Receipt | null {
  if (!s || !receipt || receipt.workspaceId !== s.workspaceId || !receipt.sourceId || !receipt.operationId) return null;
  const row = s.sources.find(source => source.id === receipt.sourceId && source.workItem && !source.archived);
  const live = s.receipts['work-item:' + receipt.operationId]?.result;
  if (!row || !live?.p1 || live.sourceId !== receipt.sourceId || live.operationId !== receipt.operationId) return null;
  // A duplicate submission points to the original durable operation. Its read-only
  // duplicate label is kept, but the original's current undo/status always wins.
  return {...live, workspaceId: s.workspaceId, ...(receipt.duplicate ? {duplicate: true} : {})};
}
