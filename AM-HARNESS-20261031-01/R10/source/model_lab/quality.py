"""Deterministic, explicitly bounded checks; no invented semantic ratings."""
import time

from .core import LabError, strict_json

ERROR_CLASSES = {"schema_invalid", "fabricated_fact", "source_mismatch", "false_completion",
                 "action_boundary", "missing_obligation", "style_contract", "unknown_check"}


def _at(value, path):
    if not isinstance(path, list):
        raise LabError("json_path_must_be_explicit_array")
    for part in path:
        value = value[part]
    return value


def score_candidate(case, output, *, inherited_guard=None):
    """Score only frozen predicates. Full factual quality remains human-reviewed.

    fact_checks_complete is an explicit *bounded* contract, not a claim that a
    keyword checker understands arbitrary factual truth. An indeterminate
    original R5 fact guard is retained even when these local predicates pass.
    """
    started = time.monotonic()
    result = {"schema": "not_run", "checks": [], "fact_guard": "indeterminate", "errors": [],
              "semantic_quality": "not_human_reviewed", "scope": "frozen_bounded_predicates"}
    try:
        parsed = strict_json(output)
        import jsonschema
        jsonschema.Draft202012Validator.check_schema(case["response_schema"])
        jsonschema.Draft202012Validator(case["response_schema"]).validate(parsed)
        result["schema"] = "pass"
    except ImportError:
        result.update(schema="indeterminate", errors=["schema_validator_unavailable"])
        result["guard_ms"] = (time.monotonic() - started) * 1000
        return result
    except Exception as exc:
        result.update(schema="fail", errors=["schema_invalid"], schema_error=type(exc).__name__)
        result["guard_ms"] = (time.monotonic() - started) * 1000
        return result
    fact_checks = []
    for index, check in enumerate(case.get("checks", [])):
        category = check.get("error_class", "unknown_check")
        if category not in ERROR_CLASSES:
            raise LabError("unregistered_error_class:" + category)
        decision, reason = "indeterminate", None
        try:
            kind = check["kind"]
            if kind == "json_equals":
                passed = _at(parsed, check["path"]) == check["expected"]
            elif kind == "json_subset":
                value = _at(parsed, check["path"])
                if not isinstance(value, list): raise LabError("expected_array")
                passed = set(value) <= set(check["allowed"])
            elif kind == "json_contains":
                passed = check["expected"] in _at(parsed, check["path"])
            elif kind == "text_contains":
                passed = check["text"] in output
            elif kind == "text_excludes":
                passed = check["text"] not in output
            else:
                raise LabError("unsupported_frozen_predicate")
            decision = "pass" if passed else "fail"
        except (KeyError, TypeError, IndexError):
            decision, reason = "fail", "required_output_path_missing_or_wrong_type"
        except LabError as exc:
            reason = str(exc)
        record = {"check_id": check.get("id", str(index)), "decision": decision,
                  "error_class": category, "reason": reason}
        result["checks"].append(record)
        if decision == "fail": result["errors"].append(category)
        if check.get("domain", "fact") == "fact": fact_checks.append(decision)
    if "fail" in fact_checks:
        result["fact_guard"] = "fail"
    elif fact_checks and all(x == "pass" for x in fact_checks) and case.get("fact_checks_complete") is True:
        result["fact_guard"] = "pass"
    if inherited_guard:
        result["original_guard"] = inherited_guard
        original = inherited_guard.get("decision")
        if original in {"reject", "fail"}:
            result["fact_guard"] = "fail"
        elif original != "pass" and result["fact_guard"] == "pass":
            result["fact_guard"] = "indeterminate"
    result["errors"] = sorted(set(result["errors"]))
    result["guard_ms"] = (time.monotonic() - started) * 1000
    return result
