import { parseCoreView, viewUrl, type CoreRequest, type CoreCommand, type CoreView } from './core-collaboration-model';
export type CommandResult = {
  acknowledgement: 'received' | 'rejected' | 'unknown';
  view?: CoreView; operationError?: string; readbackError?: string;
};
export const explainError = (error: unknown) => error instanceof Error ? error.message : String(error);
export async function readCoreView(request: CoreRequest, workspaceId: string, sourceId?: string): Promise<CoreView> {
  const scoped = parseCoreView(await request(viewUrl(workspaceId, sourceId)));
  if (!sourceId || !scoped.runs.some(b => b.items.some(m => !scoped.items.some(i => i.id === m.workItemId)))) return scoped;
  // The service returns entire batches but only the current item in a scoped view.
  // Read a fresh full projection so related admissions have real versions, then keep this item's batches.
  const full = parseCoreView(await request(viewUrl(workspaceId)));
  const runs = full.runs.filter(b => b.items.some(m => m.workItemId === sourceId));
  const related = new Set([sourceId, ...runs.flatMap(b => b.items.map(m => m.workItemId))]);
  return {...scoped, people: full.people, groups: full.groups, runs, items: full.items.filter(i => related.has(i.id))};
}
/** Exactly one POST, then one projection read. No automatic send, approval replay or retry loop. */
export async function performCoreCommand(request: CoreRequest, workspaceId: string, sourceId: string | undefined, command: CoreCommand): Promise<CommandResult> {
  if (!workspaceId || !command.action || 'workspaceId' in command) throw new Error('操作必须绑定当前工作区，不能由额外参数覆盖。');
  let acknowledgement: CommandResult['acknowledgement'] = 'received', operationError: string | undefined;
  try { await request('/api/v2/core', { ...command, workspaceId }); }
  catch (error) {
    const status = typeof error === 'object' && error ? (error as {status?: unknown}).status : undefined;
    // A 5xx/network error may follow a durable write. Never claim that nothing was saved.
    acknowledgement = typeof status === 'number' && [400,401,403,404,409,422,429].includes(status) ? 'rejected' : 'unknown';
    operationError = explainError(error);
  }
  try { return { acknowledgement, operationError, view: await readCoreView(request, workspaceId, sourceId) }; }
  catch (error) { return { acknowledgement, operationError, readbackError: explainError(error) }; }
}
/** Scope epochs suppress stale GET/POST completions after navigation, refresh or unmount. */
export class ScopeEpoch {
  private value = 0;
  advance(): number { return ++this.value; }
  isCurrent(ticket: number): boolean { return ticket === this.value; }
}
