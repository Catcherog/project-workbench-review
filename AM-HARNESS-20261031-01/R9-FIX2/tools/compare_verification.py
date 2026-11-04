#!/usr/bin/env python3
"""Compare two offline reports without treating known failures as full success."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def cases(report):
    grouped = {}
    for item in report["records"]:
        grouped.setdefault(item["nodeid"], []).append(item)
    result = {}
    for nodeid, stages in grouped.items():
        if any(s["outcome"] == "failed" for s in stages):
            result[nodeid] = "failed"
        elif any(s["outcome"] == "skipped" for s in stages):
            result[nodeid] = "skipped"
        elif any(s["phase"] == "call" and s["outcome"] == "passed" for s in stages):
            result[nodeid] = "passed"
        else:
            result[nodeid] = "incomplete"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    before = json.loads(args.baseline.read_text())
    after = json.loads(args.candidate.read_text())
    if before["schema"] != "am-offline-verification/1" or after["schema"] != before["schema"]:
        raise ValueError("incompatible reports")
    bc, ac = cases(before), cases(after)
    bf = {(x["nodeid"], x["phase"]): x for x in before["failures"]}
    af = {(x["nodeid"], x["phase"]): x for x in after["failures"]}
    added = sorted(set(ac) - set(bc))
    removed = sorted(set(bc) - set(ac))
    new_failures = [af[k] for k in sorted(set(af) - set(bf))]
    changed_errors = [{"nodeid": k[0], "phase": k[1],
        "before": bf[k].get("message"), "after": af[k].get("message")}
        for k in sorted(set(bf) & set(af))
        if bf[k].get("message") != af[k].get("message")]
    changed_outcomes = [{"nodeid": k, "before": bc[k], "after": ac[k]}
        for k in sorted(set(bc) & set(ac)) if bc[k] != ac[k]]
    new_nonpassing = [{"nodeid": k, "outcome": ac[k]} for k in added if ac[k] != "passed"]
    regressions = [x for x in changed_outcomes if x["before"] == "passed" and x["after"] != "passed"]
    source_stable = after.get("source_unchanged_during_run") is True
    delta_ok = not (new_failures or removed or new_nonpassing or regressions or
        after.get("collection_errors") or not source_stable)
    report = {
        "schema": "am-offline-verification-delta/1",
        "baseline_report": str(args.baseline), "candidate_report": str(args.candidate),
        "baseline_counts": dict(Counter(bc.values())),
        "candidate_counts": dict(Counter(ac.values())),
        "baseline_exit_code": before["exit_code"], "candidate_exit_code": after["exit_code"],
        "new_case_count": len(added), "new_case_outcomes": dict(Counter(ac[k] for k in added)),
        "new_cases": added, "removed_cases": removed,
        "new_failures": new_failures,
        "resolved_failures": [bf[k] for k in sorted(set(bf) - set(af))],
        "common_failure_count": len(set(bf) & set(af)),
        "changed_failure_messages": changed_errors,
        "changed_existing_outcomes": changed_outcomes,
        "candidate_collection_errors": after.get("collection_errors", []),
        "candidate_source_stable": source_stable,
        "delta_gate_passed": delta_ok,
        "full_suite_passed": after["exit_code"] == 0 and not af,
        "note": "A passing delta gate is not a passing full suite; changed messages require review."
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("baseline_counts", "candidate_counts",
        "new_case_count", "new_case_outcomes", "common_failure_count",
        "candidate_source_stable", "delta_gate_passed", "full_suite_passed")}, ensure_ascii=False))
    print(json.dumps({"new_failures": len(new_failures), "removed_cases": len(removed),
        "changed_failure_messages": len(changed_errors), "report": str(args.out)}))
    return 0 if delta_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
