export interface LedgerRequestErrorOptions {
  status?: number;
  code?: string;
  details?: unknown;
}
export class LedgerRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  constructor(message: string, { status = 0, code = '', details }: LedgerRequestErrorOptions = {}) {
    super(message);
    this.name = 'LedgerRequestError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
/** Preserve authorization metadata instead of flattening a server error into a message string. */
export async function readLedgerResponse(response: Response): Promise<unknown> {
  let value: unknown;
  try { value = await response.json(); }
  catch {
    throw new LedgerRequestError(response.ok ? '台账接口尚未返回可读结果。' : '台账请求未成功，请重新核对访问状态。', {
      status: response.status, code: response.ok ? 'INVALID_LEDGER_RESPONSE' : 'HTTP_' + response.status,
    });
  }
  if (!response.ok) {
    const detail = record(value) ? value.error : undefined;
    const message = typeof detail === 'string' ? detail
      : record(detail) && typeof detail.message === 'string' ? detail.message : '台账请求未成功，请重新核对。';
    const code = record(detail) && typeof detail.code === 'string' ? detail.code
      : record(value) && typeof value.code === 'string' ? value.code : 'HTTP_' + response.status;
    throw new LedgerRequestError(message, { status: response.status, code, details: detail });
  }
  return value;
}
export function isLedgerAccessError(error: unknown): boolean {
  if (!record(error)) return false;
  const result = record(error.result) && record(error.result.error) ? error.result.error : undefined;
  const status = error.status ?? error.statusCode ?? result?.status;
  const code = String(error.code ?? result?.code ?? '').toUpperCase();
  return status === 401 || status === 403
    || code === 'WEB_SCOPE_DENIED' || code === 'WEB_SOURCE_ACCESS_CHANGED';
}

