"""Behavior tests for knowledge provenance, approval and current-scope isolation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from am_conversation.knowledge import KnowledgeStore
from am_conversation.types import AccessContext, ConversationError


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "knowledge.sqlite3"
        self.owners = {("tenant-a", "app-a"): {"owner"},
                       ("tenant-b", "app-a"): {"owner"},
                       ("tenant-a", "app-b"): {"owner"}}
        self.owner = AccessContext(
            "tenant-a", "app-a", "owner", "chat-a", "thread-a",
            frozenset({"project-a", "project-b"}), is_owner=True,
        )
        self.colleague = replace(self.owner, actor_id="engineer", is_owner=False)
        self.source = {"uri": "synthetic://meeting/one", "observed_at": "2026-10-30T09:00:00+08:00",
                       "version": "source-revision-1"}
        self.store = KnowledgeStore(self.path, owner_ids=self.owners, clock=lambda: 1000.0)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def approved(self, content: str, *, ctx: AccessContext | None = None,
                 kind: str = "fact", scope: str = "private", project_id: str | None = None):
        ctx = ctx or self.owner
        record = self.store.submit(ctx, kind=kind, content=content, source=self.source,
                                   scope=scope, project_id=project_id)
        return self.store.approve(ctx, record["id"], record["version"])

    def assert_code(self, code: str, function, *args, **kwargs):
        with self.assertRaises(ConversationError) as caught:
            function(*args, **kwargs)
        self.assertEqual(code, str(caught.exception))

    def test_owner_requires_current_capability_and_matching_configuration(self):
        candidate = self.store.submit(self.owner, kind="rule", content="交付前核查证据", source=self.source,
                                      scope="tenant")
        for ctx in (replace(self.owner, is_owner=False),
                    replace(self.colleague, is_owner=True)):
            with self.subTest(ctx=ctx.actor_id, owner_flag=ctx.is_owner):
                self.assert_code("KNOWLEDGE_OWNER_REQUIRED", self.store.approve,
                                 ctx, candidate["id"], 1)
                self.assert_code("KNOWLEDGE_OWNER_REQUIRED", self.store.submit, ctx,
                                 kind="rule", content="声称我是负责人", source=self.source)
        unconfigured = KnowledgeStore(self.path)
        try:
            self.assert_code("KNOWLEDGE_OWNER_REQUIRED", unconfigured.approve,
                             self.owner, candidate["id"], 1)
        finally:
            unconfigured.close()
        self.assertEqual("approved", self.store.approve(self.owner, candidate["id"], 1)["status"])

    def test_colleague_can_only_submit_private_candidate_facts(self):
        record = self.store.submit(self.colleague, kind="fact", content="工程师报告测试完成",
                                   source=self.source, project_id="project-a")
        self.assertEqual("candidate", record["status"])
        self.assertEqual([record["id"]], [r["id"] for r in self.store.review_candidates(self.colleague)])
        self.assertEqual([], self.store.search(self.colleague, "测试"))
        for kind, scope in (("rule", "private"), ("case", "private"), ("fact", "tenant"),
                            ("fact", "project")):
            with self.subTest(kind=kind, scope=scope):
                self.assert_code("KNOWLEDGE_OWNER_REQUIRED", self.store.submit, self.colleague,
                                 kind=kind, content="不能自动共享", source=self.source,
                                 scope=scope, project_id="project-a" if scope == "project" else None)
        self.assert_code("KNOWLEDGE_OWNER_REQUIRED", self.store.approve,
                         self.colleague, record["id"], 1)
        self.assert_code("KNOWLEDGE_NOT_FOUND", self.store.get, self.owner, record["id"])
        self.assert_code("KNOWLEDGE_NOT_FOUND", self.store.approve, self.owner, record["id"], 1)
        self.assertEqual([], self.store.review_candidates(self.owner))

    def test_private_scope_includes_tenant_app_actor_chat_and_thread(self):
        record = self.approved("当前私聊的测试风险")
        self.assertEqual(record["id"], self.store.search(self.owner, "测试风险")[0]["id"])
        alternatives = (
            replace(self.owner, tenant_id="tenant-b"),
            replace(self.owner, app_id="app-b"),
            replace(self.owner, actor_id="engineer", all_projects=True),
            replace(self.owner, chat_id="another-chat", all_projects=True),
            replace(self.owner, thread_id="another-thread", all_projects=True),
        )
        for ctx in alternatives:
            with self.subTest(scope=ctx.scope):
                self.assertEqual([], self.store.search(ctx, "测试风险"))
                self.assert_code("KNOWLEDGE_NOT_FOUND", self.store.get, ctx, record["id"])

    def test_shared_knowledge_still_isolates_tenant_and_application(self):
        record = self.approved("部门共同的评审要求", kind="rule", scope="tenant")
        self.assertEqual(record["id"], self.store.search(self.colleague, "评审")[0]["id"])
        for ctx in (replace(self.owner, tenant_id="tenant-b"), replace(self.owner, app_id="app-b")):
            self.assertEqual([], self.store.search(ctx, "评审"))
            self.assert_code("KNOWLEDGE_NOT_FOUND", self.store.get, ctx, record["id"])

    def test_permission_reduction_hides_previous_project_records_and_candidates(self):
        project = self.approved("项目测试风险", scope="project", project_id="project-a")
        private = self.approved("个人记录的测试风险", project_id="project-a")
        tenant = self.approved("通用测试风险原则", scope="tenant", kind="rule")
        pending = self.store.submit(self.owner, kind="case", content="测试风险候选案例",
                                    source=self.source, scope="project", project_id="project-a")
        reduced = replace(self.owner, allowed_project_ids=frozenset({"project-b"}))
        self.assertEqual({tenant["id"]}, {r["id"] for r in self.store.search(reduced, "测试风险")})
        self.assertEqual([], self.store.review_candidates(reduced))
        for record in (project, private, pending):
            self.assert_code("KNOWLEDGE_NOT_FOUND", self.store.get, reduced, record["id"])
        self.assert_code("PROJECT_FORBIDDEN", self.store.search, reduced, "测试风险", project_id="project-a")
        self.assert_code("KNOWLEDGE_NOT_FOUND", self.store.approve, reduced, pending["id"], 1)

    def test_project_filter_applies_before_ranking_and_includes_general_rules(self):
        shared = self.approved("交付需要确认", kind="rule", scope="tenant")
        relevant = self.approved("交付资料待核验", scope="project", project_id="project-a")
        private = self.approved("交付个人备注", project_id="project-a")
        self.approved("SECRET_PROJECT_B 交付交付交付", scope="project", project_id="project-b")
        self.approved("SECRET_PRIVATE_B 交付交付交付", project_id="project-b")
        import am_conversation.knowledge as knowledge_module
        original = knowledge_module._lexical_score
        ranked_contents = []

        def observe(query, content):
            ranked_contents.append(content)
            return original(query, content)

        with patch.object(knowledge_module, "_lexical_score", side_effect=observe):
            results = self.store.search(self.owner, "交付", project_id="project-a")
        self.assertEqual({shared["id"], relevant["id"], private["id"]}, {r["id"] for r in results})
        self.assertTrue(ranked_contents)
        self.assertFalse(any("SECRET" in text for text in ranked_contents))

    def test_approval_replaces_one_version_and_retains_exact_provenance(self):
        first = self.approved("试验节点仍待确认", scope="project", project_id="project-a")
        revised_source = {**self.source, "version": "source-revision-2"}
        second = self.store.submit(
            self.owner, kind="fact", content="试验节点已经确认", source=revised_source,
            scope="project", project_id="project-a", logical_id=first["logical_id"], expected_version=1,
        )
        revised_source["version"] = "accidental-caller-mutation"
        self.assertEqual([first["id"]], [r["id"] for r in self.store.search(self.owner, "试验节点")])
        self.assert_code("STALE_KNOWLEDGE_VERSION", self.store.approve, self.owner, second["id"], 1)
        approved = self.store.approve(self.owner, second["id"], 2)
        self.assertEqual("source-revision-2", approved["source"]["version"])
        self.assertEqual([second["id"]], [r["id"] for r in self.store.search(self.owner, "试验节点")])
        history = self.store.get(self.owner, first["id"])
        self.assertEqual("superseded", history["status"])
        self.assertEqual("source-revision-1", history["source"]["version"])
        self.assertEqual("试验节点仍待确认", history["content"])
        self.assert_code("KNOWLEDGE_NOT_CANDIDATE", self.store.approve, self.owner, first["id"], 1)
        self.assertEqual(first["id"], self.store.get(self.colleague, first["id"])["id"])

    def test_old_unapproved_candidate_cannot_be_approved_or_leak_as_history(self):
        first = self.store.submit(self.owner, kind="rule", content="未经确认的错误规则",
                                  source=self.source, scope="tenant")
        second = self.store.submit(self.owner, kind="rule", content="修正后的规则",
                                   source=self.source, scope="tenant", logical_id=first["logical_id"],
                                   expected_version=1)
        self.assert_code("STALE_KNOWLEDGE_VERSION", self.store.approve, self.owner, first["id"], 1)
        self.assertEqual([second["id"]], [r["id"] for r in self.store.review_candidates(self.owner)])
        self.assert_code("KNOWLEDGE_NOT_FOUND", self.store.get, self.colleague, first["id"])
        self.store.approve(self.owner, second["id"], 2)
        self.assertEqual("superseded", self.store.get(self.owner, first["id"])["status"])
        self.assert_code("KNOWLEDGE_NOT_FOUND", self.store.get, self.colleague, first["id"])
        self.assertEqual([], self.store.search(self.colleague, "错误"))

    def test_content_revision_cannot_silently_widen_visibility(self):
        private = self.approved("私聊内容不能借修订共享", kind="rule")
        self.assert_code("KNOWLEDGE_SCOPE_IMMUTABLE", self.store.submit, self.owner,
                         kind="rule", content="试图改为部门规则", source=self.source, scope="tenant",
                         logical_id=private["logical_id"], expected_version=1)
        project = self.approved("项目专用说明", scope="project", project_id="project-a")
        self.assert_code("KNOWLEDGE_SCOPE_IMMUTABLE", self.store.submit, self.owner,
                         kind="fact", content="试图移入其他项目", source=self.source, scope="project",
                         project_id="project-b", logical_id=project["logical_id"], expected_version=1)
        other_chat = replace(self.owner, chat_id="new-chat")
        self.assert_code("KNOWLEDGE_NOT_FOUND", self.store.submit, other_chat,
                         kind="rule", content="不能从其他私聊接管", source=self.source,
                         logical_id=private["logical_id"], expected_version=1)
        self.assertEqual("私聊内容不能借修订共享", self.store.get(self.owner, private["id"])["content"])

    def test_rejection_does_not_replace_approved_truth_and_can_be_revised(self):
        first = self.approved("当前有效交付条件", kind="rule", scope="tenant")
        candidate = self.store.submit(self.owner, kind="rule", content="被否定的交付条件",
                                      source=self.source, scope="tenant", logical_id=first["logical_id"],
                                      expected_version=1)
        self.assert_code("STALE_KNOWLEDGE_VERSION", self.store.reject, self.owner, candidate["id"], 1)
        rejected = self.store.reject(self.owner, candidate["id"], 2)
        self.assertEqual("rejected", rejected["status"])
        self.assertEqual(rejected, self.store.reject(self.owner, candidate["id"], 2))
        self.assertEqual([first["id"]], [r["id"] for r in self.store.search(self.owner, "交付条件")])
        self.assert_code("KNOWLEDGE_NOT_CANDIDATE", self.store.approve, self.owner, candidate["id"], 2)
        replacement = self.store.submit(self.owner, kind="rule", content="修正交付条件",
                                        source=self.source, scope="tenant", logical_id=first["logical_id"],
                                        expected_version=2)
        self.assertEqual(3, self.store.approve(self.owner, replacement["id"], 3)["version"])

    def test_concurrent_revisions_use_compare_and_swap_across_connections(self):
        first = self.approved("同一项目初始事实", scope="project", project_id="project-a")
        stores = [KnowledgeStore(self.path, owner_ids=self.owners) for _ in range(2)]
        barrier = threading.Barrier(2)

        def revise(index):
            barrier.wait(timeout=5)
            try:
                return stores[index].submit(
                    self.owner, kind="fact", content=f"并发修订方案{index}", source=self.source,
                    scope="project", project_id="project-a", logical_id=first["logical_id"], expected_version=1,
                )
            except ConversationError as error:
                return str(error)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(revise, range(2)))
        finally:
            for store in stores:
                store.close()
        accepted = [result for result in results if isinstance(result, dict)]
        self.assertEqual(1, len(accepted))
        self.assertEqual(2, accepted[0]["version"])
        self.assertEqual(["STALE_KNOWLEDGE_VERSION"], [r for r in results if isinstance(r, str)])
        self.assertEqual(first["id"], self.store.search(self.owner, "初始事实")[0]["id"])

    def test_duplicate_approval_is_idempotent_across_connections(self):
        record = self.store.submit(self.owner, kind="rule", content="重复批准仍只有一个生效版本",
                                   source=self.source, scope="tenant")
        stores = [KnowledgeStore(self.path, owner_ids=self.owners) for _ in range(2)]
        barrier = threading.Barrier(2)

        def approve(index):
            barrier.wait(timeout=5)
            return stores[index].approve(self.owner, record["id"], 1)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(approve, range(2)))
        finally:
            for store in stores:
                store.close()
        self.assertEqual(["approved", "approved"], [r["status"] for r in results])
        self.assertEqual(results[0], results[1])
        self.assertEqual([record["id"]], [r["id"] for r in self.store.search(self.colleague, "生效版本")])

    def test_chinese_bigrams_words_and_kind_filters_work_without_vectors(self):
        exact = self.approved("测试延期时先确认是否影响关键节点", kind="rule", scope="tenant")
        self.approved("测试记录应附原始数据", kind="business", scope="tenant")
        self.approved("采购下单需要核查型号", kind="business", scope="tenant")
        self.assertEqual(exact["id"], self.store.search(self.colleague, "测试延期")[0]["id"])
        self.assertEqual([exact["id"]], [r["id"] for r in self.store.search(self.colleague, "测试", kinds=["rule"])])
        self.assertEqual([], self.store.search(self.colleague, "海岛潮汐"))
        brand = self.approved("EROB80I V6 型号的测试准备", kind="business", scope="tenant")
        self.assertEqual(brand["id"], self.store.search(self.colleague, "ｅｒｏｂ８０ｉ")[0]["id"])
        self.assertEqual([], self.store.search(self.colleague, "测试", kinds=[]))
        self.assert_code("INVALID_KNOWLEDGE_KIND", self.store.search, self.owner, "测试", kinds="rule")

    def test_sources_are_required_and_records_persist_after_restart(self):
        for source in ({}, {"uri": "synthetic://one"}, {"uri": "", "observed_at": "today"},
                       {**self.source, "bad": float("nan")}):
            self.assert_code("INVALID_KNOWLEDGE_SOURCE", self.store.submit, self.owner,
                             kind="rule", content="无来源不能入库", source=source)
        self.assertEqual([], self.store.review_candidates(self.owner))
        record = self.approved("重启后保留已批准规则", kind="rule", scope="tenant")
        self.store.close()
        self.store.close()
        self.assert_code("KNOWLEDGE_STORE_CLOSED", self.store.get, self.owner, record["id"])
        self.store = KnowledgeStore(self.path, owner_ids=self.owners)
        retrieved = self.store.search(self.colleague, "重启")
        self.assertEqual([record["id"]], [r["id"] for r in retrieved])
        self.assertEqual(self.source, retrieved[0]["source"])


if __name__ == "__main__":
    unittest.main()
