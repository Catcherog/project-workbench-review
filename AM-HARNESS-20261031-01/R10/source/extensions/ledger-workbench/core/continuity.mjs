import {assertSnapshot, clone, snapshotBasis} from './model.mjs';

const closed = new Set(['closed', 'cancelled']);
const rank = value => ({P0:0, P1:1, P2:2, P3:3, P4:4}[value] ?? 4);

/** Read-only view of the original registered items. No new task IDs or timer. */
export function buildContinuity(snapshot) {
  assertSnapshot(snapshot);
  const projectById = new Map(snapshot.projects.map(p => [p.id, p]));
  const items = snapshot.items.filter(i => projectById.has(i.projectId) && !closed.has(i.businessState));
  const byId = new Map(items.map(i => [i.id, i]));
  const brief = item => ({id:item.id, title:item.title, businessState:item.businessState,
    priority:item.priority, nextCheckAt:item.nextCheckAt ?? null,
    dueAt:item.dueAt ?? null, deadlineKind:item.deadlineKind});
  const outstanding = snapshot.reminders.filter(r => byId.has(r.itemId));
  const attention = outstanding.filter(r => r.displayState !== 'snoozed')
    .map(r => ({id:r.id, projectId:byId.get(r.itemId).projectId, itemId:r.itemId,
      title:r.title, reason:r.body, priority:r.priority, kind:r.kind ?? 'registered_reminder',
      businessState:byId.get(r.itemId).businessState, nextCheckAt:byId.get(r.itemId).nextCheckAt ?? null}));
  const hasReminder = new Set(attention.map(r => r.itemId));
  for (const item of items) {
    if (item.requiresViewerAction && item.businessState !== 'paused' && !hasReminder.has(item.id)) {
      attention.push({id:'viewer-action:'+item.id, projectId:item.projectId, itemId:item.id,
        title:item.title, reason:item.actionText || '已有明确需要你处理的动作',
        priority:item.priority, kind:'registered_action', businessState:item.businessState,
        nextCheckAt:item.nextCheckAt ?? null});
    }
  }
  attention.sort((a,b) => rank(a.priority)-rank(b.priority) || a.id.localeCompare(b.id));
  const outside = snapshot.projects.filter(p => p.kind === 'outside').map(p => ({
    projectId:p.id, title:p.title, coverage:clone(snapshot.projectCoverage?.[p.id] ?? snapshot.coverage),
    items:items.filter(i => i.projectId === p.id)
      .sort((a,b) => rank(a.priority)-rank(b.priority) || a.id.localeCompare(b.id)).map(brief),
  }));
  return {schemaVersion:1, basis:snapshotBasis(snapshot), generatedAt:snapshot.generatedAt,
    scope:'registered_authorized_items', openCount:items.length,
    waitingCount:items.filter(i => i.businessState === 'waiting').length,
    pausedCount:items.filter(i => i.businessState === 'paused').length,
    needsReviewCount:new Set(outstanding.filter(r => r.kind === 'source_changed').map(r => r.itemId)).size,
    uncertainDeliveryCount:new Set(outstanding.filter(r => r.kind === 'delivery_unknown').map(r => r.itemId)).size,
    outside, attention};
}
