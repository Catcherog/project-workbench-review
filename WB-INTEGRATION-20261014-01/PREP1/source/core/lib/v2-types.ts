import type { State, Item } from './domain';

export const v2Kinds = ['projects','milestones','dependencies','risks','decisions','actions','sources','judgments','people','resources','relations','flowNodes','deliverables','externalLinks','cases'] as const;
export type V2Kind = typeof v2Kinds[number];
/** Registry collections are local-only snapshots.  They are deliberately kept
 * outside v2Kinds because they do not represent ordinary business records. */
export const registryKinds = ['externalObjects','remoteFieldValues','mappingRules','syncBaselines','syncRuns','syncReceipts','dispatchRecords'] as const;
export type RegistryKind = typeof registryKinds[number];
export type FieldError = { path: string; message: string; before?: unknown; current?: unknown; proposed?: unknown };
export type Operation = {
  id: string; kind: V2Kind; targetId: string; action: 'create' | 'update';
  before: Record<string, any>; after: Record<string, any>; reason: string;
  sourceIds: string[]; classification: 'fact' | 'suggestion' | 'hypothesis';
  missingInfo: string[]; atomicGroup?: string; status?: 'pending' | 'accepted' | 'rejected';
};
export type DraftInput = {
  workspaceId: string; request: string; purpose: string; creator: string;
  baseRevision: number; idempotencyKey: string; operations: Operation[];
};
export type ChangeGroup = DraftInput & {
  id: string; createdAt: string; draftVersion: number; fingerprint: string;
  status: 'pending' | 'partial' | 'accepted' | 'conflict' | 'rejected' | 'withdrawn';
  reviewComment?: string; acceptedBy?: string; acceptedAt?: string;
  auditIds: string[]; conflicts?: FieldError[]; history: any[];
  aiTriageSourceIds?:string[];
};
export type AuditEntry = State['audit'][number] & {
  actor?: string; kind?: V2Kind; groupId?: string; revision?: number;
  sourceIds?: string[]; compensates?: string; undoneBy?: string;
};
export type V2State = Omit<State,'audit'> & {
  workspaceId: string; workspaceName: string; workspaceType: 'official' | 'demo' | 'legacy' | 'restored';
  riskPolicy?:{version:number;adoptedAt:string;historicalProjectIds:string[];deferredNodeIds:string[];proposalSourceIds:string[]};
  people: Item[]; resources: Item[]; relations: Item[]; changeGroups: ChangeGroup[];
  flowNodes: Item[]; deliverables: Item[]; externalLinks: Item[]; cases: Item[];
  externalObjects: import('./mapping-registry').ExternalObject[];
  remoteFieldValues: import('./mapping-registry').RemoteFieldValue[];
  mappingRules: import('./mapping-registry').MappingRule[];
  syncBaselines: import('./mapping-registry').SyncBaseline[];
  syncRuns: import('./mapping-registry').SyncRun[];
  syncReceipts: import('./mapping-registry').SyncReceipt[];
  dispatchRecords: import('./mapping-registry').DispatchRecord[];
  audit: AuditEntry[]; viewed: { at: string; auditIds: string[] } | null;
  receipts: Record<string, { fingerprint: string; result: any }>;
  reports: {id: string; createdAt: string; revision: number; projectId: string; content: string}[];
};
export type WorkspaceSummary = {id: string; name: string; type: V2State['workspaceType']; revision: number; counts: Record<string,number>};
export const v2Labels: Record<V2Kind,string> = {
  projects:'项目',milestones:'里程碑',dependencies:'依赖',risks:'风险 / 问题',decisions:'决策',actions:'行动项',sources:'信息来源',judgments:'管理判断',people:'人员',resources:'共享资源',relations:'关系',
  flowNodes:'流程节点',deliverables:'交付物',externalLinks:'外部关联',cases:'专项事项',
};
