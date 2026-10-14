/** Shared proposal, kept in D's module until coordinator wiring. */
export type AssistantContextRef = { kind: 'workspace' | 'sources' | 'projects' | 'cases' | 'flowNodes' | 'deliverables' | 'actions' | 'milestones' | 'risks' | 'decisions'; id: string };
export type SourceLocator = {
  kind: 'text' | 'page' | 'paragraph' | 'table' | 'cell' | 'image';
  label: string; start?: number; end?: number; line?: number; endLine?: number;
  page?: number; paragraph?: number; table?: number; row?: number; sheet?: string; cell?: string;
  attachmentId?: string; documentKey?: string;
};
export type AssistantCitation = {
  citationId: string; sourceId: string; workspaceId: string; version: number | string;
  library?: {id:string;path:string;version:string;sha256:string;kind:string;snapshotDate?:string;originalAvailability?:string;catalogEntryId:string};
  fingerprint: string; title: string; url: string; projectIds: string[]; caseIds: string[];
  occurredAt?: string; collectedAt?: string; timeUncertain?: boolean;
  locator: SourceLocator; quote: string; interpretation: string;
  coverage: 'complete' | 'partial'; availability: 'current' | 'stale';
};
export type AssistantSession = {
  schemaVersion: 1; id: string; workspaceId: string; contextRef: AssistantContextRef;
  projectId: string; lastJobId: string; revision: number; createdAt: string; updatedAt: string;
};
export type AssistantCoverage = { sourceId: string; title: string; complete: boolean; read?:boolean; limitations: string[] };
export type AssistantEvidencePacket = {
  schemaVersion: 1; workspaceId: string; sessionId: string; jobId: string;
  contextRef: AssistantContextRef; projectId: string; baseRevision: number;
  citations: AssistantCitation[]; gaps: string[]; conflicts: { citationIds: string[]; reason: string }[];
  coverage: AssistantCoverage[];
  /** Existing intake observations only; no new reminder/status ledger. */
  feedback: { batchId: string; targetId: string; kind?: string; sourceId: string; quote: string; after: Record<string, unknown> }[];
  signals: { batchId: string; sourceId: string; targetId?: string; title: string; reason: string; quote: string }[];
  pending: { batchId: string; sourceId: string; targetId?: string; reason: string; quote?: string }[];
};
