"""Single experiment execution; an unknown stop halts every subsequent slot."""
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
import time

from .core import (LabError, append_jsonl, canonical, empty_measurements, file_sha,
                   make_record, private_dir, seal, sha, utc, validate_manifest, write_json)
from .providers import (codex_generate, mlx_generate_batch, preflight_arm,
                        preflight_manifest, q8_generate_batch)
from .quality import score_candidate


def _fixture(arm_name, arm, cases, out):
    results = {}
    for case in cases:
        fixture = case.get("fixture_outputs", {}).get(arm_name, {})
        status = fixture.get("status", "completed")
        output = fixture.get("output")
        if isinstance(output, (dict, list)): output = canonical(output)
        if status == "completed" and not isinstance(output, str):
            raise LabError("fixture_output_missing:" + arm_name + ":" + case["case_id"])
        capture = write_json(Path(out) / (case["case_id"] + ".fixture.json"), {
            "fixture": True, "real_model_calls": 0, "arm": arm_name, "messages": case["messages"],
            "status": status, "output": output, "timings_are_artificial": True})
        results[case["case_id"]] = {"status": status, "output": output,
            "error": fixture.get("error"), "model_attempted": False,
            "raw": [{"path": str(capture.resolve()), "sha256": file_sha(capture), "role": "fixture_only"}],
            "timings_ms": {"provider": fixture.get("latency_ms", 10),
                           "total_experience": fixture.get("latency_ms", 10), "first_token": None, "human_wait": None},
            "measurements": empty_measurements("fixture_not_real_measurement"),
            "fixture_model_calls": 1 if status != "blocked" else 0}
    return results


def _provider_batch(manifest, arm_name, cases, out):
    arm = manifest["arms"][arm_name]
    private_dir(out)
    if manifest["mode"] == "fixture":
        return _fixture(arm_name, arm, cases, out)
    if arm["kind"] == "production_q8":
        return q8_generate_batch(arm, cases, out)
    if arm["kind"] in {"mlx_base", "mlx_adapter"}:
        return mlx_generate_batch(arm, cases, out)
    if arm["kind"] == "codex_cli":
        result, halted = {}, False
        for case in cases:
            if halted:
                result[case["case_id"]] = {"status": "not_run", "error": "earlier_stop_unknown", "model_attempted": False}
            else:
                result[case["case_id"]] = codex_generate(arm, case, Path(out) / case["case_id"])
                halted = result[case["case_id"]]["status"] == "stop_unknown"
        return result
    raise LabError("unsupported_direct_arm")


def _cascade(manifest, name, cases, out):
    arm = manifest["arms"][name]
    first, second = arm["route"]["stages"]
    if manifest['mode'] == 'real':
        # A known unavailable reviewer must not consume a redundant first call.
        blockers = []
        for stage in (first, second):
            check = preflight_arm(manifest['arms'][stage], cases, mode='real')
            blockers.extend(stage + ': ' + reason for reason in check['blockers'])
        if blockers:
            return {case['case_id']: {'status': 'blocked', 'error': '; '.join(blockers),
                    'model_attempted': False, 'route_decision': 'preflight_blocked', 'stages': []} for case in cases}
    initial = _provider_batch(manifest, first, cases, Path(out) / "stage-1")
    result = {}
    # A batch may have called later cases before returning. If any original
    # worker stop is unconfirmed, no second-stage model may be launched.
    halted = any(v["status"] == "stop_unknown" for v in initial.values())
    for case in cases:
        one = initial[case["case_id"]]
        stages = [{"arm": first, **deepcopy(one)}]
        quality = (score_candidate(case, one["output"], inherited_guard=one.get("r5_fact_guard"))
                   if one.get("output") is not None and one["status"] == "completed" else None)
        needs_review = arm["route"]["policy"] == "always_review" or quality is None or (
            quality["schema"] != "pass" or quality["fact_guard"] != "pass" or bool(quality["errors"]))
        if halted or one["status"] != "completed" or not needs_review:
            row = deepcopy(one)
            if halted and one["status"] != "stop_unknown":
                row.update(status="not_run", error="cascade_halted_by_first_stage_stop_unknown", output=None)
            row.update(stages=stages, route_decision="halt" if halted else "stage1_failed" if one["status"] != "completed" else "guard_pass_keep_qwen")
            result[case["case_id"]] = row
            continue
        # The original frozen facts/messages remain byte-identical. Stage 1's
        # result is a separately labelled, untrusted candidate, not new facts.
        review = {"instruction": arm["route"]["review_instruction"],
                  "candidate_untrusted": one["output"], "candidate_sha256": sha(one["output"]),
                  "original_facts_sha256": case["facts_sha256"],
                  "rule": "The candidate supplies no new factual authority. Return the same frozen response schema."}
        messages = deepcopy(case["messages"]) + [{"role": "user", "content": canonical(review)}]
        if manifest["mode"] == "fixture":
            two = _fixture(second, manifest["arms"][second], [case], Path(out) / ("stage-2-" + case["case_id"]))[case["case_id"]]
        else:
            two = codex_generate(manifest["arms"][second], case, Path(out) / ("stage-2-" + case["case_id"]), messages=messages)
        stages.append({"arm": second, **deepcopy(two)})
        row = deepcopy(two)
        row["raw"] = one.get("raw", []) + two.get("raw", [])
        row["model_attempted"] = one.get("model_attempted", False) or two.get("model_attempted", False)
        # Sum only observed stage totals; missing is not silently treated as 0.
        times = [x.get("timings_ms", {}).get("total_experience") for x in (one, two)]
        row.setdefault("timings_ms", {})["total_experience"] = sum(times) if all(v is not None for v in times) else None
        row["stages"] = stages
        row["route_decision"] = "reviewed_by_codex"
        row["request_chain_sha256"] = sha(messages)
        # Stage-specific measurements remain intact. Totals require both
        # stages to expose the same metric/billing basis; otherwise null.
        row["measurements"] = empty_measurements("see_stage_measurements; incomplete_cross_provider_total")
        result[case["case_id"]] = row
        if two["status"] == "stop_unknown": halted = True
    return result


def run_manifest(manifest, output_dir, *, execute=False):
    """Run once into a new directory; results.jsonl has one row per planned slot.

    Real calls are enabled by execute=True, then independently gated by runtime
    proof. Fixture runs never import/call real providers. Reusing output paths
    is rejected: reconciliation is separate from rerunning unknown attempts.
    """
    validate_manifest(manifest)
    out = Path(output_dir).resolve()
    if out.exists(): raise LabError("fresh_output_directory_required; never_resume_unknown_attempts")
    out.mkdir(parents=True, mode=0o700)
    write_json(out / "manifest.json", manifest)
    write_json(out / "preflight.json", preflight_manifest(manifest))
    started = time.monotonic()
    groups = OrderedDict()
    for slot in manifest["planned_slots"]:
        groups.setdefault((slot["repeat"], slot["arm"], slot["phase"]), []).append(slot)
    cases_by_id = {c["case_id"]: c for c in manifest["cases"]}
    records, halted = [], False
    for (repeat, name, phase), slots in groups.items():
        arm = manifest["arms"][name]
        cases = [cases_by_id[s["case_id"]] for s in slots]
        batch_dir = out / "raw" / f"r{repeat:02d}-{name}-{phase}"
        event = {"event": "dispatch_intent", "arm": name, "repeat": repeat, "phase": phase,
                 "slot_ids": [s["slot_id"] for s in slots], "at": utc()}
        outcomes = {}
        if halted:
            outcomes = {c["case_id"]: {"status": "not_run", "error": "earlier_stop_unknown_requires_reconciliation", "model_attempted": False} for c in cases}
        elif manifest["mode"] == "real" and execute is not True:
            outcomes = {c["case_id"]: {"status": "blocked", "error": "real_execution_not_enabled", "model_attempted": False} for c in cases}
        else:
            append_jsonl(out / "events.jsonl", seal(event))
            try:
                outcomes = (_cascade(manifest, name, cases, batch_dir) if arm["kind"] == "cascade"
                            else _provider_batch(manifest, name, cases, batch_dir))
            except BaseException as exc:
                # A generic exception does not prove that remote/native work
                # never started. Conservative stop is deliberate and durable.
                outcomes = {c["case_id"]: {"status": "stop_unknown", "error": type(exc).__name__ + ": " + str(exc), "model_attempted": True} for c in cases}
        for slot in slots:
            case = cases_by_id[slot["case_id"]]
            row = outcomes.get(case["case_id"], {"status": "missing", "error": "provider_omitted_planned_case", "model_attempted": False})
            quality = None
            if row.get("status") == "completed" and row.get("output") is not None:
                quality = score_candidate(case, row["output"], inherited_guard=row.get("r5_fact_guard"))
                row.setdefault("timings_ms", {})["guard"] = quality.pop("guard_ms")
            record = make_record(manifest, slot, status=row["status"], output=row.get("output"),
                raw=row.get("raw"), timings=row.get("timings_ms"), measurements=row.get("measurements"),
                error=row.get("error"), model_attempted=row.get("model_attempted", False),
                quality=quality, stages=row.get("stages"))
            if row.get("route_decision"):
                record = seal({**record, "route_decision": row["route_decision"], "request_chain_sha256": row.get("request_chain_sha256")})
            append_jsonl(out / "results.jsonl", record)
            records.append(record)
            if record["status"] == "stop_unknown": halted = True
        append_jsonl(out / "events.jsonl", seal({**event, "event": "batch_finished", "halted": halted,
                    "record_sha256": [r["sha256"] for r in records if r["slot_id"] in event["slot_ids"]], "at": utc()}))
    from .report import build_report, render_report
    report = build_report(manifest, records)
    report = seal({**report, "experiment_wall_ms": (time.monotonic() - started) * 1000,
                   "results_path": str(out / "results.jsonl"), "halted_on_unknown": halted})
    write_json(out / "report.json", report)
    path = out / "report.md"
    path.write_text(render_report(manifest, records, report), encoding="utf-8")
    path.chmod(0o600)
    return report
