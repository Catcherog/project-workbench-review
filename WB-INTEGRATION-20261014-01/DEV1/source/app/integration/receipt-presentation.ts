/** Accepts the existing P1 receipt, never an LLM answer or job.status. No writes and no date parsing of user input. */
export type SavedReceipt = {
  operationId?: string; sourceId?: string; at?: string; undoneAt?: string; duplicate?: boolean;
  closed?: boolean; pendingChanges?: unknown[]; progress?: string;
};
export function receiptPresentation(receipt: SavedReceipt) {
  if (!receipt.operationId || !receipt.sourceId) return { title: '保存回执不完整，请重新读取', tone: 'amber' as const };
  if (receipt.undoneAt) return { title: '本次操作已撤销', tone: 'neutral' as const };
  if (receipt.duplicate) return { title: '同一原图已记录，本次未重复保存', tone: 'blue' as const };
  if (receipt.pendingChanges?.length) return { title: '本次记录已保留；较新安排未被覆盖', tone: 'amber' as const };
  if (receipt.closed) return { title: '已保存，已移入“已结束”', tone: 'green' as const };
  return { title: '本地记录已保存', tone: 'green' as const };
}
export function receiptTimestamp(at?: string): string {
  if (!at || !Number.isFinite(Date.parse(at))) return '保存时间未提供';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(at)) + '（北京时间）';
}
export type SaveProjection = {
  status?: string; save?: {status?: string; receipt?: SavedReceipt};
  preparation?: {status?: string; reason?: string; error?: string}; jobStatus?: string;
};
/** R2-FIX1 colleague contract: only save.status + durable receipt support a saved label. */
export function inputSavePresentation(value: SaveProjection) {
  const receipt = value.save?.receipt;
  const saved = value.save?.status === 'saved' && !!receipt?.operationId && !receipt.undoneAt;
  return { saved, title: saved ? '业务记录已保存' : receipt?.undoneAt ? '原保存已撤销' : '尚无有效业务保存回执',
    preparation: value.preparation?.status || '', preparationReason: value.preparation?.reason || value.preparation?.error || '', jobStatus: value.jobStatus || '' };
}
