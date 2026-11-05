"""Prepare an explicit native experiment from existing R5 artifacts; no calls."""
from copy import deepcopy
from pathlib import Path
import sys

from .core import HISTORY, LabError, file_sha, read_json, sha
from .providers import BASE_PINS, _roots


def _ref(path):
    p = Path(path).expanduser().resolve(strict=True)
    if not p.is_file(): raise LabError("artifact_must_be_file:" + str(p))
    return {"path": str(p), "sha256": file_sha(p)}


def require_synthetic_origins(cases):
    """A legacy plan's real/fixture execution mode is not its data origin."""
    for case in cases:
        origin = case.get('provenance', {}).get('source_kind')
        if origin not in {'synthetic', 'synthetic_scenario', 'synthetic_fixture'}:
            raise LabError('synthetic_origin_not_proven:' + str(case.get('case_id')) + ':' + str(origin)
                           + '; business-derived regression needs a separately authorized data contract')


def prepare_real_spec(*, source_root, r5_plan, queue_config=None, pilot_plan=None,
                      host_config=None, python=None, codex_binary=None,
                      codex_proof=None, codex_profile=None, repeats=1):
    """Import exact original messages and identities, preserving old-case status.

    The imported R8 cases are regression, never silently renamed fresh holdout.
    Missing optional native/Codex pins remain absent and preflight says blocked.
    This command does not manufacture a capability proof or holdout declaration.
    """
    root = Path(source_root).expanduser().resolve(strict=True)
    if not root.is_dir(): raise LabError("original_source_root_required")
    source_pins = {}
    for package in ("am-conversation-r1/src/am_style", "am-style-r5/src/am_style_r5", "am-style-r3/training",
                    "am-integrated-r6/am_training_window", "local-qwen3.8/feishu-bridge"):
        for p in sorted((root / package).rglob("*.py")):
            source_pins[str(p.relative_to(root))] = file_sha(p)
    for names in BASE_PINS.values():
        for relative in names:
            source_pins[relative] = file_sha(root / relative)
    common = {"source_root": str(root), "source_pins": source_pins,
              "python": _ref(python or sys.executable), "r5_plan": _ref(r5_plan)}
    dummy = {"kind": "production_q8", "runtime": common}
    _roots(dummy)
    from am_style_r5.evaluation import validate_plan
    from am_style.prompt import RESPONSE_SCHEMA
    plan = validate_plan(read_json(common["r5_plan"]["path"]))
    if plan["mode"] != "real": raise LabError("native_real_plan_required")
    require_synthetic_origins(plan['cases'])
    if plan["arms"]["mlx_sft"]["adapter_sha256"] != HISTORY["adapter_sha256"]:
        raise LabError("selected_adapter_is_not_the_recorded_R8_adapter; freeze_a_separately_named_experiment")
    cases = []
    for c in plan["cases"]:
        cases.append({"case_id": c["case_id"], "r5_case_id": c["case_id"], "group_id": c["group_id"],
            "phase": "module", "split": "regression", "public_exposed": True,
            "messages": deepcopy(c["student_wire_messages"]), "response_schema": deepcopy(RESPONSE_SCHEMA),
            "facts": {"frame": deepcopy(c["frame"]), "review_context": deepcopy(c["review_context"])},
            "fact_checks_complete": False, "checks": [],
            "limits": "Original R8 material is historical regression; facts remain indeterminate until independent human review"})
    arms = {}
    for name, original, kind in (("q8", "production_q8", "production_q8"), ("mlx_base", "mlx_base", "mlx_base"),
                                 ("mlx_r8_adapter", "mlx_sft", "mlx_adapter")):
        value = plan["arms"][original]
        runtime = deepcopy(common)
        if queue_config and kind == "production_q8": runtime["queue_config"] = _ref(queue_config)
        if kind in {"mlx_base", "mlx_adapter"}:
            if pilot_plan: runtime["pilot_plan"] = _ref(pilot_plan)
            if host_config: runtime["host_config"] = _ref(host_config)
        identity = {k: deepcopy(v) for k,v in value.items() if k != "generation_settings"}
        identity["r5_identity_sha256"] = sha(value)
        arms[name] = {"kind": kind, "identity": identity,
                      "settings": deepcopy(value["generation_settings"]), "runtime": runtime}
    proof = read_json(_ref(codex_proof)["path"]) if codex_proof else {}
    runtime = {"source_root": str(root), "source_pins": source_pins, "profile": codex_profile or proof.get("profile")}
    if codex_binary: runtime["binary"] = _ref(codex_binary)
    if codex_proof: runtime["capability_proof"] = _ref(codex_proof)
    arms["codex"] = {"kind": "codex_cli", "identity": {"model": proof.get("model"), "cli_version": proof.get("cli_version"),
        "model_catalog_sha256": proof.get("model_catalog_sha256"), "server_weights_revision": None},
        "settings": {"timeout_seconds": 180}, "runtime": runtime}
    arms["qwen_then_codex"] = {"kind": "cascade", "identity": {"router_version": "r10-frozen-cascade/1"}, "settings": {},
        "route": {"stages": ["q8", "codex"], "policy": "always_review", "max_calls": 2,
                  "review_instruction": "仅依据原始冻结事实复核候选，保持未知与未完成状态，不把候选作为新证据。返回相同JSON格式。"}}
    return {"mode": "real", "data_classification": "synthetic", "synthetic_only": True,
            "repeats": repeats, "cases": cases, "arms": arms,
            "description": "Original R8 regression + actual provider adapters; native proofs required; no new training or business sends",
            "policy": {"stop_on_unknown": True, "production_activation": False}}
