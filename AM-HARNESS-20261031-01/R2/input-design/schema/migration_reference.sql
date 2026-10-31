-- DESIGN ONLY. Do not execute this entire file against an existing service.
-- Each section belongs in the corresponding existing database migration.
-- Runtime effects, action status and delivery truth remain in existing tables.
-- Migration version guards, retention policy and actual table prefixes must be
-- resolved in the real repository. No DROP, ALTER, UPDATE or backfill is issued here.

-- SECTION: conversation database
CREATE TABLE am_response_contract_v2 (
    contract_id TEXT PRIMARY KEY,
    binding_key TEXT NOT NULL,
    origin_event_id TEXT NOT NULL,
    engine_event_id TEXT,
    schema_version TEXT NOT NULL,
    outcome_hash TEXT NOT NULL,
    task_family TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    CHECK (expires_at >= created_at),
    UNIQUE (binding_key, outcome_hash)
);

CREATE TABLE am_response_attempt_v2 (
    attempt_id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL REFERENCES am_response_contract_v2(contract_id),
    strategy TEXT NOT NULL CHECK (strategy IN ('direct','canonical','single_composition','protected')),
    profile_version TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN (
        'not_needed','not_attempted','planned','generating','accepted',
        'rejected','fallback','suppressed')),
    reason_codes_json TEXT NOT NULL,
    model_calls INTEGER NOT NULL DEFAULT 0 CHECK (model_calls >= 0),
    elapsed_ms INTEGER NOT NULL DEFAULT 0 CHECK (elapsed_ms >= 0),
    candidate_hash TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE am_response_presentation_v2 (
    presentation_id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL REFERENCES am_response_contract_v2(contract_id),
    binding_key TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('final','progress','terminal_notice')),
    purpose_sequence INTEGER NOT NULL DEFAULT 0 CHECK (purpose_sequence >= 0),
    selected_attempt_id TEXT REFERENCES am_response_attempt_v2(attempt_id),
    semantic_text TEXT NOT NULL,
    semantic_hash TEXT NOT NULL,
    renderer_version TEXT NOT NULL,
    dependency_hash TEXT NOT NULL,
    prepared_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    UNIQUE (binding_key, purpose, purpose_sequence)
);

CREATE INDEX am_response_contract_expiry_v2
    ON am_response_contract_v2(expires_at);

-- SECTION: gateway database (do not create a cross-database FK)
-- The original outbox remains the delivery authority. This table is a binding
-- index/projection, written within the existing enqueue transaction.
CREATE TABLE am_response_outbox_binding_v2 (
    outbox_id TEXT PRIMARY KEY,
    presentation_id TEXT NOT NULL,
    part_index INTEGER NOT NULL DEFAULT 0 CHECK (part_index >= 0),
    part_count INTEGER NOT NULL DEFAULT 1 CHECK (part_count >= 1),
    binding_key TEXT NOT NULL,
    semantic_hash TEXT NOT NULL,
    rendered_hash TEXT NOT NULL,
    context_schema_version TEXT NOT NULL,
    dependency_envelope_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    CHECK (part_index < part_count),
    UNIQUE (presentation_id, part_index)
);

-- A second business-state table is deliberately absent. GoalProgress may be
-- added through the real task store, keyed by stable scope/goal identity, after
-- its relationship with current followup/action/document records is verified.

