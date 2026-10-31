"""Reference response policy. All production effects remain injected ports.

This class prepares text only. The caller must finalize it BEFORE the original
ConversationAgent._finish, then use the original publication/receipt lifecycle.
"""
from __future__ import annotations

import math
import time
from .policy import ResponsePolicy
from .protocols import (CandidateModel, EnvelopeGuard, HostRenderer,
                        ModelNotDispatched, ModelStoppedFailure, SemanticAssessor)
from .types import OutcomeEnvelope, PreparedResponse, ResponsePlan, Route, RunBinding, TextSegment
from .validation import PlanError, parse_plan, validate_plan, validate_envelope_boundary


class ResponseOrchestrator:
    def __init__(self, *, policy: ResponsePolicy, guard: EnvelopeGuard,
                 host_renderer: HostRenderer, model: CandidateModel | None = None,
                 semantic_assessor: SemanticAssessor | None = None,
                 clock=time.monotonic):
        self.policy, self.guard = policy, guard
        self.host_renderer, self.model, self.clock = host_renderer, model, clock
        self.semantic_assessor = semantic_assessor

    def prepare(self, envelope: OutcomeEnvelope, *, route: Route,
                deadline: float, existing_plan: ResponsePlan | str | None = None) -> PreparedResponse:
        self.guard.check(envelope, "response_entry")
        validate_envelope_boundary(envelope)
        if route == Route.DURABLE_EXPRESSION and not isinstance(envelope.fence, RunBinding):
            raise ValueError("DURABLE_EXPRESSION_REQUIRES_RUN_BINDING")
        p = self.policy
        calls = 0

        def host(reason: str, candidate: str | None = None) -> PreparedResponse:
            # This guard is outside provider-error handling. A revoked source
            # must not become a stale-text fallback, including in shadow mode.
            self.guard.check(envelope, "before_host_fallback")
            text = self.host_renderer.render(envelope, reason=reason)
            if not isinstance(text, str) or not text.strip():
                raise ValueError("HOST_RENDERER_INVALID")
            if any(v and v in text for v in envelope.forbidden_literals):
                raise ValueError("HOST_RENDERER_EXPOSED_INTERNAL_LITERAL")
            # Critical text is authoritative even when the short-body target
            # cannot be met. Production HostRenderer may paginate; it may not
            # truncate approved previews or drop unknown/partial outcomes.
            cursor = 0
            for block in sorted(envelope.protected, key=lambda b: b.order):
                if not block.required:
                    continue
                index = text.find(block.exact_text, cursor)
                if index < 0:
                    raise ValueError("HOST_RENDERER_DROPPED_PROTECTED_BLOCK")
                cursor = index + len(block.exact_text)
            self.guard.check(envelope, "after_host_fallback")
            return PreparedResponse(text, envelope.fingerprint, envelope.fence,
                "host", reason, calls, tuple((b.block_id, b.text_digest) for b in envelope.protected if b.required),
                False, candidate)

        if p.mode == "off" or not p.permits_text(envelope):
            return host("host_only_policy")
        if route in {Route.READONLY_FAST, Route.HOST_ONLY}:
            return host("no_additional_model_on_this_route")
        if existing_plan is not None and route != Route.MAIN_FINAL:
            raise ValueError("EXISTING_PLAN_REQUIRES_MAIN_FINAL_ROUTE")
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError("SHARED_MONOTONIC_DEADLINE_REQUIRED")
        raw = existing_plan
        origin = "main_model"
        if raw is None:
            # A five-second read or a local receipt cannot silently open a model
            # lane. Optional expression must have been admitted as a durable job.
            if route != Route.DURABLE_EXPRESSION or self.model is None:
                return host("no_additional_model_on_this_route")
            remaining = deadline - self.clock() - p.finish_reserve_seconds
            if remaining < p.min_viable_seconds:
                return host("insufficient_shared_budget")
            timeout = min(p.max_model_seconds, remaining)
            self.guard.check(envelope, "before_expression_model")
            calls = 1
            started = self.clock()
            try:
                raw = self.model.generate(envelope, timeout=timeout, max_output_chars=p.max_output_chars)
            except ModelNotDispatched:
                calls = 0
                self.guard.check(envelope, "after_model_admission_denied")
                return host("model_not_dispatched")
            except ModelStoppedFailure:
                self.guard.check(envelope, "after_expression_model_error")
                return host("model_confirmed_stopped_failure")
            # STOP_UNKNOWN, TimeoutError, GuardRejected and unexpected
            # integration errors propagate to original host isolation.
            self.guard.check(envelope, "after_expression_model")
            if self.clock() - started > timeout:
                return host("expression_slice_exceeded")
            origin = "expression_model"
        self.guard.check(envelope, "before_plan_validation")
        if self.clock() >= deadline - p.finish_reserve_seconds:
            return host("no_validation_budget")
        try:
            plan = parse_plan(raw) if isinstance(raw, str) else raw
            checked = validate_plan(envelope, plan, p)
        except PlanError:
            return host("candidate_mechanically_rejected")
        self.guard.check(envelope, "after_plan_validation")
        if p.mode == "shadow":
            return host("shadow_candidate_not_adopted", checked.text)
        if any(isinstance(segment, TextSegment) for segment in plan.segments):
            if self.semantic_assessor is None:
                return host("semantic_assessment_unavailable")
            assessment = self.semantic_assessor.assess(envelope, plan, checked.text)
            self.guard.check(envelope, "after_semantic_assessment")
            if assessment.verdict != "accepted" or not assessment.profile_id:
                return host("semantic_assessment_" + assessment.verdict)
            if self.clock() >= deadline - p.finish_reserve_seconds:
                return host("assessment_exceeded_budget")
        return PreparedResponse(checked.text, envelope.fingerprint, envelope.fence,
            origin, "qualified_candidate_with_residual_semantic_risk", calls, checked.protected_digests,
            False)

