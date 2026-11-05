import type { LedgerRequest } from './types';
import { LedgerRequestError, readLedgerResponse } from './request-error';
export { LedgerRequestError, readLedgerResponse, isLedgerAccessError } from './request-error';

interface HostTransport {
  /** Use the existing authenticated state loader. This function must reject non-2xx results. */
  load: (path: string) => Promise<unknown>;
  /** Wrap the original FeedbackRequest POST function; preserve its CSRF/session handling. */
  post: (path: string, body: Record<string, unknown>) => Promise<unknown>;
}

/**
 * Explicitly compose GET and POST. The original FeedbackRequest is not assumed to support GET.
 * Never add a browser-provided tenantId/userId as a trusted identity header.
 */
export function createLedgerHostRequest({ load, post }: HostTransport): LedgerRequest {
  return (path, body) => {
    if (!path.startsWith('/api/v2/ledger/')) {
      return Promise.reject(new Error('台账请求超出已配置接口范围'));
    }
    return body === undefined ? load(path) : post(path, body);
  };
}

interface NativeTransport {
  /** Read the currently active host token already obtained from the original /api/v2/status. */
  readToken: () => string | null | undefined;
  fetcher?: typeof fetch;
}

/** Native local-WB transport. The browser supplies Origin; identity never comes from JSON fields. */
export function createNativeLedgerRequest({ readToken, fetcher = fetch }: NativeTransport): LedgerRequest {
  return async (path, body) => {
    const url = new URL(path, window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/v2/ledger/')
        || path.includes('\\') || url.hash) {
      throw new LedgerRequestError('台账请求超出当前同源接口范围。', { status: 403, code: 'WEB_SCOPE_DENIED' });
    }
    const token = readToken();
    if (typeof token !== 'string' || !token.trim()) {
      throw new LedgerRequestError('当前工作台令牌尚未就绪，请重新核对连接。', { status: 401, code: 'WORKBENCH_TOKEN_MISSING' });
    }
    const response = await fetcher(url.pathname + url.search, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'same-origin',
      headers: {
        'X-Workbench-Token': token,
        'X-Workbench-Client': 'ui',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    return readLedgerResponse(response);
  };
}

/*
Host integration, inside the existing authenticated WB main area:

const ledgerRequest = createLedgerHostRequest({
  load: existingAuthenticatedGetLoader,
  post: (path, body) => existingFeedbackRequest(path, body),
});
<LedgerWorkbench request={ledgerRequest} />

The host must supply its real GET loader and POST callback. This module does not create a
credential-free fetch fallback. The server derives identity and authorization from the session.
*/

