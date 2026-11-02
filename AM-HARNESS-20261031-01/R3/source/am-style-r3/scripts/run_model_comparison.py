#!/usr/bin/env python3
"""Sequential synthetic expression comparison; never sends a business message.

Input JSONL: {"case_id": ..., "synthetic": true, "frame": {...}}.
All model arms receive the same frozen frame, policy and canonical messages.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "am-conversation-r1/src"))

from am_style.contracts import ModelRequest, SpeechFrame, StylePolicy, canonical, digest
from am_style.evaluation import summarize
from am_style.prompt import build_messages
from am_style.providers import CodexCLIProvider, OllamaHTTPProvider
from am_style.render import render_canonical
from am_style.runtime import ModelUnavailable, StopUnconfirmed
from am_style.verify import BoundedVerifier, parse_candidate


def provider_from_config(item):
    kind = item.get("kind")
    kwargs = {k: v for k, v in item.items() if k not in {"kind", "name", "enabled"}}
    if kind == "ollama_isolated":
        return OllamaHTTPProvider(**kwargs)
    if kind == "codex_cli":
        proof_path = kwargs.pop("capability_proof_file", None)
        if not proof_path:
            raise ModelUnavailable("capability_proof_file_required")
        kwargs["capability_proof"] = json.loads(Path(proof_path).read_text(encoding="utf-8"))
        return CodexCLIProvider(**kwargs)
    raise ModelUnavailable("comparison_does_not_construct_a_production_coordinator")


def run_comparison(cases, arms, *, policy=None, budget=20, provider_factory=provider_from_config):
    policy = policy or StylePolicy(realization="free")
    # Freeze the denominator and validate all inputs before any provider can run.
    cases = json.loads(canonical(cases))
    active = [item for item in json.loads(canonical(arms)) if item.get("enabled") is True]
    expected_cases = [case.get("case_id") for case in cases]
    active_arms = ["host_canonical"] + [item.get("name") for item in active]
    if (any(not x for x in expected_cases + active_arms)
            or len(set(expected_cases)) != len(expected_cases) or len(set(active_arms)) != len(active_arms)):
        raise ValueError("unique_cases_and_active_arms_required")
    prepared = []
    for case in cases:
        if case.get("synthetic") is not True:
            raise ValueError("comparison_requires_labeled_synthetic_cases")
        frame = SpeechFrame.freeze(case["frame"])
        messages = build_messages(frame, policy)
        request = ModelRequest(canonical(messages), frame.fingerprint, digest(policy.as_dict()), budget)
        prepared.append((case, frame, messages, request))
    rows = []
    stopped = False
    stop_trigger = None
    for case, frame, messages, request in prepared:
        common = {"case_id": case["case_id"], "frame_sha256": frame.fingerprint,
                  "prompt_sha256": digest(messages), "policy_sha256": digest(policy.as_dict()),
                  "eligible": True, "attempted": False, "schema_pass": False, "semantic_pass": False,
                  "adopted": False, "candidate_text": None, "duration_ms": None,
                  "naturalness": "not_scored", "facts_human_review": "pending", "human_review": None,
                  "delivered": False, "delivery_receipt": None, "delivery": "none"}
        baseline = render_canonical(frame)
        baseline_verdict = BoundedVerifier().verify(frame, baseline, policy)
        rows.append({**common, "arm": "host_canonical", "status": "deterministic",
                     "raw_text": canonical({"text": baseline}), "candidate_text": baseline,
                     "schema_pass": True, "semantic_pass": baseline_verdict.decision == "pass",
                     "bounded_decision": baseline_verdict.decision, "bounded_reason": baseline_verdict.reason,
                     "origin": "deterministic_host"})
        for arm in active:
            row = {**common, "arm": arm["name"]}
            if stopped:
                # Record every frozen case/arm combination without constructing
                # another provider or consuming a model lane.
                rows.append({**row, "status": "skipped_stop_unconfirmed", "stop_trigger": stop_trigger,
                             "bounded_decision": "not_checked", "bounded_reason": "not_attempted"})
                continue
            start = time.monotonic()
            provider = None
            call_entered = False
            try:
                provider = provider_factory(arm)
                call_entered = True
                result = provider.generate(request)
                candidate = parse_candidate(result.text)
                row.update(status="completed", raw_text=result.text, provider=result.provider, model=result.model,
                           model_ms=result.duration_ms, duration_ms=result.duration_ms,
                           metadata=json.loads(result.metadata_json), schema_pass=candidate is not None,
                           candidate_text=candidate, attempted=True)
                if candidate is not None:
                    verdict = BoundedVerifier().verify(frame, candidate, policy)
                    row.update(bounded_decision=verdict.decision, bounded_reason=verdict.reason,
                               semantic_pass=verdict.decision == "pass")
                else:
                    row.update(bounded_decision="not_checked", bounded_reason="invalid_schema")
            except StopUnconfirmed as exc:
                row.update(status="stop_unconfirmed", error=str(exc), metadata=getattr(exc, "metadata", {}))
                stopped = True
                stop_trigger = {"case_id": case["case_id"], "arm": arm["name"], "reason": str(exc)}
            except (ModelUnavailable, OSError, ValueError, TypeError) as exc:
                row.update(status="unavailable", error=str(exc), metadata=getattr(exc, "metadata", {}))
            row["wall_ms"] = (time.monotonic() - start) * 1000
            # Provider preflight failures do not become fictitious model calls.
            # Injected providers without this optional marker use entry into
            # generate as the conservative attempt boundary.
            row["attempted"] = bool(getattr(provider, "last_model_attempted", call_entered))
            if row["attempted"] and row["duration_ms"] is None:
                row["duration_ms"] = row["wall_ms"]
            rows.append(row)
    return {"schema": "am-expression-comparison/1", "stopped_for_reconciliation": stopped,
            "expected_cases": expected_cases, "active_arms": active_arms,
            "policy": policy.as_dict(), "rows": rows, "business_delivery": False,
            "summary": summarize(rows, expected_cases=expected_cases, arms=active_arms),
            "quality_conclusion": "not_evaluated; requires blind human review"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--providers", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--budget", type=float, default=20)
    parser.add_argument("--execute", action="store_true", help="Run only explicitly enabled isolated arms")
    args = parser.parse_args(argv)
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding="utf-8").splitlines() if line.strip()]
    config = json.loads(Path(args.providers).read_text(encoding="utf-8"))
    policy = StylePolicy(**json.loads(Path(args.policy).read_text(encoding="utf-8"))) if args.policy else StylePolicy(realization="free")
    arms = config.get("arms", [])
    names = [a.get("name") for a in arms]
    if any(not n for n in names) or len(set(names)) != len(names):
        raise ValueError("unique_arm_names_required")
    if not args.execute:
        arms = [{**a, "enabled": False} for a in arms]
    output = Path(args.output)
    if output.exists():
        raise ValueError("use_new_output_path_to_preserve_prior_results")
    result = run_comparison(cases, arms, policy=policy, budget=args.budget)
    result["execute_requested"] = args.execute
    result["configured_arms"] = names
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(result["rows"]), "execute_requested": args.execute,
                      "completed_model_calls": sum(r.get("status") == "completed" for r in result["rows"]),
                      "stop_unconfirmed": result["stopped_for_reconciliation"], "output": str(output)}, ensure_ascii=False))
    return 2 if result["stopped_for_reconciliation"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
