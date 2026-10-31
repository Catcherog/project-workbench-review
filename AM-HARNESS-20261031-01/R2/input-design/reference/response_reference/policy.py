"""Generation policy is per task family and claim risk, not a global rewrite."""
from __future__ import annotations

from dataclasses import dataclass
from .types import OutcomeEnvelope, Risk, TaskFamily


@dataclass(frozen=True)
class ResponsePolicy:
    # This is NEW expression policy, not the legacy output_rewrite switch.
    # Production needs a separate integration flag/compatibility renderer.
    mode: str = "off"  # off / shadow / enforce; default remains off.
    generated_families: frozenset[TaskFamily] = frozenset()
    paraphrase_risks: frozenset[Risk] = frozenset({Risk.LOW, Risk.REVIEWED})
    max_model_seconds: float = 15.0
    # A deployment should set this from measured local latency rather than
    # promising that a multi-second Qwen call fits a five-second read path.
    min_viable_seconds: float = 1.0
    finish_reserve_seconds: float = 0.5
    max_output_chars: int = 1600
    max_segments: int = 12

    def __post_init__(self):
        import math
        if self.mode not in {"off", "shadow", "enforce"}:
            raise ValueError("RESPONSE_MODE_INVALID")
        for value in (self.max_model_seconds, self.min_viable_seconds, self.finish_reserve_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("RESPONSE_BUDGET_INVALID")
        if not 0 < self.max_model_seconds <= 30 or self.min_viable_seconds > self.max_model_seconds:
            raise ValueError("RESPONSE_BUDGET_INVALID")
        if type(self.max_output_chars) is not int or not 80 <= self.max_output_chars <= 12000:
            raise ValueError("RESPONSE_SIZE_INVALID")
        if type(self.max_segments) is not int or not 1 <= self.max_segments <= 32:
            raise ValueError("RESPONSE_SIZE_INVALID")
        if Risk.CRITICAL in self.paraphrase_risks:
            raise ValueError("CRITICAL_CLAIMS_REQUIRE_HOST_BLOCKS")

    def permits_text(self, envelope: OutcomeEnvelope) -> bool:
        # Critical control/effect communication is not unlockable by an ordinary
        # feature flag. Read/analysis prose remains genuinely generative.
        locked_families = {TaskFamily.PREVIEW, TaskFamily.EXECUTION_RECEIPT,
                           TaskFamily.CANCEL, TaskFamily.UNKNOWN, TaskFamily.FAILURE}
        return (self.mode != "off" and envelope.family in self.generated_families
                and envelope.family not in locked_families
                and envelope.content_mode != "metadata_only")

