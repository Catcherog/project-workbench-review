"""Host-owned outcome and response contracts for design review.

The host creates OutcomeEnvelope. Model-generated JSON must never be decoded
as an OutcomeEnvelope, Receipt, SourceStamp or ProtectedBlock.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from hashlib import sha256
import json
from typing import Literal


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


class TaskFamily(StrEnum):
    READ = "read"
    ANALYZE = "analyze"
    FOLLOWUP = "followup"
    SCHEDULE = "schedule"
    NOTE = "note"
    KNOWLEDGE = "knowledge"
    DOCUMENT = "document"
    PREVIEW = "preview"
    EXECUTION_RECEIPT = "execution_receipt"
    CANCEL = "cancel"
    UNKNOWN = "unknown"
    FAILURE = "failure"


class Risk(StrEnum):
    LOW = "low"
    REVIEWED = "reviewed"
    CRITICAL = "critical"


class ReceiptStage(StrEnum):
    NOT_STARTED = "not_started"
    RESERVED = "reserved"
    QUEUED = "queued"
    LOCAL_COMMITTED = "local_committed"
    PLATFORM_ACCEPTED = "platform_accepted"
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED_BEFORE_START = "cancelled_before_start"


class Route(StrEnum):
    MAIN_FINAL = "main_final"
    READONLY_FAST = "readonly_fast"
    DURABLE_EXPRESSION = "durable_expression"
    HOST_ONLY = "host_only"


@dataclass(frozen=True)
class RunBinding:
    scope_key: str
    run_id: str
    revision: int
    cancel_epoch: int
    lease_generation: int
    source_access_version: str


@dataclass(frozen=True)
class EventBinding:
    """Fast/control events use existing event freshness, not a fabricated Run."""
    scope_key: str
    event_id: str
    event_revision: int
    source_access_version: str


BindingToken = RunBinding | EventBinding


@dataclass(frozen=True)
class SourceStamp:
    source_id: str
    content_revision: str
    access_revision: str
    observed_at: str
    expires_at: str | None
    evidence_digest: str
    display_url: str | None = None


@dataclass(frozen=True)
class SemanticClaim:
    claim_id: str
    subject_id: str
    predicate: str
    value: str
    unit: str | None
    polarity: Literal["positive", "negative", "unknown"]
    modality: Literal["asserted", "estimate", "plan", "requirement", "conditional", "unknown"]
    evidence_state: Literal["source_record", "self_report", "owner_reviewed", "platform_verified", "inference"]
    # Event time is distinct from source observation time.
    event_time: str | None
    event_time_kind: str | None
    qualifiers: tuple[str, ...]
    source_ids: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    risk: Risk = Risk.REVIEWED
    required: bool = False


@dataclass(frozen=True)
class EffectReceipt:
    receipt_id: str
    work_unit_id: str
    action_id: str
    action_revision: int
    operation: str
    target_id: str
    payload_digest: str
    idempotency_key: str
    stage: ReceiptStage
    verification_source: str | None
    observed_at: str
    # Original host readback establishes this value; not the model.
    verification_digest: str | None = None


@dataclass(frozen=True)
class WorkUnit:
    work_unit_id: str
    requested_operation: str
    target_id: str | None
    result: Literal["not_started", "needs_input", "needs_approval", "queued", "partial", "complete", "failed", "unknown"]
    receipt_ids: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    effect: Literal["read", "local", "external"] = "read"


@dataclass(frozen=True)
class CoverageGap:
    gap_id: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class ProtectedBlock:
    block_id: str
    role: Literal["preview", "receipt", "critical_fact", "quotation", "control", "artifact", "failure"]
    exact_text: str
    claim_ids: tuple[str, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    required: bool = True
    # Relative order is host-owned, particularly for conditions and approvals.
    order: int = 0
    content_class: Literal["content", "metadata"] = "content"
    work_unit_ids: tuple[str, ...] = ()
    gap_ids: tuple[str, ...] = ()

    @property
    def text_digest(self) -> str:
        return sha256(self.exact_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OutcomeEnvelope:
    outcome_id: str
    family: TaskFamily
    fence: BindingToken
    work_units: tuple[WorkUnit, ...]
    claims: tuple[SemanticClaim, ...]
    sources: tuple[SourceStamp, ...]
    receipts: tuple[EffectReceipt, ...]
    protected: tuple[ProtectedBlock, ...]
    coverage_gaps: tuple[CoverageGap, ...] = ()
    forbidden_literals: tuple[str, ...] = ()
    allowed_urls: tuple[str, ...] = ()
    content_mode: Literal["content", "metadata_only"] = "content"
    # Actual host event identities are distinct from Run/target action ids.
    # Required in a production adapter, optional only for isolated fixtures.
    origin_event_id: str | None = None
    engine_event_id: str | None = None

    @property
    def fingerprint(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class TextSegment:
    text: str
    claim_ids: tuple[str, ...]
    intent: Literal["answer", "analysis", "recommendation", "question", "acknowledgement"]


@dataclass(frozen=True)
class LockedSegment:
    block_id: str


@dataclass(frozen=True)
class ResponsePlan:
    envelope_fingerprint: str
    segments: tuple[TextSegment | LockedSegment, ...]
    omitted_optional_claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MechanicalValidation:
    text: str
    declared_claim_coverage: tuple[str, ...]
    locked_claim_coverage: tuple[str, ...]
    protected_digests: tuple[tuple[str, str], ...]
    # Always False for arbitrary model paraphrases. The name prevents callers
    # from equating structural success with proven semantic fidelity.
    semantic_equivalence_proven: bool = False


@dataclass(frozen=True)
class PreparedResponse:
    text: str
    envelope_fingerprint: str
    fence: BindingToken
    origin: Literal["host", "main_model", "expression_model"]
    disposition: str
    extra_model_calls: int
    protected_digests: tuple[tuple[str, str], ...]
    semantic_equivalence_proven: bool = False
    candidate_text_for_private_eval: str | None = None


@dataclass(frozen=True)
class SemanticAssessment:
    """Risk admission evidence, never a mathematical equivalence certificate."""
    verdict: Literal["accepted", "rejected", "unavailable"]
    profile_id: str
    reasons: tuple[str, ...] = ()

