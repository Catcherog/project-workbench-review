"""Failure-inclusive reporting, paired comparisons and non-activating choices."""
from collections import Counter
from itertools import combinations
import math
import statistics

from .core import (LabError, check_seal, seal, sha, validate_manifest, validate_records)


def distribution(values, *, planned=None):
    xs = sorted(v for v in values if type(v) in (int, float) and math.isfinite(v) and v >= 0)
    if not xs:
        return {"n": 0, "missing": planned, "p50": None, "p95": None, "mean": None, "sum": None,
                "missing_reason": "not_observed", "quantile_method": "nearest_rank"}
    return {"n": len(xs), "missing": None if planned is None else planned-len(xs),
            "p50": statistics.median(xs), "p95": xs[math.ceil(.95*len(xs))-1],
            "mean": statistics.mean(xs), "sum": sum(xs), "missing_reason": None,
            "quantile_method": "p50 median; p95 nearest_rank", "p95_small_sample": len(xs) < 20}


def _rate(n, d):
    return {"numerator": n, "denominator": d, "value": n/d if d else None}


def _review_index(reviews, manifest):
    if reviews is None: return {}
    check_seal(reviews)
    if reviews.get("manifest_sha256") != manifest["sha256"] or reviews.get("schema") != "am-model-lab-human-reviews/1":
        raise LabError("human_reviews_manifest_mismatch")
    index = {}
    for row in reviews.get("ratings", []):
        if row.get("rater_type") != "human": raise LabError("only_explicit_human_ratings")
        index.setdefault(row["slot_id"], []).append(row)
    return index


def build_report(manifest, records, reviews=None):
    validate_records(manifest, records)
    index = {r["slot_id"]: r for r in records}
    human = _review_index(reviews, manifest)
    for slot_id, ratings in human.items():
        if slot_id not in index or any(r["record_sha256"] != index[slot_id]["sha256"] for r in ratings):
            raise LabError("human_review_bound_to_different_result")
    by_phase = {}
    planned = manifest["planned_slots"]
    metric_names = ("provider", "provider_plus_cli", "end_to_end", "model_load", "total_experience", "guard", "first_token", "human_wait")
    for phase in sorted({s["phase"] for s in planned}):
        by_phase[phase] = {}
        for name in manifest["arms"]:
            slots = [s for s in planned if s["arm"] == name and s["phase"] == phase]
            rows = [index[s["slot_id"]] for s in slots if s["slot_id"] in index]
            denominator = len(slots)
            statuses = Counter(r["status"] for r in rows)
            statuses["missing"] += denominator-len(rows)
            complete = [r for r in rows if r["status"] == "completed"]
            schema_pass = [r for r in complete if r["quality"]["schema"] == "pass"]
            fact_pass = [r for r in schema_pass if r["quality"]["fact_guard"] == "pass" and not r["quality"]["errors"]]
            fact_unknown = [r for r in complete if r["quality"]["fact_guard"] in {"indeterminate", "not_run"}]
            errors = Counter(e for r in rows for e in r["quality"]["errors"])
            rated_rows = [r for r in rows if r["slot_id"] in human]
            ratings = [v for r in rated_rows for v in human[r["slot_id"]]]
            latency = {k: distribution([r["timings_ms"].get(k) for r in rows], planned=denominator) for k in metric_names}
            completed_latency = {k: distribution([r["timings_ms"].get(k) for r in complete], planned=len(complete)) for k in metric_names}
            tokens = {k: distribution([r["measurements"]["tokens"][k]["value"] for r in rows], planned=denominator)
                      for k in ("input", "output", "cached_input")}
            resources = {k: distribution([r["measurements"]["resources"][k]["value"] for r in rows], planned=denominator)
                         for k in ("peak_rss_mib", "peak_accelerator_mib", "mlx_reported_peak_memory_GB", "energy_wh")}
            billed = [r["measurements"]["cost"] for r in rows]
            currencies = {x["currency"] for x in billed if x["billed"]["value"] is not None}
            cost = {"observed_rows": sum(x["billed"]["value"] is not None for x in billed), "planned_rows": denominator,
                    "total": None, "currency": None, "complete": False, "missing_reason": "incomplete_or_different_billing_basis"}
            if len(currencies) == 1 and None not in currencies and denominator and all(x["billed"]["value"] is not None for x in billed) and len(billed) == denominator:
                cost.update(total=sum(x["billed"]["value"] for x in billed), currency=next(iter(currencies)), complete=True, missing_reason=None)
            by_phase[phase][name] = {"kind": manifest["arms"][name]["kind"], "identity": manifest["arms"][name]["identity"],
                "planned": denominator, "recorded": len(rows), "status_counts": dict(statuses),
                "model_attempted": sum(r["model_attempted"] for r in rows),
                "completed_rate": _rate(len(complete), denominator),
                "schema_pass_rate": _rate(len(schema_pass), denominator),
                "bounded_fact_pass_rate": _rate(len(fact_pass), denominator),
                "fact_indeterminate": len(fact_unknown), "errors": dict(errors),
                "human_reviewed_slots": len(rated_rows), "human_ratings": len(ratings),
                "human_scores": {k: distribution([v[k] for v in ratings], planned=len(ratings))
                                 for k in ("factuality", "usefulness", "style", "action_boundary")},
                "latency_ms_all_observed_attempts": latency,
                "latency_ms_completed_only": completed_latency,
                "tokens": tokens, "resources": resources, "cost": cost,
                "batch_window_ms": [{"repeat": repeat, "duration": next((r["timings_ms"].get("batch_window_total")
                    for r in rows if r["repeat"] == repeat and r["timings_ms"].get("batch_window_total") is not None), None)}
                    for repeat in range(manifest["repeats"])],
                "business_acceptance": "not_measured" if phase == "module" or manifest["mode"] == "fixture" else "requires_native_workflow_and_human_receipts"}
    paired = []
    cases_by_id = {c["case_id"]: c for c in manifest["cases"]}
    for phase in by_phase:
        for left, right in combinations(manifest["arms"], 2):
            left_rows = {(r["case_id"], r["repeat"]): r for r in records if r["arm"] == left and r["phase"] == phase}
            right_rows = {(r["case_id"], r["repeat"]): r for r in records if r["arm"] == right and r["phase"] == phase}
            keys = {(s["case_id"], s["repeat"]) for s in planned if s["arm"] == left and s["phase"] == phase}
            available = [(left_rows[k], right_rows[k]) for k in sorted(keys) if k in left_rows and k in right_rows
                         and left_rows[k]["status"] == right_rows[k]["status"] == "completed"]
            lat_pairs = [(a["timings_ms"].get("total_experience"), b["timings_ms"].get("total_experience")) for a, b in available]
            deltas = [b-a for a,b in lat_pairs if a is not None and b is not None]
            kinds = {manifest["arms"][left]["kind"], manifest["arms"][right]["kind"]}
            attribution = "provider_plus_harness_or_composite; no single-factor causal claim"
            if kinds == {"mlx_base", "mlx_adapter"}:
                a, b = manifest["arms"][left], manifest["arms"][right]
                shared = ("base_revision", "model_manifest_sha256", "tokenizer_sha256")
                matched = all(a["identity"].get(k) is not None and a["identity"].get(k) == b["identity"].get(k) for k in shared) and a["settings"] == b["settings"]
                attribution = "adapter_increment_only_if_runtime_pins_and_all_shared_settings_verified" if matched else "blocked_attribution_shared_runtime_or_settings_differ"
            elif kinds == {"production_q8", "mlx_base"}:
                attribution = "runtime_quantization_and_backend_bundle; not adapter gain"
            elif kinds == {"production_q8", "mlx_adapter"}:
                attribution = "total_runtime_plus_adapter_bundle; not isolated post_training_gain"
            independent = {a["case_id"] for a,b in available if cases_by_id[a["case_id"]]["split"] == "sealed_test"}
            human_pairs, rated_unique_pairs = [], set()
            for a, b in available:
                ar = {r["reviewer_id"]: r for r in human.get(a["slot_id"], [])}
                br = {r["reviewer_id"]: r for r in human.get(b["slot_id"], [])}
                for reviewer in sorted(set(ar) & set(br)):
                    human_pairs.append((ar[reviewer], br[reviewer]))
                    rated_unique_pairs.add((a["case_id"], a["repeat"]))
            wtl = {}
            for dimension in ("factuality", "usefulness", "style", "action_boundary"):
                wtl[dimension] = {"left_wins": sum(a[dimension] > b[dimension] for a,b in human_pairs),
                                  "ties": sum(a[dimension] == b[dimension] for a,b in human_pairs),
                                  "right_wins": sum(a[dimension] < b[dimension] for a,b in human_pairs)}
            paired.append({"phase": phase, "left": left, "right": right, "planned_pairs": len(keys),
                "completed_pairs": len(available), "unique_cases": len({a["case_id"] for a,b in available}),
                "independent_cases": len(independent), "coverage": _rate(len(available), len(keys)),
                "byte_identical_pairs": sum(a["output"] == b["output"] for a,b in available),
                "right_minus_left_total_ms": {"n": len(deltas), "median": statistics.median(deltas) if deltas else None,
                                              "mean": statistics.mean(deltas) if deltas else None},
                "attribution": attribution, "quality_winner": "unknown; independent human ratings and sufficient coverage required",
                "human_paired": {"same_case_repeat_reviewer_pairs": len(human_pairs),
                    "unique_rated_case_repeat_pairs": len(rated_unique_pairs), "planned_case_repeat_pairs": len(keys),
                    "status": "descriptive_paired_ratings" if human_pairs else "unknown_missing_paired_human_reviews",
                    "by_dimension": wtl, "automatic_composite_winner": None},
                "causal_improvement_claim": False})
    all_complete = len(records) == len(planned) and all(r["status"] == "completed" for r in records)
    return seal({"schema": "am-model-lab-report/1", "manifest_sha256": manifest["sha256"],
        "records_sha256": sha(records), "mode": manifest["mode"], "data_classification": "synthetic",
        "result_scope": "fixture_only_no_real_score" if manifest["mode"] == "fixture" else "real_provider_calls_on_frozen_synthetic_material; not a real-business ranking",
        "planned": len(planned), "recorded": len(records), "missing": len(planned)-len(records),
        "real_model_attempt_records": sum(r["model_attempted"] for r in records) if manifest["mode"] == "real" else 0,
        "model_attempted_definition": "client/dispatch attempt; not proof of backend inference count; raw native receipts preserve actual_calls",
        "phases": by_phase, "paired_comparisons": paired,
        "data_complete": all_complete, "human_reviews_sha256": reviews.get("sha256") if reviews else None,
        "human_reviewed_slots": len(human), "history": manifest.get("history", {}),
        "winner": None, "winner_reason": "User chooses after complete independent evidence; fixture or missing data cannot rank real models",
        "production_activation": False, "external_sends": 0,
        "limits": ["Timeouts/blocked/missing remain in planned denominator", "p95 with n<20 is descriptive only",
                   "No zero substitution for unobserved tokens, resources, costs or latency",
                   "Paired completed subset includes coverage and cannot replace the full denominator",
                   "Repeated outputs are not additional independent cases", "R8 four identical pairs do not demonstrate post-training improvement",
                   "Codex stdin contains messages JSON material plus its own host prompt; Qwen native chat does not have token-identical total context",
                   "Codex max-output-token budget is not hard-enforced by this native CLI comparison",
                   "Native generation settings are frozen but differ across Q8/MLX/Codex; only the MLX adapter contrast can isolate tuning"]})


def propose_selection(manifest, report, arm, reason):
    validate_manifest(manifest); check_seal(report)
    if report.get("manifest_sha256") != manifest["sha256"] or arm not in manifest["arms"]:
        raise LabError("selection_not_bound_to_this_manifest")
    if not isinstance(reason, str) or not reason.strip(): raise LabError("selection_reason_required")
    blockers = []
    if report["mode"] != "real": blockers.append("fixture_evidence_cannot_choose_real_winner")
    if not report["data_complete"]: blockers.append("incomplete_or_failed_planned_evidence")
    if not report.get("human_reviewed_slots"): blockers.append("no_independent_human_review")
    for phase, values in report["phases"].items():
        selected = values[arm]
        if selected["fact_indeterminate"]: blockers.append(phase + ":facts_indeterminate")
        if selected["bounded_fact_pass_rate"]["numerator"] != selected["planned"]:
            blockers.append(phase + ":factual_or_schema_contract_not_passed_for_every_planned_case")
    blockers.append("real_business_acceptance_and_explicit_user_activation_not_part_of_this_lab")
    return seal({"schema": "am-model-lab-selection-proposal/1", "manifest_sha256": manifest["sha256"],
        "report_sha256": report["sha256"], "selected_arm": arm, "selected_definition": manifest["arms"][arm],
        "reason": reason, "status": "proposal_requires_evidence_and_user_decision", "blockers": sorted(set(blockers)),
        "route_policy": manifest["arms"][arm].get("route"), "production_activation": False,
        "writes_to_production": 0, "automatic_winner": False})


def render_report(manifest, records, report):
    """Human-readable report with every planned slot, not just successes."""
    validate_records(manifest, records); check_seal(report)
    if report["manifest_sha256"] != manifest["sha256"]: raise LabError("foreign_report")
    def cell(value):
        if value is None: return "未知"
        if isinstance(value, float): return f"{value:.2f}"
        return str(value).replace("|", "\\|").replace("\n", " ")
    fixture = manifest["mode"] == "fixture"
    lines = ["# AM 模型对照报告", "",
        "**本报告是离线 fixture 验证，所有时延均为人工设定，不能用于真实模型排名。**" if fixture else
        "**本报告只覆盖冻结的合成材料。真实 provider 调用与真实业务验收分别统计；缺失结果不代表通过。**", "",
        f"- 计划槽位：{report['planned']}；已记录：{report['recorded']}；缺失：{report['missing']}。",
        f"- 真实模型尝试记录：{report['real_model_attempt_records']}；有人工评分的槽位：{report['human_reviewed_slots']}。",
        "- 最终模型选择：未自动决定。生产启用：关闭。",
        f"- Manifest：`{manifest['sha256']}`", f"- 报告：`{report['sha256']}`", "",
        "## 比较边界", "",
        "所有臂使用同一冻结事实及任务材料。Codex CLI 的 stdin 接收 messages JSON 材料，并保留自身宿主提示、策略与 AGENTS；Qwen 使用原生聊天封装，两者并非同 token 级总上下文。Codex 对照只能评价当前 provider 与 harness 组合。",
        "只有 MLX base 与 adapter 的基础权重、tokenizer、运行时、设置均相同且实际身份通过验证时，才能归因于 adapter。Q8 对 MLX 的差异同时包括后端、量化和运行时。",
        "R8 的四组 base/adapter 逐字相同，事实 guard 为 indeterminate，真人评分为 0，因此没有已观察到的后训练改进，也不能再视作新盲测。", ""]
    for phase, arms in report["phases"].items():
        lines.extend(["## " + ("模块级结果" if phase == "module" else "端到端结果"), "",
            "| 方案 | 计划 | 完成 | Schema 通过 | 有界事实通过 | 事实未知 | 人评槽位 | provider/CLI p50 / p95 ms | 调用总体验 p50 / p95 ms |",
            "|---|---:|---:|---:|---:|---:|---:|---|---|"])
        for name, value in arms.items():
            latency = value["latency_ms_all_observed_attempts"]
            provider = latency["provider"] if latency["provider"]["n"] else latency["provider_plus_cli"]
            total = latency["total_experience"]
            vals = [name, value["planned"], value["completed_rate"]["numerator"], value["schema_pass_rate"]["numerator"],
                    value["bounded_fact_pass_rate"]["numerator"], value["fact_indeterminate"], value["human_reviewed_slots"],
                    cell(provider["p50"]) + " / " + cell(provider["p95"]), cell(total["p50"]) + " / " + cell(total["p95"])]
            lines.append("| " + " | ".join(cell(v) for v in vals) + " |")
        lines.extend(["", "所有通过率分母均为计划槽位。模块级调用总体验是客户端/探针已观察时段，不等于飞书手机端的完整业务体验。MLX 卸载、恢复等批次窗口耗时单列，不能藏入单次生成速度。p95 在少于 20 次时仅供描述。", "",
                      "### 失败、缺失与资源", ""])
        for name, value in arms.items():
            lines.append(f"- **{name}**：状态 `{value['status_counts']}`；错误 `{value['errors']}`；输入/输出 token 观测 {value['tokens']['input']['n']}/{value['tokens']['output']['n']}；成本总额 {cell(value['cost']['total'])}；峰值 RSS 观测 {value['resources']['peak_rss_mib']['n']}。")
        lines.append("")
    lines.extend(["## 配对比较与匿名真人评分", "",
        "| 阶段 | 左 / 右 | 完成配对 / 计划 | 相同输出 | 同人配对评分数 | 实用性 左胜 / 平 / 右胜 | 归因范围 |",
        "|---|---|---:|---:|---:|---|---|"])
    for pair in report["paired_comparisons"]:
        human = pair["human_paired"]; score = human["by_dimension"]["usefulness"]
        wtl = f"{score['left_wins']} / {score['ties']} / {score['right_wins']}" if human["same_case_repeat_reviewer_pairs"] else "未知：缺少共同评分人"
        lines.append("| " + " | ".join(cell(x) for x in [pair["phase"], pair["left"] + " / " + pair["right"],
            f"{pair['completed_pairs']} / {pair['planned_pairs']}", pair["byte_identical_pairs"], human["same_case_repeat_reviewer_pairs"], wtl, pair["attribution"]]) + " |")
    lines.extend(["", "评分只配对同 case、同 repeat、同 reviewer 的两份输出；未评分仍为未知。其余分项胜/平/负与原始分数在 report.json / 导入的人评文件中保留，不自动加权成一个赢家。", "",
                  "## 每个计划槽位", ""])
    index = {r["slot_id"]: r for r in records}
    for slot in manifest["planned_slots"]:
        row = index.get(slot["slot_id"])
        lines.extend([f"### {slot['case_id']} · {slot['arm']} · repeat {slot['repeat']} · {slot['phase']}", ""])
        if row is None:
            lines.extend(["状态：missing。仍保留在分母。", ""]); continue
        lines.extend([f"状态：**{row['status']}**；Schema：{row['quality']['schema']}；事实：{row['quality']['fact_guard']}。",
                      f"错误：`{cell(row.get('error'))}`；记录 SHA：`{row['sha256']}`。", ""])
        if row.get("output") is not None:
            output = row["output"]
            fence = "`" * (max([len(part) for part in __import__('re').findall(r'`+', output)] or [2])+1)
            lines.extend([fence + "text", output[:4000], fence, ""])
            if len(output) > 4000: lines.extend(["预览截断；完整输出保存在 results.jsonl 和原始捕获中。", ""])
        if row.get("stages"):
            lines.extend(["组合各阶段：" + "；".join(f"{s['arm']}: {s['status']}" for s in row["stages"]), ""])
        for raw in row.get("raw", []):
            lines.append(f"- 原始文件 `{raw['path']}` · SHA `{raw['sha256']}`")
        lines.append("")
    return "\n".join(lines)
