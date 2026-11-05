export type RowKey = 'plan' | 'progress' | 'blocker' | 'todo';
export type SemanticVersion = string | number | null;

/** The host owns credentials and workspace access. Undefined body means GET. */
export type LedgerRequest = (path: string, body?: Record<string, unknown>) => Promise<unknown>;

export interface Evidence {
  sourceId: string;
  objectId: string;
  version: number | string | null;
  quote: string | null;
  rawAvailable: boolean;
  rawExpiresAt?: string | null;
  verification: string;
  url: string | null;
  occurredAt: string | null;
  receivedAt: string | null;
  stale: boolean;
}
export interface Entry {
  id: string;
  itemId?: string | null;
  factIds?: string[];
  text: string;
  date?: string | null;
  certainty: string;
  critical: boolean;
  sourceRefs: Evidence[];
  retentionBoundExcerpt?: boolean;
  rawExcerptUnavailable?: boolean;
}
export interface ProcessingGap {
  id: string;
  kind: 'processing';
  projectIds: string[];
  reason: string;
  gapCode: string;
  text: string;
  retentionBoundExcerpt: true;
  rawExcerptUnavailable: boolean;
  sourceRefs: Evidence[];
}
export interface Project {
  id: string;
  title: string;
  kind: 'project' | 'outside';
  status: 'active' | 'paused' | 'closed' | 'unknown';
  needsAttention: boolean;
  reviewCount: number;
}
export interface Coverage {
  status: string;
  checkedAt: string | null;
  reasons: string[];
  processingGaps?: ProcessingGap[];
}
export interface SummaryRow {
  key: RowKey;
  label: string;
  text: string;
  entries: Entry[];
  moreEntries: Entry[];
  severity: 'normal' | 'attention' | 'critical' | 'unknown';
}
export interface Review {
  id: string;
  projectId?: string | null;
  itemId?: string | null;
  question: string;
  reason: string;
  excerpt: string;
  evidence: Evidence[];
  choices: { id: string; label: string; value: unknown }[];
  basis: string;
  status: 'pending' | 'resolved';
}
export interface Reminder {
  id: string;
  itemId: string;
  projectId: string;
  title: string;
  body: string;
  priority: string | number;
  dueAt?: string | null;
  displayState: 'unread' | 'read' | 'snoozed';
  snoozedUntil?: string | null;
  businessState: 'open' | 'waiting' | 'paused' | 'closed' | 'cancelled';
  basis?: string;
}
export interface WorkItem {
  id: string;
  projectId: string;
  title: string;
  version: number;
  semanticVersion: SemanticVersion;
  businessState: 'open' | 'waiting' | 'paused' | 'closed' | string;
  priority: string | number;
  requiresViewerAction: boolean;
  actionText?: string;
  dueAt?: string | null;
  deadlineKind: string;
  nextCheckAt?: string | null;
  assignees: (string | { id: string; name?: string; displayName?: string })[];
  view?: unknown;
}
export interface Bootstrap {
  schemaVersion: 1;
  workspaceId: string;
  viewerId: string;
  basis: string;
  generatedAt: string;
  coverage: Coverage;
  projects: Project[];
  reviews: Review[];
  reminders: Reminder[];
  continuity?: Continuity;
}
export interface Continuity {
  schemaVersion: 1;
  basis: string;
  generatedAt: string;
  scope: 'registered_authorized_items';
  openCount: number;
  waitingCount: number;
  pausedCount: number;
  needsReviewCount: number;
  uncertainDeliveryCount: number;
  outside: {projectId: string; title: string; coverage: Coverage;
    items: Pick<WorkItem, 'id' | 'title' | 'businessState' | 'priority' | 'nextCheckAt' | 'dueAt' | 'deadlineKind'>[]}[];
  attention: {id: string; projectId: string; itemId: string; title: string; reason: string;
    priority: string | number; kind: string; businessState: string; nextCheckAt: string | null}[];
}
export interface ProjectSummary {
  project: Project;
  basis: string;
  generatedAt: string;
  coverage: Coverage;
  rows: SummaryRow[];
  reviewCount: number;
  reminders: Reminder[];
  details: { facts: unknown[]; items: WorkItem[]; processingGaps?: ProcessingGap[] };
}
export type AMChannel = 'group' | 'recipient_p2p';
export interface AMPreview {
  previewId: string;
  contentHash: string;
  displayHash: string;
  version: 1;
  expiresAtMs: number;
  itemId: string;
  projectId: string;
  target: {
    channel: AMChannel;
    id: string;
    name: string;
    attention: { id: string; name: string }[];
  };
  body: string;
  count: 1;
  sendWindow: { notBeforeMs: number; expiresAtMs: number; immediate: true };
  followup: string;
  dependenciesHash: string;
}
export type AMRecommendation =
  | { kind: 'wait'; recommendation: string; reason: string; nextCheckAt?: string }
  | { kind: 'choose'; recommendation: string; reason: string; items: { id: string; title: string }[] }
  | { kind: 'choose_route'; recommendation: string; reason: string; allowedChannels: AMChannel[];
      assigneeIds: string[]; assignees?: { id: string; name?: string }[] }
  | {
      kind: 'action'; recommendation: string; reason: string; itemId: string;
      expectedItemVersion: number; expectedSemanticVersion: SemanticVersion; preview: AMPreview;
    };
export interface AMPresentation { presentationId: string; expiresAtMs: number }
export interface AMReceipt {
  requestId: string;
  intentId?: string;
  occurrenceId?: string;
  state: string;
  messageId?: string | null;
  readbackState?: string | null;
  reason?: string | null;
  updatedAt?: string;
}
export interface AMActionRequest {
  projectId: string;
  requestId: string;
  itemId: string;
  expectedItemVersion: number;
  expectedSemanticVersion: SemanticVersion;
  channel: AMChannel;
  recipientId?: string;
  body: string;
  purpose: 'request_progress';
  previousPreviewId: string;
}

