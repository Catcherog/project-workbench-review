"""Ports for adapters Codex must implement and verify against the real host."""
from __future__ import annotations

from typing import Protocol
from .types import OutcomeEnvelope, PreparedResponse, ResponsePlan, SemanticAssessment


class GuardRejected(RuntimeError):
    """Cancellation, revision, permission, source or execution fence changed."""


class ModelNotDispatched(RuntimeError):
    """Admission/budget denied before inference: zero dispatched calls."""


class ModelStoppedFailure(RuntimeError):
    """Dispatched, but original coordinator CONFIRMED the model has stopped."""


class ModelStopUnknown(RuntimeError):
    """Original STOP_UNKNOWN isolation; do not fallback or release its lane."""


class EnvelopeGuard(Protocol):
    def check(self, envelope: OutcomeEnvelope, phase: str) -> None:
        """Raise GuardRejected for stale scope/source/fence/deadline.

        The production implementation must check current host state. Matching
        the original in-memory dataclass is not sufficient.
        """
        ...


class CandidateModel(Protocol):
    def generate(self, envelope: OutcomeEnvelope, *, timeout: float,
                 max_output_chars: int) -> str | ResponsePlan:
        """One read-only proposal through the original ModelCoordinator.

        The production adapter builds a minimal authorized projection; it must
        not serialize credentials, internal ids or all historical text. It may
        not call business tools, create another coordinator or retry. Errors
        distinguish not-dispatched, confirmed-stopped and STOP_UNKNOWN; a raw
        TimeoutError must never be mapped to a confirmed stop without evidence.
        """
        ...


class HostRenderer(Protocol):
    def render(self, envelope: OutcomeEnvelope, *, reason: str) -> str:
        """Natural deterministic rendering of the complete actual outcome.

        Must retain required claims, protected text and every requested work
        unit's actual status, including partial/unknown. No external actions.
        This remains a required adapter, not a generic 'completed' template.
        """
        ...


class SemanticAssessor(Protocol):
    def assess(self, envelope: OutcomeEnvelope, plan: ResponsePlan,
               rendered_text: str) -> SemanticAssessment:
        """Admit a measured, explicitly qualified free-expression profile.

        This reference port must not perform another model/network call. A
        production profile combines scoped offline qualification and applicable
        domain checks, with human evaluation and measured residual error. The
        same model's claim_ids/self-review is insufficient. If no profile/check
        can support this family, language, schema or risk, return unavailable.
        Even accepted is risk admission, not proof of arbitrary paraphrases.
        """
        ...


class OutcomeAdapter(Protocol):
    def normalize(self, host_result: object, host_context: object) -> OutcomeEnvelope:
        """Convert known original host schemas, preserving evidence levels.

        Unrecognized result schemas must stay explicitly unsupported/locked;
        do not silently infer verified success from a message string.
        """
        ...


class PresentationCommitter(Protocol):
    def persist(self, response: PreparedResponse, host_context: object) -> object:
        """Original _finish/history/publication integration; not provided here.

        Recheck the same fence and sources at the existing commit and dispatch
        boundaries. Preserve FIX1 local effects, presentation and history logic.
        """
        ...

