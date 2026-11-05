"""Immutable inputs, exact denominators, private append-only evidence."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re

SCHEMA = "am-model-lab-manifest/1"
STATUSES = {"completed", "blocked", "not_run", "provider_failed", "timeout",
            "cancelled", "stop_unknown", "invalid", "truncated", "missing"}
KINDS = {"codex_cli", "production_q8", "mlx_base", "mlx_adapter", "cascade"}
HISTORY = {
    "source": "R8 fixed 13c653263e58de81f3cd4ae44269008c4b82e13d",
    "planned": 12, "completed": 11, "stop_unknown_original_record": 1,
    "base_adapter_pairs": 4, "byte_identical_pairs": 4,
    "human_reviews": 0, "facts_guard": "indeterminate",
    "inference": "no_observed_adapter_improvement; not fresh holdout",
    "adapter_sha256": "9a8c9e4e25b19ac23f5b40abf3eeb438189d95fdf68d4b05e34872283879767a",
}


class LabError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def strict_json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise LabError("duplicate_json_key:" + k)
            result[k] = v
        return result
    def bad_constant(value):
        raise LabError("non_finite_json:" + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


def read_json(path):
    return strict_json(Path(path).read_text(encoding="utf-8"))


def seal(value):
    out = deepcopy(value)
    out.pop("sha256", None)
    out["sha256"] = sha(out)
    return out


def check_seal(value):
    if not isinstance(value, dict) or value.get("sha256") != seal(value)["sha256"]:
        raise LabError("object_hash_mismatch")
    return value


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise LabError("symlink_output_directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def write_json(path, value, *, exclusive=True):
    path = Path(path)
    private_dir(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def append_jsonl(path, value):
    path = Path(path)
    private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    import fcntl
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(canonical(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_jsonl(path):
    if not Path(path).is_file():
        return []
    return [strict_json(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def resolve_ref(ref, label="artifact"):
    if not isinstance(ref, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", ""))):
        raise LabError(label + "_content_pin_required")
    path = Path(ref.get("path", ""))
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise LabError(label + "_absolute_existing_regular_file_required")
    if file_sha(path) != ref["sha256"]:
        raise LabError(label + "_changed")
    return path


def measured(value=None, *, unit=None, reason="not_observed", source=None, scope=None):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
        raise LabError("invalid_measurement")
    return {"value": value, "unit": unit, "missing_reason": reason if value is None else None,
            "source": source, "scope": scope}


def empty_measurements(reason="not_observed"):
    return {
        "tokens": {k: measured(unit="tokens", reason=reason) for k in ("input", "output", "cached_input")},
        "resources": {"peak_rss_mib": measured(unit="MiB", reason=reason),
                      "peak_accelerator_mib": measured(unit="MiB", reason=reason),
                      "mlx_reported_peak_memory_GB": measured(unit="GB", reason=reason),
                      "energy_wh": measured(unit="Wh", reason=reason)},
        "cost": {"billed": measured(unit="currency", reason=reason), "currency": None,
                 "billing_basis": None, "subscription_allocation": None},
    }


def freeze_manifest(spec, output_path=None):
    """Freeze all cases, arms, exact messages, pins, routes and planned slots.

    No model or remote I/O. Unavailable runtime artifacts may be declared but
    remain blocked by preflight. A fixture is never upgraded to real evidence.
    """
    m = deepcopy(spec)
    m.pop("sha256", None)
    m["schema"] = SCHEMA
    m.setdefault("mode", "real")
    m.setdefault("created_at", utc())
    m.setdefault("repeats", 1)
    m.setdefault("synthetic_only", True)
    m.setdefault("data_classification", "synthetic")
    m.setdefault("policy", {"stop_on_unknown": True, "production_activation": False})
    m.setdefault("history", HISTORY)
    if m["mode"] not in {"real", "fixture"} or m["synthetic_only"] is not True:
        raise LabError("real_or_fixture_synthetic_only_required")
    if m["data_classification"] != "synthetic":
        raise LabError("original_probe_contract_only_authorizes_synthetic_material; redacted_business_is_not_synthetic")
    if type(m["repeats"]) is not int or not 1 <= m["repeats"] <= 20:
        raise LabError("repeats_must_be_1_to_20")
    if m["policy"].get("stop_on_unknown") is not True or m["policy"].get("production_activation") is not False:
        raise LabError("stop_unknown_and_no_activation_required")
    cases, arms = m.get("cases"), m.get("arms")
    if not isinstance(cases, list) or not cases or not isinstance(arms, dict) or not arms:
        raise LabError("nonempty_cases_and_arms_required")
    seen = set()
    for case in cases:
        ident = case.get("case_id")
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", ident) or ident in seen:
            raise LabError("invalid_or_duplicate_case_id")
        seen.add(ident)
        if case.get("phase") not in {"module", "end_to_end"}:
            raise LabError("explicit_module_or_end_to_end_phase_required")
        if case.get("split") not in {"fixture", "calibration", "regression", "sealed_test"}:
            raise LabError("explicit_split_required")
        if m["mode"] == "real" and case["split"] == "fixture":
            raise LabError("fixture_case_cannot_be_real")
        if case["split"] == "sealed_test":
            if (case.get("public_exposed") is not False or case.get("not_used_for_tuning") is not True
                    or not case.get("independence_evidence")):
                raise LabError("sealed_test_needs_exclusion_and_declaration_evidence")
        if not isinstance(case.get("messages"), list) or not case["messages"]:
            raise LabError("exact_messages_required")
        if not isinstance(case.get("response_schema"), dict):
            raise LabError("response_schema_required")
        if not isinstance(case.get("checks", []), list):
            raise LabError("checks_must_be_array")
        case["facts_sha256"] = sha(case.get("facts", []))
        case["messages_sha256"] = sha(case["messages"])
        case["case_sha256"] = sha({k: v for k, v in case.items() if k != "case_sha256"})
    for name, arm in arms.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name) or arm.get("kind") not in KINDS:
            raise LabError("invalid_arm")
        if not isinstance(arm.get("identity"), dict):
            raise LabError("identity_object_required:" + name)
        if not isinstance(arm.get("settings"), dict):
            raise LabError("generation_settings_required:" + name)
        if arm["kind"] == "cascade":
            route = arm.get("route", {})
            stages = route.get("stages", [])
            if (len(stages) != 2 or stages[0] not in arms or stages[1] not in arms
                    or arms[stages[0]]["kind"] not in {"production_q8", "mlx_base", "mlx_adapter"}
                    or arms[stages[1]]["kind"] != "codex_cli"):
                raise LabError("cascade_requires_qwen_then_codex")
            if route.get("policy") not in {"always_review", "on_guard_failure"}:
                raise LabError("explicit_cascade_policy_required")
            if route.get("max_calls") != 2 or not isinstance(route.get("review_instruction"), str):
                raise LabError("bounded_frozen_cascade_instruction_required")
        arm["identity_sha256"] = sha(arm["identity"])
    # Rotation prevents every arm always benefiting from the same cold/warm order.
    slots = []
    order = sorted(arms)
    for repeat in range(m["repeats"]):
        rotated = order[repeat % len(order):] + order[:repeat % len(order)]
        for arm in rotated:
            for case in cases:
                key = {"case_id": case["case_id"], "arm": arm, "repeat": repeat, "phase": case["phase"]}
                slots.append({**key, "slot_id": sha(key)[:24]})
    m["case_manifest_sha256"] = sha(cases)
    m["planned_slots"] = slots
    m["expected_results"] = len(slots)
    result = seal(m)
    if output_path is not None:
        write_json(output_path, result)
    return result


def validate_manifest(manifest):
    check_seal(manifest)
    if manifest.get("schema") != SCHEMA:
        raise LabError("unsupported_manifest_schema")
    refrozen = freeze_manifest(manifest)
    if refrozen != manifest:
        raise LabError("manifest_derived_bindings_changed")
    return manifest


def make_record(manifest, slot, *, status, output=None, raw=None, timings=None,
                measurements=None, error=None, model_attempted=False, quality=None, stages=None):
    if status not in STATUSES:
        raise LabError("invalid_result_status")
    case = next(c for c in manifest["cases"] if c["case_id"] == slot["case_id"])
    return seal({"schema": "am-model-lab-result/1", **slot,
                 "manifest_sha256": manifest["sha256"], "mode": manifest["mode"],
                 "case_sha256": case["case_sha256"], "facts_sha256": case["facts_sha256"],
                 "messages_sha256": case["messages_sha256"],
                 "identity_sha256": manifest["arms"][slot["arm"]]["identity_sha256"],
                 "status": status, "recorded_at": utc(), "model_attempted": model_attempted,
                 "output": output, "output_sha256": text_sha(output) if output is not None else None,
                 "raw": raw or [], "timings_ms": timings or {},
                 "measurements": measurements or empty_measurements(),
                 "quality": quality or {"schema": "not_run", "checks": [], "fact_guard": "not_run", "errors": []},
                 "error": error, "stages": stages or [], "external_sends": 0,
                 "production_changed": False})


def validate_records(manifest, records, *, verify_raw=True):
    validate_manifest(manifest)
    slots = {s["slot_id"]: s for s in manifest["planned_slots"]}
    cases = {c["case_id"]: c for c in manifest["cases"]}
    seen = set()
    for record in records:
        check_seal(record)
        ident = record.get("slot_id")
        if ident in seen or ident not in slots:
            raise LabError("duplicate_or_unplanned_result")
        seen.add(ident)
        if any(record.get(k) != v for k, v in slots[ident].items()):
            raise LabError("slot_binding_changed")
        if record.get("manifest_sha256") != manifest["sha256"] or record.get("mode") != manifest["mode"]:
            raise LabError("result_manifest_binding_changed")
        case = cases[record["case_id"]]
        if any(record.get(k) != case[k] for k in ("case_sha256", "facts_sha256", "messages_sha256")):
            raise LabError("result_case_binding_changed")
        if record.get("identity_sha256") != manifest["arms"][record["arm"]]["identity_sha256"]:
            raise LabError("result_identity_changed")
        if record.get("status") not in STATUSES or type(record.get("model_attempted")) is not bool:
            raise LabError("invalid_result_state")
        output = record.get("output")
        if record.get("output_sha256") != (text_sha(output) if output is not None else None):
            raise LabError("output_content_changed")
        if record["status"] == "completed" and not isinstance(output, str):
            raise LabError("completed_result_requires_output")
        if manifest["mode"] == "fixture" and record["model_attempted"]:
            raise LabError("fixture_cannot_claim_real_model_attempt")
        if record["status"] == "completed" and not record.get("raw"):
            raise LabError("completed_result_requires_raw_capture")
        for artifact in record.get("raw", []):
            if manifest["mode"] == "real" and artifact.get("role") == "fixture_only":
                raise LabError("fixture_capture_cannot_be_real_evidence")
            if verify_raw:
                resolve_ref(artifact, "raw_capture")
    return records
