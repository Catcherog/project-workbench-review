import type { LedgerRequest } from './types';
import { isLedgerAccessError } from './request-error';

interface PendingOperation { state: 'pending'; requestId: string; pollUrl: string }
interface PollOptions { intervalMs?: number; timeoutMs?: number }
function pending(value: unknown): value is PendingOperation {
  return !!value && typeof value === 'object' && !Array.isArray(value)
    && (value as Record<string, unknown>).state === 'pending'
    && typeof (value as Record<string, unknown>).requestId === 'string'
    && typeof (value as Record<string, unknown>).pollUrl === 'string';
}
export class LedgerOperationError extends Error {
  readonly requestId: string;
  readonly pollUrl: string;
  constructor(message: string, operation: PendingOperation) {
    super(message);
    this.name = 'LedgerOperationError';
    this.requestId = operation.requestId;
    this.pollUrl = operation.pollUrl;
  }
}
/**
 * Resolve a 202 response by GET-polling the original operation.
 * The original POST is sent exactly once. No identity or authorization is added here.
 */
export function withLedgerOperations(transport: LedgerRequest, options: PollOptions = {}): LedgerRequest {
  const intervalMs = Math.max(50, options.intervalMs ?? 800);
  const timeoutMs = Math.max(intervalMs, options.timeoutMs ?? 180_000);
  const outstanding = new Map<string, PendingOperation>();
  return async (path, body) => {
    const key = path + ':' + (body?.requestId || 'GET');
    let result: unknown;
    try { result = outstanding.get(key) || await transport(path, body); }
    catch (error) {
      if (isLedgerAccessError(error)) outstanding.clear();
      throw error;
    }
    if (!pending(result)) return result;
    const initial = result;
    outstanding.set(key, initial);
    if (!/^\/api\/v2\/ledger\/operations\/[A-Za-z0-9_-]+$/.test(initial.pollUrl)) {
      throw new LedgerOperationError('后台返回了无法核对的查询地址，已停止继续请求。', initial);
    }
    const startedAt = Date.now();
    while (pending(result)) {
      if (result.requestId !== initial.requestId || result.pollUrl !== initial.pollUrl) {
        throw new LedgerOperationError('后台任务身份发生变化，已保留原请求供核对。', initial);
      }
      if (Date.now() - startedAt >= timeoutMs) {
        throw new LedgerOperationError('后台仍在处理原请求，请稍后查询同一请求的结果。', initial);
      }
      await new Promise(resolve => setTimeout(resolve, intervalMs));
      try { result = await transport(initial.pollUrl); }
      catch (error) {
        if (isLedgerAccessError(error)) {
          outstanding.clear();
          throw error;
        }
        const detail = error instanceof Error ? error.message : '查询连接暂时中断';
        throw new LedgerOperationError(detail + '；原请求可能仍在处理，请查询原回执。', initial);
      }
    }
    if (result && typeof result === 'object' && !Array.isArray(result)) {
      const record = result as Record<string, unknown>;
      if (record.state === 'failed') {
        outstanding.delete(key);
        throw new LedgerOperationError(typeof record.error === 'string' ? record.error : '后台任务未完成，请核对原请求。', initial);
      }
      if ((record.state === 'completed' || record.state === 'succeeded') && 'result' in record) {
        outstanding.delete(key);
        return record.result;
      }
    }
    outstanding.delete(key);
    return result;
  };
}

