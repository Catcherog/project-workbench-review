"""Independent semantic counterexamples for the legacy-field adapter.

These test adapter trust, not the rewriter's closed selection protocol.
All names, projects and updates are synthetic.
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import json
import unittest

from am_reply.compiler import build_legacy_contract
from am_reply.contracts import default_plan, fallback_text, render_candidate
from am_reply.types import ContractError


class CompilerReviewTests(unittest.TestCase):
    def setUp(self):
        self.ctx = SimpleNamespace(
            source_access_version="source-version-2",
            session_id="synthetic-scope-A",
            can_access_project=lambda key: key == "project-75",
        )
        self.project = {
            "id": "project-75",
            "title": "需求75：合成工艺试验",
            "aliases": ["需求75"],
            "identity_status": "verified",
            "fields": {
                "人员与职责": "AR101张甲 | 测试\nAR102李乙 | 采购",
                "项目进展": "首批尚未到货。所有日期均以首批测试合格为前提；未合格不得启动下一批。",
                "关键日期": "第二批预计11月8日启动。",
                "待办": "确认第二批启动安排。",
            },
            "snapshot": {"version": "a" * 64, "stale": False},
            "evidence_state": "recorded_not_independently_verified",
        }

    def compile(self, question="需求75谁负责？", *, project=None, extras=()):
        p = self.project if project is None else project
        evidence = [json.dumps(p, ensure_ascii=False)]
        evidence.extend(json.dumps(extra, ensure_ascii=False) for extra in extras)
        return build_legacy_contract(self.ctx, "event-synthetic-75", question,
                                     "模型原答复，仅为输入而非证据。", evidence)

    def assert_intact_or_declined(self, project):
        result = self.compile(project=project)
        if result is None:
            return
        self.assertEqual(result.origin, "ledger_source_block")
        self.assertEqual(result.claims[0].variants,
                         (project["fields"]["人员与职责"],))

    def test_global_role_condition_inside_a_line_is_not_rebound_to_person(self):
        project = deepcopy(self.project)
        project["fields"]["人员与职责"] = (
            "AR101张甲 | 测试，所有职责仅在方案批准后生效\n"
            "AR102李乙 | 采购"
        )
        self.assert_intact_or_declined(project)

    def test_role_status_or_unknown_person_is_not_recast_as_assigned_owner(self):
        for raw in ("AR101张甲 | 已退出项目", "尚未确定 | 测试负责人",
                    "AR101张甲 | 不再负责测试"):
            with self.subTest(raw=raw):
                project = deepcopy(self.project)
                project["fields"]["人员与职责"] = raw
                self.assert_intact_or_declined(project)

    def test_conflicting_newer_nonledger_facts_do_not_get_replaced_by_old_field(self):
        project = deepcopy(self.project)
        project["fields"]["项目进展"] = "测试尚未开始。"
        project["information"] = {
            "available": True,
            "facts": [{"fact_id": "feedback-1", "field": "project_progress",
                       "value": "今天已经开始测试。", "business_state": "reported"}],
            "coverage": {"needs_refresh_or_review": False, "processing_pending": False},
        }
        self.assertIsNone(self.compile("需求75最新进展？", project=project))

    def test_extra_information_read_cannot_be_silently_dropped(self):
        update = {
            "available": True,
            "facts": [{"fact_id": "feedback-2", "subject_id": "project-75",
                       "field": "project_progress", "value": "首批已到货，等待检查。"}],
        }
        self.assertIsNone(self.compile("需求75项目进展？", extras=(update,)))

    def test_oversize_read_result_is_not_silently_treated_as_absent(self):
        update = {
            "facts": [{"subject_id": "project-75", "value": "更新事实" * 30000}],
        }
        # Evidence is recorded before the original engine truncates a tool
        # result for the model. An oversized result is not proof of absence.
        self.assertIsNone(self.compile("需求75项目进展？", extras=(update,)))

    def test_explicit_project_number_mismatch_declines_projection(self):
        self.assertIsNone(self.compile("需求76谁负责？"))

    def test_requested_provenance_is_not_replaced_by_business_dates(self):
        for question in ("需求75的资料采集时间？", "需求75快照版本与观察时间？",
                         "需求75进展的来源是什么？"):
            with self.subTest(question=question):
                self.assertIsNone(self.compile(question))

    def test_ledger_record_is_not_promoted_to_independently_verified_fact(self):
        contract = self.compile()
        self.assertTrue(contract.require_record_attribution)
        self.assertTrue(fallback_text(contract).startswith("按现有记录，"))
        candidate = default_plan(contract)
        candidate["lead_in"] = "none"
        with self.assertRaisesRegex(ContractError, "SOURCE_ATTRIBUTION_REQUIRED"):
            render_candidate(contract, candidate)

    def test_same_name_staff_keep_codes_in_natural_variants(self):
        project = deepcopy(self.project)
        project["fields"]["人员与职责"] = "AR101张甲 | 测试\nAR102张甲 | 采购"
        contract = self.compile(project=project)
        self.assertIsNotNone(contract)
        self.assertEqual(contract.origin, "ledger_role_projection")
        text = fallback_text(contract)
        self.assertIn("AR101张甲", text)
        self.assertIn("AR102张甲", text)

    def test_dates_and_todos_keep_whole_progress_condition(self):
        for question in ("需求75关键日期？", "需求75有哪些待办？"):
            with self.subTest(question=question):
                contract = self.compile(question)
                self.assertIsNotNone(contract)
                self.assertEqual(contract.origin, "ledger_source_block")
                text = fallback_text(contract)
                self.assertIn(self.project["fields"]["项目进展"], text)

    def test_arbitrary_progress_prose_remains_one_intact_source_block(self):
        contract = self.compile("需求75项目进展？")
        self.assertIsNotNone(contract)
        self.assertEqual(contract.origin, "ledger_source_block")
        self.assertEqual(contract.claims[0].variants,
                         (self.project["fields"]["项目进展"],))


if __name__ == "__main__":
    unittest.main()
