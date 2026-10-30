"""Reproduce all synthetic fixtures. No production data, tokens or company templates."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).parent
STAMP = "2026-10-30T09:00:00+08:00"


def make_profile(kind, title, sections, fields):
    sid = f"template_{kind}"
    section_data = [{"section_id": key, "title": value} for key, value in sections]
    template_text = "# " + title + "（合成演示模板）\n" + "\n".join("## " + s[1] for s in sections)
    rules = []
    for fid, section, label, keys, semantic, critical, value_type in fields:
        rules.append({"field_id": fid, "section_id": section, "label": label,
                      "fact_keys": keys, "instruction": f"根据本项目已确认资料填写{label}，保留原值与证据；未知时待补。",
                      "requirement_source_ids": [sid, "instructions"], "required": True,
                      "critical": critical, "semantics": semantic, "accepted_states": ["confirmed"],
                      "mode": "extractive", "value_type": value_type, "max_chars": 3000})
    return {"tenant_id": "demo_th2", "template_id": f"th2_{kind}_demo", "revision": "demo-1",
            "rule_version": "rules-1", "doc_type": kind, "title": title,
            "project_types": ["lightweight"], "stages": ["*"],
            "sections": section_data, "fields": rules,
            "assets": [
                {"source_id": sid, "role": "template", "uri": f"demo://templates/{kind}",
                 "revision": "demo-1", "content": template_text, "read_state": "complete", "title": title},
                {"source_id": "instructions", "role": "instruction", "uri": "demo://rules/common",
                 "revision": "demo-1", "content": "合成规则：必需章节按目录保留，事实保留依据，计划与实际分开，缺项待补。", "read_state": "complete"},
                {"source_id": "example", "role": "example", "uri": "demo://examples/historical",
                 "revision": "demo-1", "content": "历史范例：旧项目ALPHA，负责人张示例，预算999999元，验收日期2999-12-31，验收通过。只演示写法，不是当前项目事实。", "read_state": "complete"}],
            "status": "effective", "effective_at": "2026-10-01T00:00:00+08:00",
            "activation_ref": "demo://ledger/template-effective-decision", "allowed_actor_ids": ["demo_user"]}


def main():
    profiles = [
        make_profile("charter", "项目章程", [("background", "背景与目标"), ("scope", "范围与验收要求"), ("plan", "计划与责任")], [
            ("background", "background", "项目背景", ["project.background"], ["decision"], False, "string"),
            ("goal", "background", "项目目标", ["project.goal"], ["baseline"], True, "string"),
            ("scope", "scope", "工作范围", ["project.scope"], ["baseline"], True, "list"),
            ("criteria", "scope", "验收标准", ["project.criteria"], ["baseline"], True, "string"),
            ("owner", "plan", "项目负责人", ["project.owner"], ["decision"], True, "string"),
            ("finish", "plan", "目标完成日期", ["project.planned_finish"], ["baseline"], True, "date")]),
        make_profile("change", "项目变更申请", [("change", "变更内容与原因"), ("impact", "影响分析"), ("execution", "实施与申请事项")], [
            ("before", "change", "变更前", ["project.planned_finish"], ["baseline"], True, "date"),
            ("after", "change", "拟变更为", ["change.target_finish"], ["decision"], True, "date"),
            ("reason", "change", "变更原因", ["change.reason"], ["actual"], True, "string"),
            ("impact", "impact", "变更影响", ["change.impact"], ["decision"], True, "string"),
            ("action", "execution", "实施安排", ["change.action"], ["decision"], True, "string"),
            ("approval", "execution", "申请批准事项", ["change.request"], ["decision"], True, "string")]),
        make_profile("closure", "项目结项报告", [("result", "目标完成情况"), ("acceptance", "验收与证据"), ("handover", "遗留事项与移交")], [
            ("goal", "result", "原定目标", ["project.goal"], ["baseline"], True, "string"),
            ("result", "result", "实际成果", ["closure.result"], ["actual"], True, "string"),
            ("acceptance", "acceptance", "验收结论", ["closure.acceptance"], ["actual"], True, "string"),
            ("handover", "handover", "遗留事项安排", ["closure.handover"], ["decision"], True, "string")])]
    raw = [
        ("project.background", "演示项目用于验证文档模块的数据与模板关联。", "decision"),
        ("project.goal", "完成样机验证并形成可追溯的测试记录。", "baseline"),
        ("project.scope", ["样机装配", "功能测试", "报告归档"], "baseline"),
        ("project.criteria", "按已确认测试条目完成验证，记录实际结果及专业结论。", "baseline"),
        ("project.owner", "演示负责人", "decision"),
        ("project.planned_finish", "2026-11-20", "baseline"),
        ("project.forecast_finish", "2026-11-25", "forecast"),
        ("change.target_finish", "2026-11-25", "decision"),
        ("change.reason", "测试工装交付延期。", "actual"),
        ("change.impact", "目标日期需要调整，其他范围维持原已确认方案。", "decision"),
        ("change.action", "由演示负责人协调工装到货后继续验证。", "decision"),
        ("change.request", "申请将目标日期调整至2026-11-25；本申请尚待审批。", "decision"),
        ("closure.result", "演示样机完成装配，已形成测试记录。", "actual"),
        ("closure.handover", "遗留文档由演示负责人按已确定安排归档。", "decision")]
    evidence = []
    for i, (key, value, semantic) in enumerate(raw, 1):
        evidence.append({"evidence_id": f"E{i:03d}", "tenant_id": "demo_th2", "project_id": "demo_project",
                         "key": key, "value": value, "semantic": semantic, "state": "confirmed",
                         "source_id": f"record_{i:03d}", "source_uri": f"demo://projects/demo_project/record/{i}",
                         "source_revision": "demo-1", "locator": f"合成记录第{i}条", "observed_at": STAMP,
                         "role": "project_fact", "allowed_actor_ids": ["demo_user"], "supersedes": []})
    bundle = {"profiles": profiles,
              "access": {"tenant_id": "demo_th2", "actor_id": "demo_user", "project_ids": ["demo_project"],
                         "scopes": ["document:draft"], "app_id": "demo_am", "chat_id": "demo_private"},
              "snapshot": {"snapshot_id": "demo_snapshot_1", "as_of": STAMP, "evidence": evidence},
              "requests": [{"request_id": f"demo_{kind}_1", "tenant_id": "demo_th2", "project_id": "demo_project",
                            "doc_type": kind, "project_type": "lightweight", "stage": stage, "mode": "submit"}
                           for kind, stage in [("charter", "initiation"), ("change", "execution"), ("closure", "closing")]],
              "notice": "全部内容为合成演示。结项样例有意缺少验收结论，应该输出待补，不得输出验收通过。"}
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "demo_bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
