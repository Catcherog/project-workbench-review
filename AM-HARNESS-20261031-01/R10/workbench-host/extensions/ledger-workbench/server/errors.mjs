export class LedgerError extends Error {
  constructor(code, message, status = 400, details = {}) {
    super(message); this.name = 'LedgerError'; this.code = code; this.status = status; this.details = details;
  }
}

export function publicError(error) {
  if (error instanceof LedgerError) return { code: error.code, message: error.message, ...error.details };
  return { code: 'internal_error', message: '暂时未能处理，请保留当前内容后重试。' };
}
