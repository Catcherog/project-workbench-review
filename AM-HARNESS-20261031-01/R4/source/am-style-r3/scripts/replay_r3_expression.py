#!/usr/bin/env python3
"""Re-score frozen R3 text locally; does not call a model, adopt or send text."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from am_style.contracts import SpeechFrame, StylePolicy
from am_style.natural import NaturalSurfaceVerifier
from am_style.verify import BoundedVerifier, CompositeVerifier
from am_style.latency import summarize_latency


def replay(frozen, comparison):
    frames = {row["case_id"]: SpeechFrame.freeze(row["frame"]) for row in frozen["cases"]}
    policy = StylePolicy(**frozen["policy"])
    output = []
    natural = CompositeVerifier(NaturalSurfaceVerifier())
    for row in comparison["rows"]:
        if row.get("arm") != "qwen":
            continue
        frame = frames[row["case_id"]]
        if row.get("frame_sha256") != frame.fingerprint:
            raise ValueError("R3 frozen frame hash mismatch")
        before = BoundedVerifier().verify(frame, row["candidate_text"], policy)
        after = natural.verify(frame, row["candidate_text"], policy)
        output.append({"case_id": row["case_id"], "candidate_text": row["candidate_text"],
                       "frame_sha256": frame.fingerprint,
                       "r3": {"decision": before.decision, "reason": before.reason},
                       "r4_optional": {"decision": after.decision, "reason": after.reason, "verifier": after.verifier},
                       "human_review_added": False, "adopted": False, "delivered": False})
    return {"schema": "am-r4-calibration-replay/1", "population": "26 already exposed R3 Qwen candidates",
            "rows": output, "r3_counts": dict(Counter(x["r3"]["decision"] for x in output)),
            "r4_optional_counts": dict(Counter(x["r4_optional"]["decision"] for x in output)),
            "latency_from_original_observations": summarize_latency(comparison["rows"]),
            "model_calls_this_run": 0, "business_deliveries": 0,
            "quality_conclusion": "grammar coverage only; no new naturalness, model or business result"}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frozen", default="data/r3/frozen-comparison.json")
    p.add_argument("--comparison", default="data/r3/comparison.json")
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    target = Path(args.output)
    if target.exists():
        raise ValueError("use a new output path")
    result = replay(json.loads(Path(args.frozen).read_text()), json.loads(Path(args.comparison).read_text()))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"r3_counts": result["r3_counts"], "r4_optional_counts": result["r4_optional_counts"],
                      "model_calls": 0, "output": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
