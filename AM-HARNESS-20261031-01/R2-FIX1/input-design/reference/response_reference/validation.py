"""Strict plan validation; intentionally not a general semantic-equivalence test."""
from __future__ import annotations

import json
import re
from .policy import ResponsePolicy
from .types import (LockedSegment, MechanicalValidation, OutcomeEnvelope, ResponsePlan,
                    Risk, TextSegment)


class PlanError(ValueError):
    pass


def validate_envelope_boundary(envelope: OutcomeEnvelope) -> None:
    """Small boundary invariant, not full production adapter validation."""
    if envelope.content_mode not in {"content", "metadata_only"}:
        raise ValueError("UNKNOWN_CONTENT_MODE")
    if envelope.content_mode == "metadata_only":
        if envelope.claims or envelope.sources or any(
                block.content_class != "metadata" for block in envelope.protected):
            raise ValueError("METADATA_ONLY_MUST_NOT_CARRY_OLD_CONTENT")
    units = {u.work_unit_id: u for u in envelope.work_units}
    gaps = {g.gap_id: g for g in envelope.coverage_gaps}
    receipts = {r.receipt_id: r for r in envelope.receipts}
    if (len(units) != len(envelope.work_units) or len(gaps) != len(envelope.coverage_gaps)
            or len(receipts) != len(envelope.receipts)):
        raise ValueError("DUPLICATE_OUTCOME_ID")
    for receipt in envelope.receipts:
        if receipt.work_unit_id not in units:
            raise ValueError("RECEIPT_WORK_UNIT_UNKNOWN")
    for unit in envelope.work_units:
        if (not set(unit.receipt_ids) <= receipts.keys()
                or any(receipts[r].work_unit_id != unit.work_unit_id for r in unit.receipt_ids)):
            raise ValueError("WORK_UNIT_RECEIPT_BINDING_INVALID")
    locked_units, locked_gaps, locked_receipts = set(), set(), set()
    for block in envelope.protected:
        if (not set(block.work_unit_ids) <= units.keys()
                or not set(block.gap_ids) <= gaps.keys()
                or not set(block.receipt_ids) <= receipts.keys()):
            raise ValueError("PROTECTED_OUTCOME_BINDING_INVALID")
        if block.required:
            locked_units.update(block.work_unit_ids)
            locked_gaps.update(block.gap_ids)
            locked_receipts.update(block.receipt_ids)
    for unit in envelope.work_units:
        if ((unit.effect != "read" or unit.result != "complete" or unit.receipt_ids or unit.unresolved)
                and unit.work_unit_id not in locked_units):
            raise ValueError("WORK_UNIT_STATUS_REQUIRES_HOST_BLOCK")
    if any(g.required and g.gap_id not in locked_gaps for g in envelope.coverage_gaps):
        raise ValueError("IMPORTANT_GAP_REQUIRES_HOST_BLOCK")
    if receipts.keys() - locked_receipts:
        raise ValueError("EFFECT_RECEIPT_REQUIRES_HOST_BLOCK")


def _fail(code):
    raise PlanError(code)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _fail("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _ids(value):
    if (type(value) is not list or len(value) > 128
            or any(type(v) is not str or not v or len(v) > 128 for v in value)
            or len(value) != len(set(value))):
        _fail("INVALID_REFERENCE_LIST")
    return tuple(value)


def parse_plan(raw: str, *, max_chars: int = 24000) -> ResponsePlan:
    if type(raw) is not str or not raw or len(raw) > max_chars:
        _fail("INVALID_PLAN_SIZE")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
            parse_constant=lambda _: _fail("INVALID_JSON_NUMBER"))
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, PlanError):
            raise
        _fail("INVALID_PLAN_JSON")
    if (type(value) is not dict or set(value) != {"envelope_fingerprint", "segments", "omitted_optional_claim_ids"}
            or type(value["envelope_fingerprint"]) is not str
            or type(value["segments"]) is not list or not 1 <= len(value["segments"]) <= 32):
        _fail("INVALID_PLAN_SCHEMA")
    segments = []
    for segment in value["segments"]:
        if type(segment) is not dict:
            _fail("INVALID_SEGMENT")
        if segment.get("kind") == "locked":
            if set(segment) != {"kind", "block_id"} or type(segment["block_id"]) is not str:
                _fail("INVALID_LOCKED_SEGMENT")
            segments.append(LockedSegment(segment["block_id"]))
        elif segment.get("kind") == "text":
            if (set(segment) != {"kind", "text", "claim_ids", "intent"}
                    or type(segment["text"]) is not str or not segment["text"].strip()
                    or type(segment["intent"]) is not str
                    or segment["intent"] not in {"answer", "analysis", "recommendation", "question", "acknowledgement"}):
                _fail("INVALID_TEXT_SEGMENT")
            segments.append(TextSegment(segment["text"], _ids(segment["claim_ids"]), segment["intent"]))
        else:
            _fail("INVALID_SEGMENT_KIND")
    return ResponsePlan(value["envelope_fingerprint"], tuple(segments),
                        _ids(value["omitted_optional_claim_ids"]))


def validate_plan(envelope: OutcomeEnvelope, plan: ResponsePlan,
                  policy: ResponsePolicy) -> MechanicalValidation:
    validate_envelope_boundary(envelope)
    if not isinstance(plan, ResponsePlan) or plan.envelope_fingerprint != envelope.fingerprint:
        _fail("ENVELOPE_FINGERPRINT_MISMATCH")
    if not 1 <= len(plan.segments) <= policy.max_segments:
        _fail("SEGMENT_LIMIT")
    claims = {c.claim_id: c for c in envelope.claims}
    blocks = {b.block_id: b for b in envelope.protected}
    receipts = {r.receipt_id: r for r in envelope.receipts}
    sources = {s.source_id for s in envelope.sources}
    if len(claims) != len(envelope.claims) or len(blocks) != len(envelope.protected) or len(receipts) != len(envelope.receipts):
        _fail("DUPLICATE_HOST_ID")
    for claim in envelope.claims:
        if (not claim.source_ids or not set(claim.source_ids) <= sources
                or not set(claim.depends_on) <= claims.keys()
                or not set(claim.conflicts_with) <= claims.keys()):
            _fail("HOST_CLAIM_BINDING_INVALID")
    for block in envelope.protected:
        if not set(block.claim_ids) <= claims.keys() or not set(block.receipt_ids) <= receipts.keys():
            _fail("HOST_BLOCK_BINDING_INVALID")
    mentioned, locked_claims, used_blocks, rendered, block_orders = set(), set(), set(), [], []
    for segment in plan.segments:
        if isinstance(segment, LockedSegment):
            if segment.block_id not in blocks or segment.block_id in used_blocks:
                _fail("UNKNOWN_OR_DUPLICATE_BLOCK")
            block = blocks[segment.block_id]
            used_blocks.add(segment.block_id)
            mentioned.update(block.claim_ids); locked_claims.update(block.claim_ids)
            block_orders.append(block.order)
            rendered.append(block.exact_text)
        elif isinstance(segment, TextSegment):
            if (type(segment.text) is not str or type(segment.claim_ids) is not tuple
                    or any(type(i) is not str for i in segment.claim_ids)
                    or type(segment.intent) is not str
                    or segment.intent not in {"answer", "analysis", "recommendation", "question", "acknowledgement"}):
                _fail("INVALID_TYPED_TEXT_SEGMENT")
            if not policy.permits_text(envelope):
                _fail("GENERATED_TEXT_NOT_ENABLED_FOR_FAMILY")
            if not segment.text.strip() or len(segment.text) > policy.max_output_chars:
                _fail("TEXT_SIZE_INVALID")
            if not set(segment.claim_ids) <= claims.keys():
                _fail("UNKNOWN_CLAIM_REFERENCE")
            if len(set(segment.claim_ids)) != len(segment.claim_ids):
                _fail("DUPLICATE_CLAIM_REFERENCE")
            if segment.intent in {"answer", "analysis"} and not segment.claim_ids:
                _fail("GROUNDED_TEXT_REQUIRES_CLAIMS")
            if any(claims[i].risk not in policy.paraphrase_risks for i in segment.claim_ids):
                _fail("CLAIM_REQUIRES_LOCKED_REALIZATION")
            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]|<\s*/?\s*at\b", segment.text, re.I):
                _fail("UNSAFE_TEXT_MARKUP")
            for url in re.findall(r"https?://[^\s<>\]\)）]+", segment.text):
                if url not in envelope.allowed_urls:
                    _fail("URL_NOT_HOST_ALLOWED")
            mentioned.update(segment.claim_ids)
            rendered.append(segment.text)
        else:
            _fail("INVALID_SEGMENT_TYPE")
    if block_orders != sorted(block_orders):
        _fail("LOCKED_BLOCK_ORDER_CHANGED")
    if any(b.required and b.block_id not in used_blocks for b in envelope.protected):
        _fail("REQUIRED_BLOCK_OMITTED")
    if any(c.required and c.claim_id not in mentioned for c in envelope.claims):
        _fail("REQUIRED_CLAIM_NOT_DECLARED")
    if any(c.risk == Risk.CRITICAL and c.required and c.claim_id not in locked_claims for c in envelope.claims):
        _fail("CRITICAL_CLAIM_NOT_LOCKED")
    for ident in mentioned:
        if not set(claims[ident].depends_on) <= mentioned:
            _fail("CLAIM_DEPENDENCY_OMITTED")
        if not set(claims[ident].conflicts_with) <= mentioned:
            _fail("CONFLICT_SIDE_OMITTED")
    omitted = set(plan.omitted_optional_claim_ids)
    if (not omitted <= claims.keys() or omitted & mentioned
            or any(claims[i].required for i in omitted)):
        _fail("INVALID_OMITTED_OPTIONAL_CLAIMS")
    text = "\n\n".join(rendered)
    if len(text) > policy.max_output_chars:
        _fail("RESPONSE_TOO_LONG")
    if any(v and v in text for v in envelope.forbidden_literals):
        _fail("FORBIDDEN_INTERNAL_LITERAL")
    # References are only declarations. Even a fully cited sentence can invert
    # a predicate or invent a conclusion. Never report semantic proof here.
    return MechanicalValidation(text, tuple(sorted(mentioned)), tuple(sorted(locked_claims)),
        tuple((i, blocks[i].text_digest) for i in sorted(used_blocks)), False)

