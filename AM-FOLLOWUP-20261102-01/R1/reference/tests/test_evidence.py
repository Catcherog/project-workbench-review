"""Synthetic semantic and persistence regressions; no live Lark or LLM use."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from am_followup.evidence import (
    ConcurrentUpdate, CoverageKey, EvidenceError, EvidenceLedger, EvidenceSnapshot,
    FactProposal, QuoteSpan, ReadResult, SourceEvidence, TaskSeed, display_time,
)


T = "2026-11-02T10:00:00+08:00"
T1 = "2026-11-02T10:01:00+08:00"
T2 = "2026-11-02T10:02:00+08:00"


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "evidence.sqlite3")
        self.ledger = EvidenceLedger(self.path, "tenant_demo")
        self.counter = 0
        self.seed = self.source("请跟进项目A测试，负责人为工程师A。", "seed")
        self.ledger.ingest(self.seed)
        self.create_task()

    def source(self, text, native_id=None, **overrides):
        self.counter += 1
        values = dict(tenant_id="tenant_demo", namespace="synthetic_lark", source_type="message",
                      scope_id="demo_chat", native_id=native_id or f"msg_{self.counter}", version="v1",
                      text=text, event_time=T, observed_at=T, acl_version="acl1",
                      audience_keys=("chat:demo_chat", "person:engineer_a", "person:owner"),
                      version_seq=1)
        values.update(overrides)
        return SourceEvidence(**values)

    def create_task(self, task_id="task_a", **overrides):
        args = dict(task_id=task_id, canonical_key=f"demo_project:{task_id}:test", action="确认是否已开测",
                    evidence_refs=(self.seed.ref,), project_id="project_a", owner_id="engineer_a",
                    origin="user_direct", business_timezone="Asia/Shanghai")
        args.update(overrides)
        return self.ledger.create_task(TaskSeed(**args))

    def proposal(self, field, value, *, task_id="task_a", source=None, supersedes=(), response_to=None, subject_key=None):
        source = source or self.source(f"已核实字段 {field} = {value}")
        self.ledger.ingest(source)
        span = QuoteSpan(source.ref, 0, len(source.text), source.text)
        proposal = FactProposal(task_id, field, value, (span,), T, tuple(supersedes), response_to=response_to, subject_key=subject_key)
        return self.ledger.propose(proposal)

    def accept(self, field, value, **kwargs):
        task_id = kwargs.get("task_id", "task_a")
        claim_id = self.proposal(field, value, **kwargs)
        version = self.ledger.task_view(task_id)["version"]
        self.ledger.accept_claim(claim_id, "trusted_fixture_reviewer", version, reviewed_at=T1)
        return claim_id

    def test_duplicate_reread_does_not_change_source_version(self):
        view = self.ledger.task_view("task_a")
        result = self.ledger.ingest(replace(self.seed, observed_at=T1))
        self.assertEqual(result.status, "duplicate")
        self.assertEqual(self.ledger.task_view("task_a")["version"], view["version"])

    def test_same_text_different_native_message_is_not_deduplicated(self):
        second = replace(self.seed, native_id="another_message")
        self.assertEqual(self.ledger.ingest(second).status, "inserted")
        self.assertNotEqual(second.source_key, self.seed.source_key)

    def test_platform_sequence_orders_edits_not_event_timestamp(self):
        later = replace(self.seed, version="v2", version_seq=2, text="新的负责人需要核实", event_time="2026-11-01T10:00:00+08:00")
        self.assertEqual(self.ledger.ingest(later).status, "advanced")
        self.assertEqual(self.ledger.task_view("task_a")["seed_issues"], ["source_changed"])

    def test_out_of_order_event_cannot_replace_current(self):
        later = replace(self.seed, version="v3", version_seq=3)
        self.ledger.ingest(later)
        historical = replace(self.seed, version="v2", version_seq=2, text="过往版本")
        self.assertEqual(self.ledger.ingest(historical).status, "historical")
        self.assertEqual(self.ledger.ingest(later).status, "duplicate")

    def test_same_version_different_content_is_conflict(self):
        conflict = replace(self.seed, text="另一份互相矛盾的内容")
        self.assertEqual(self.ledger.ingest(conflict).status, "conflict")
        self.assertIn("source_conflict", self.ledger.task_view("task_a")["seed_issues"])

    def test_reviewed_source_conflict_resolution_and_rebase_restore_readiness(self):
        old_snapshot = self.ledger.snapshot(["task_a"])
        self.ledger.ingest(replace(self.seed, text="存在异文"))
        authoritative = replace(self.seed, version="v2", version_seq=2, text=self.seed.text + "\n补充说明。")
        self.ledger.ingest(authoritative)
        state = self.ledger.source_state(self.seed.source_key)
        self.assertTrue(state["conflicted"])
        self.ledger.resolve_source_conflict(self.seed.source_key, authoritative.ref, "trusted_reviewer",
                                            state["state_version"], explanation="已定向回读原始来源核实该版本")
        still_old = self.ledger.task_view("task_a")
        self.assertFalse(still_old["followup_ready"])
        rebased = self.ledger.review_rebase_task("task_a", [authoritative.ref], "trusted_reviewer",
                                                still_old["version"], explanation="项目、责任人和动作的含义均未改变")
        self.assertTrue(rebased["followup_ready"])
        self.assertEqual(rebased["owner_id"], "engineer_a")
        self.assertEqual(len(self.ledger.seed_history("task_a")), 2)
        self.assertIn("task_changed", self.ledger.check_snapshot(old_snapshot, ["person:engineer_a"]))

    def test_source_conflict_resolution_requires_current_generation(self):
        self.ledger.ingest(replace(self.seed, text="冲突甲"))
        state = self.ledger.source_state(self.seed.source_key)
        self.ledger.ingest(replace(self.seed, text="冲突乙"))
        with self.assertRaises(ConcurrentUpdate):
            self.ledger.resolve_source_conflict(self.seed.source_key, self.seed.ref, "trusted_reviewer",
                                                state["state_version"], explanation="旧界面看到的版本")

    def test_source_resolution_cannot_pick_another_source(self):
        self.ledger.ingest(replace(self.seed, text="冲突"))
        unrelated = self.source("无关证据")
        self.ledger.ingest(unrelated)
        state = self.ledger.source_state(self.seed.source_key)
        with self.assertRaises(EvidenceError):
            self.ledger.resolve_source_conflict(self.seed.source_key, unrelated.ref, "reviewer",
                                                state["state_version"], explanation="不能换来源")

    def test_rebase_cannot_swap_source_identity(self):
        unrelated = self.source("无关事项的新来源")
        self.ledger.ingest(unrelated)
        with self.assertRaises(EvidenceError):
            self.ledger.review_rebase_task("task_a", [unrelated.ref], "reviewer",
                                          self.ledger.task_view("task_a")["version"], explanation="不能借rebase换任务")

    def test_rebase_requires_fresh_task_version_and_current_source(self):
        version = self.ledger.task_view("task_a")["version"]
        edited = replace(self.seed, version="v2", version_seq=2, text=self.seed.text + " 已补充")
        self.ledger.ingest(edited)
        with self.assertRaises(ConcurrentUpdate):
            self.ledger.review_rebase_task("task_a", [edited.ref], "reviewer", version, explanation="旧任务版本")
        with self.assertRaises(EvidenceError):
            self.ledger.review_rebase_task("task_a", [self.seed.ref], "reviewer",
                                          self.ledger.task_view("task_a")["version"], explanation="旧证据版本")

    def test_unordered_versions_do_not_guess_lexical_order(self):
        source = self.source("原文", "opaque_versions", version="z", version_seq=None)
        self.ledger.ingest(source)
        second = replace(source, version="a", text="另一版本")
        self.assertEqual(self.ledger.ingest(second).status, "unordered")

    def test_explicit_predecessor_orders_opaque_versions(self):
        source = self.source("原文", "opaque_versions", version="z", version_seq=None)
        self.ledger.ingest(source)
        second = replace(source, version="a", text="新原文", replaces_version="z")
        self.assertEqual(self.ledger.ingest(second).status, "advanced")

    def test_candidate_is_not_business_truth(self):
        self.proposal("execution", "done")
        task = self.ledger.task_view("task_a")
        self.assertEqual(task["execution"], "unknown")
        self.assertFalse(task["business_completed"])
        self.assertFalse(task["followup_ready"])

    def test_quote_span_prevents_unattributed_candidate(self):
        span = QuoteSpan(self.seed.ref, 0, 2, "编造")
        with self.assertRaises(EvidenceError):
            self.ledger.propose(FactProposal("task_a", "execution", "done", (span,), T))

    def test_acknowledgement_only_resolves_exact_pending_response(self):
        pending = self.accept("response", "pending")
        self.accept("response", "acknowledged", supersedes=(pending,), response_to=pending,
                    source=self.source("收到"))
        task = self.ledger.task_view("task_a")
        self.assertEqual(task["response"], "acknowledged")
        self.assertEqual(task["execution"], "unknown")
        self.assertFalse(task["business_completed"])

    def test_acknowledgement_cannot_close_other_task_response(self):
        self.create_task("task_b")
        pending = self.accept("response", "pending", task_id="task_b")
        claim = self.proposal("response", "acknowledged", supersedes=(pending,), response_to=pending)
        with self.assertRaises(EvidenceError):
            self.ledger.accept_claim(claim, "reviewer", self.ledger.task_view("task_a")["version"])

    def test_acknowledgement_requires_explicit_reply_binding(self):
        with self.assertRaises(EvidenceError):
            self.proposal("response", "acknowledged")

    def test_sent_plan_is_not_started_test(self):
        self.accept("plan_delivery", "delivered", source=self.source("方案已经发送"))
        self.accept("planned_start", "2026-11-02", source=self.source("计划周一开测"))
        task = self.ledger.task_view("task_a")
        self.assertEqual(task["fields"]["plan_delivery"]["values"], ["delivered"])
        self.assertEqual(task["delivery"], "unknown")
        self.assertEqual(task["execution"], "unknown")
        self.assertNotIn("actual_start", task["fields"])
        self.assertFalse(task["business_completed"])
        self.assertEqual(task["business_state"], "open")
        self.assertEqual(task["legacy_action_status"], "waiting")

    def test_delivery_claim_requires_task_target_artifact(self):
        with self.assertRaises(EvidenceError):
            self.proposal("delivery", "delivered", source=self.source("方案已经发送"))
        self.create_task("report", action="交付测试报告", deliverable_key="test_report")
        with self.assertRaises(EvidenceError):
            self.proposal("delivery", "delivered", task_id="report", subject_key="test_plan")
        self.accept("delivery", "delivered", task_id="report", subject_key="test_report",
                    source=self.source("测试报告已经发送"))
        report = self.ledger.task_view("report")
        self.assertEqual(report["legacy_action_status"], "submitted")
        self.assertFalse(report["business_completed"])

    def test_prepared_release_is_not_published(self):
        self.accept("release_materials", "ready", source=self.source("稿件和测试版本已齐"))
        self.accept("planned_release", "本周", source=self.source("计划本周发布"))
        self.assertNotIn("actual_release", self.ledger.task_view("task_a")["fields"])
        self.assertFalse(self.ledger.task_view("task_a")["business_completed"])
        self.assertEqual(self.ledger.task_view("task_a")["legacy_action_status"], "waiting")

    def test_approval_obsoletes_submission_not_entire_project(self):
        self.create_task("submit_approval", purpose="approval_submission", action="提交审批")
        self.accept("approval", "approved", task_id="submit_approval")
        task = self.ledger.task_view("submit_approval")
        self.assertTrue(task["obsolete_action"])
        self.assertFalse(task["business_completed"])
        self.assertEqual(task["fields"]["approval"]["values"], ["approved"])
        self.assertEqual(self.ledger.task_view("task_a")["execution"], "unknown")

    def test_hypothetical_actual_approval_withdrawal_is_separate_fact(self):
        self.create_task("submit_approval", purpose="approval_submission")
        first = self.accept("approval", "approved", task_id="submit_approval")
        self.accept("approval", "withdrawn", task_id="submit_approval", supersedes=(first,))
        task = self.ledger.task_view("submit_approval")
        self.assertFalse(task["obsolete_action"])
        self.assertFalse(task["business_completed"])

    def test_completion_requires_execution_and_acceptance_evidence(self):
        self.accept("execution", "done")
        self.assertFalse(self.ledger.task_view("task_a")["business_completed"])
        self.accept("acceptance", "accepted")
        task = self.ledger.task_view("task_a")
        self.assertTrue(task["business_completed"])
        self.assertEqual(len(task["completion_claim_ids"]), 2)
        self.assertFalse(task["followup_ready"])

    def test_equal_field_conflicts_do_not_use_latest_wins(self):
        self.accept("owner_id", "engineer_a")
        self.accept("owner_id", "engineer_b")
        task = self.ledger.task_view("task_a")
        self.assertTrue(task["conflict"])
        self.assertIsNone(task["owner_id"])
        self.assertFalse(task["followup_ready"])

    def test_explicit_supersedes_reconciles_field(self):
        first = self.accept("owner_id", "engineer_a")
        self.accept("owner_id", "engineer_b", supersedes=(first,))
        task = self.ledger.task_view("task_a")
        self.assertFalse(task["conflict"])
        self.assertEqual(task["owner_id"], "engineer_b")

    def test_edit_invalidates_accepted_claim_and_old_snapshot(self):
        source = self.source("正在测试")
        self.accept("execution", "in_progress", source=source)
        snapshot = self.ledger.snapshot(["task_a"])
        self.ledger.ingest(replace(source, version="v2", version_seq=2, text="尚未测试"))
        task = self.ledger.task_view("task_a")
        self.assertEqual(task["execution"], "unknown")
        self.assertTrue(task["stale"])
        self.assertIn("task_changed", self.ledger.check_snapshot(snapshot, ["person:engineer_a"]))

    def test_retraction_does_not_delete_historical_task(self):
        self.ledger.ingest(replace(self.seed, version="v2", version_seq=2, retracted=True))
        task = self.ledger.task_view("task_a")
        self.assertEqual(task["task_id"], "task_a")
        self.assertEqual(task["business_state"], "needs_verification")

    def test_import_missing_mapping_and_id_remains_private_candidate(self):
        weak = self.source("两个项目估时待明确", stable_id=False)
        self.ledger.ingest(weak)
        self.create_task("legacy", evidence_refs=(weak.ref,), project_id=None, owner_id=None)
        task = self.ledger.task_view("legacy")
        self.assertTrue(task["provisional"])
        self.assertEqual(task["missing"], ["project_id", "owner_id"])
        self.assertIsNone(task["deadline_text"])
        self.assertFalse(task["followup_ready"])

    def test_private_chat_cannot_become_project_candidate(self):
        private = self.source("私人话题", sensitivity="private")
        with self.assertRaises(EvidenceError):
            self.proposal("risk", "私人话题", source=private)

    def test_private_material_cannot_seed_task(self):
        private = self.source("私人话题", sensitivity="private")
        self.ledger.ingest(private)
        with self.assertRaises(EvidenceError):
            self.create_task("personal", evidence_refs=(private.ref,))

    def test_version_sequence_must_be_authoritative_integer(self):
        with self.assertRaises(EvidenceError):
            self.source("无有效顺序", version_seq="2")

    def test_body_business_time_is_not_converted(self):
        self.accept("deadline_text", "10点前", source=self.source("10点前给信息"))
        self.assertEqual(self.ledger.task_view("task_a")["deadline_text"], "10点前")
        self.assertEqual(display_time("2026-11-02T11:36:00+09:00"), "2026-11-02T10:36:00+08:00")

    def test_naive_event_timestamp_is_rejected(self):
        with self.assertRaises(EvidenceError):
            self.source("无法定位时间", event_time="2026-11-02T10:00:00")

    def test_scope_specific_failure_preserves_cursor_and_tasks(self):
        messages = CoverageKey("scanner", "message", "demo_chat")
        calendar = CoverageKey("scanner", "calendar", "week")
        self.ledger.record_read(ReadResult(messages, "success", T, T, 0, cursor="m1", cursor_seq=1))
        self.ledger.record_read(ReadResult(messages, "failed", T1, T1, 1, reason="unreadable"))
        self.ledger.record_read(ReadResult(calendar, "success", T1, T1, 0, cursor="empty_grid"))
        self.assertEqual(self.ledger.checkpoint(messages)["cursor"], "m1")
        self.assertEqual(self.ledger.checkpoint(messages)["result"]["status"], "failed")
        self.assertEqual(self.ledger.task_view("task_a")["task_id"], "task_a")

    def test_partial_read_cannot_advance_scope_cursor(self):
        key = CoverageKey("scanner", "message", "demo_chat")
        with self.assertRaises(EvidenceError):
            self.ledger.record_read(ReadResult(key, "partial", T, T, 0, cursor="new"))

    def test_cli_backfill_does_not_advance_web_checkpoint(self):
        cli = CoverageKey("cli_backfill", "message", "demo_chat")
        web = CoverageKey("web_scanner", "message", "demo_chat")
        self.ledger.record_read(ReadResult(cli, "success", T, T, 0, cursor="m100"))
        self.assertEqual(self.ledger.checkpoint(web)["version"], 0)

    def test_gap_survives_local_recovery(self):
        key = CoverageKey("scanner", "message", "demo_chat")
        self.ledger.add_gap("historic_gap", key, "历史消息部分缺失", T)
        self.ledger.record_read(ReadResult(key, "success", T1, T1, 0, cursor="m1"))
        self.assertEqual(len(self.ledger.coverage_view()["open_gaps"]), 1)
        snapshot = self.ledger.snapshot(["task_a"], required_coverage=[key])
        self.assertIn("coverage_gap", self.ledger.check_snapshot(snapshot, ["person:engineer_a"]))

    def test_gap_closure_requires_stable_matching_coverage_proof(self):
        key = CoverageKey("scanner", "message", "demo_chat")
        self.ledger.add_gap("historic_gap", key, "已知范围缺口", T)
        with self.assertRaises(EvidenceError):
            self.ledger.resolve_gap("historic_gap", resolution_ref=self.seed.ref, reviewer_id="reviewer", resolved_at=T1)
        proof = self.source("已逐项核对该范围水位", source_type="coverage_proof")
        self.ledger.ingest(proof)
        self.ledger.resolve_gap("historic_gap", resolution_ref=proof.ref, reviewer_id="reviewer", resolved_at=T1)
        self.assertEqual(self.ledger.coverage_view()["open_gaps"], [])

    def test_ingest_batch_and_cursor_are_atomic(self):
        source = self.source("不应因游标错误留在数据库")
        key = CoverageKey("scanner", "message", "demo_chat")
        with self.assertRaises(ConcurrentUpdate):
            self.ledger.ingest_batch([source], ReadResult(key, "success", T, T, 999, cursor="m1"))
        with self.assertRaises(EvidenceError):
            self.ledger.get_evidence(source.ref)

    def test_concurrent_checkpoint_updates_only_one_wins(self):
        key = CoverageKey("scanner", "message", "demo_chat")
        def update(cursor):
            try:
                self.ledger.record_read(ReadResult(key, "success", T, T, 0, cursor=cursor))
                return "success"
            except ConcurrentUpdate:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(update, ["m1", "m2"]))
        self.assertCountEqual(outcomes, ["success", "conflict"])

    def test_concurrent_semantic_review_cannot_clobber_task(self):
        first = self.proposal("execution", "planned")
        before = self.ledger.task_view("task_a")["version"]
        self.proposal("risk", "物料待核实")
        with self.assertRaises(ConcurrentUpdate):
            self.ledger.accept_claim(first, "reviewer", before)

    def test_snapshot_requires_exact_dependencies(self):
        self.accept("risk", "请勿传播原始附件")
        snapshot = self.ledger.snapshot(["task_a"])
        truncated = replace(snapshot, refs=snapshot.refs[:1])
        self.assertIn("snapshot_dependencies_mismatch", self.ledger.check_snapshot(truncated, ["person:engineer_a"]))

    def test_snapshot_roundtrip_and_audience_scope(self):
        snapshot = self.ledger.snapshot(["task_a"], created_at=T)
        decoded = EvidenceSnapshot.from_dict(snapshot.to_dict())
        self.assertEqual(snapshot, decoded)
        self.assertEqual(self.ledger.check_snapshot(decoded, ["chat:demo_chat"]), ())
        self.assertIn("audience_not_allowed", self.ledger.check_snapshot(decoded, ["person:external_partner"]))

    def test_snapshot_expiry_and_acl_change(self):
        snapshot = self.ledger.snapshot(["task_a"], created_at=T)
        self.assertIn("snapshot_expired_or_future", self.ledger.check_snapshot(snapshot, ["person:owner"], now=T2, max_age_seconds=60))
        update = replace(self.seed, version="v2", version_seq=2, acl_version="acl2", audience_keys=("person:owner",))
        self.ledger.ingest(update)
        reasons = self.ledger.check_snapshot(snapshot, ["person:engineer_a"])
        self.assertIn("source_changed", reasons)

    def test_cross_tenant_isolation(self):
        other = EvidenceLedger(self.path, "other_tenant")
        with self.assertRaises(EvidenceError):
            other.get_evidence(self.seed.ref)
        with self.assertRaises(EvidenceError):
            other.ingest(self.seed)
        self.assertEqual(other.check_snapshot(self.ledger.snapshot(["task_a"]), ["person:owner"]), ("cross_tenant_snapshot",))

    def test_task_and_pending_claim_survive_restart(self):
        self.proposal("planned_start", "本周")
        reopened = EvidenceLedger(self.path, "tenant_demo")
        self.assertEqual(len(reopened.task_view("task_a")["candidates"]), 1)

    def test_progress_projection_has_no_invented_percentage(self):
        self.accept("execution", "in_progress")
        project = self.ledger.project_view("project_a")
        self.assertIsNone(project["progress_percentage"])
        self.assertTrue(project["tasks"][0]["fields"]["execution"]["claims"][0]["evidence"])

    def test_new_overview_does_not_release_restricted_original(self):
        self.accept("external_release", "forbidden")
        self.accept("test_overview", "六项测试概述已提供")
        task = self.ledger.task_view("task_a")
        self.assertEqual(task["fields"]["external_release"]["values"], ["forbidden"])
        self.assertNotIn("actual_start", task["fields"])


if __name__ == "__main__":
    unittest.main()
