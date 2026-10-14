import type { V2State } from '../lib/v2-types';
import type { ItemAttention } from './item-workspace-model';

// These are view groups only. The underlying feedback and approval states stay separate.
export type AttentionFilter = 'check' | 'followup';
export const attentionFilters: [AttentionFilter, string][] = [
  ['followup', '待跟进'], ['check', '待核对'],
];
export function attentionFilter(value = 'followup'): AttentionFilter {
  if (['confirmation', 'response', 'check', 'acceptance'].includes(value)) return 'check';
  return 'followup';
}
export function matchesAttentionFilter(item: ItemAttention, filter: AttentionFilter) {
  const category = attentionViewCategory(item);
  return filter === 'check' ? ['confirmation', 'response', 'acceptance'].includes(category) : category === filter;
}
export function attentionViewCategory(item: ItemAttention) {
  return item.category === 'followup' && item.followup?.pendingReply ? 'response' : item.category;
}
export function attentionLabel(item: ItemAttention) {
  return ({ confirmation: '待核对', response: '新反馈', acceptance: '交付状态待核对', followup: '待跟进' })[attentionViewCategory(item)];
}
export function attentionPresentation(s: V2State, item: ItemAttention) {
  const reason = item.reasons.find(reason => reason.startsWith(item.requiresVerification?'AI疑点待核实：':'已核实风险：')) || item.reason;
  const group = item.kind === 'changeGroups' ? s.changeGroups.find(row => row.id === item.targetId) : undefined;
  const pending = group?.operations.filter(op => !op.status || op.status === 'pending').length || 0;
  const node = ['flowNodes', 'milestones'].includes(item.kind);
  const discovery = item.kind==='sources' && s.sources.some(row=>item.managementSourceIds?.includes(row.id)&&row.managementSignal?.triage);
  const title = group ? `核对 ${pending} 项修改建议` : item.title;
  const action = group ? `审核 ${pending} 项修改` : node ? '核对节点记录' : attentionViewCategory(item) === 'response' ? '核对反馈'
    : item.kind === 'deliverables' && item.category === 'acceptance' ? '核对工程师交付状态'
    : discovery ? '核实风险与归属' : item.kind === 'sources' ? '核对资料' : item.kind === 'decisions' ? '查看决策记录'
    : item.kind === 'risks' ? '查看风险记录' : item.kind === 'cases' ? '处理专项' : '处理跟进';
  const summary = group ? item.title.length > 180 ? item.title.slice(0, 180) + '…' : item.title : item.reason;
  return { title, action, summary, reason, openRecord: !!group || node || ['decisions', 'risks', 'cases'].includes(item.kind),
    type: group ? '修改建议' : discovery ? '风险识别' : node ? '节点核对' : item.kind === 'deliverables' ? '交付物' : '' };
}
