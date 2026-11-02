"""Real SQLite import tests: idempotence, rollback, scopes and zero-write plans."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from am_conversation.knowledge import KnowledgeStore
from am_conversation.learning import KnowledgeImporter
from am_conversation.types import AccessContext, ConversationError


class KnowledgeImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "learning.sqlite3"
        self.owners = {("tenant-a", "app-a"): {"owner"}, ("tenant-b", "app-a"): {"owner"}}
        self.ctx = AccessContext("tenant-a", "app-a", "owner", "owner-chat", "thread-a",
                                 frozenset({"project-a"}), is_owner=True)
        self.store = KnowledgeStore(self.path, owner_ids=self.owners)
        self.importer = KnowledgeImporter(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def item(self, key="rule.one", content="合成规则：验收前核查证据", **changes):
        return {"item_key": key, "kind": "rule", "scope": "tenant", "content": content,
                "source": {"uri": "synthetic://sample/rule", "observed_at": "2026-10-30T09:00:00+08:00",
                           "version": "v1"}, **changes}

    @staticmethod
    def lines(*items):
        return "\n".join(json.dumps(item, ensure_ascii=False) for item in items)

    def run_import(self, *items, **options):
        return self.importer.import_jsonl(self.ctx, self.lines(*items), **options)

    def test_default_import_is_candidate_and_explicit_owner_flag_can_approve(self):
        report = self.run_import(self.item())
        self.assertTrue(report["ok"])
        self.assertEqual(1, report["counts"]["created"])
        record = report["results"][0]
        self.assertEqual("candidate", record["status"])
        self.assertEqual([], self.store.search(self.ctx, "验收"))
        approved = self.run_import(self.item(), approve=True)
        self.assertEqual(1, approved["counts"]["unchanged"])
        self.assertEqual(1, approved["counts"]["approved"])
        self.assertEqual(record["record_id"], approved["results"][0]["record_id"])
        self.assertEqual(record["record_id"], self.store.search(self.ctx, "验收")[0]["id"])

    def test_duplicates_do_not_create_versions_in_same_file_or_after_restart(self):
        report = self.run_import(self.item(), self.item(), approve=True)
        self.assertEqual((1, 1, 1), (report["counts"]["created"], report["counts"]["unchanged"],
                                    report["counts"]["approved"]))
        self.assertEqual(1, report["results"][1]["version"])
        self.store.close()
        self.store = KnowledgeStore(self.path, owner_ids=self.owners)
        self.importer = KnowledgeImporter(self.store)
        repeated = self.run_import(self.item(), approve=True)
        self.assertEqual("unchanged", repeated["results"][0]["action"])
        self.assertEqual(report["results"][0]["record_id"], repeated["results"][0]["record_id"])
        self.assertEqual(0, repeated["counts"]["approved"])

    def test_changed_content_waits_for_new_approval_and_preserves_old_source(self):
        first = self.run_import(self.item(), approve=True)["results"][0]
        revised = self.item(content="合成规则：验收前还须核查本次测试记录")
        revised["source"]["version"] = "v2"
        report = self.run_import(revised)
        self.assertEqual(1, report["counts"]["updated"])
        second = report["results"][0]
        self.assertEqual((2, "candidate"), (second["version"], second["status"]))
        self.assertEqual([first["record_id"]], [r["id"] for r in self.store.search(self.ctx, "合成规则")])
        self.run_import(revised, approve=True)
        self.assertEqual([second["record_id"]], [r["id"] for r in self.store.search(self.ctx, "合成规则")])
        self.assertEqual("v1", self.store.get(self.ctx, first["record_id"])["source"]["version"])
        self.assertEqual("v2", self.store.get(self.ctx, second["record_id"])["source"]["version"])

    def test_historical_content_is_not_recreated_or_silently_reactivated(self):
        first = self.run_import(self.item(), approve=True)["results"][0]
        revised = self.item(content="合成规则：使用新版本的验收条件")
        second = self.run_import(revised, approve=True)["results"][0]
        old_file = self.run_import(self.item())
        self.assertEqual("unchanged", old_file["results"][0]["action"])
        self.assertTrue(old_file["results"][0]["historical"])
        self.assertEqual(first["record_id"], old_file["results"][0]["record_id"])
        self.assertIn("IMPORT_HISTORICAL_CONTENT_NOT_REAPPLIED", old_file["results"][0]["warnings"])
        forced = self.run_import(self.item(), approve=True)
        self.assertFalse(forced["ok"])
        self.assertEqual("IMPORT_HISTORICAL_VERSION", forced["results"][0]["error"])
        self.assertEqual([second["record_id"]], [r["id"] for r in self.store.search(self.ctx, "合成规则")])
        self.assertEqual([], self.store.review_candidates(self.ctx))

    def test_dry_run_does_not_create_index_or_change_any_database_record(self):
        before = "\n".join(self.store._db.iterdump())
        changes_before = self.store._db.total_changes
        report = self.run_import(self.item(), self.item(), approve=True, dry_run=True)
        self.assertTrue(report["ok"])
        self.assertEqual({"created": 1, "updated": 0, "approved": 1}, report["planned"])
        self.assertEqual(0, report["counts"]["created"])
        self.assertEqual(1, report["counts"]["unchanged"])
        self.assertEqual([None, None], [r["record_id"] for r in report["results"]])
        self.assertTrue(all(not r["persisted"] for r in report["results"]))
        self.assertEqual(before, "\n".join(self.store._db.iterdump()))
        self.assertEqual(changes_before, self.store._db.total_changes)
        actual = self.run_import(self.item(), approve=True)["results"][0]
        before = "\n".join(self.store._db.iterdump())
        revised = self.item(content="新候选内容保持旧版直到批准")
        planned = self.run_import(revised, revised, dry_run=True)
        self.assertEqual(1, planned["planned"]["updated"])
        self.assertEqual(2, planned["results"][0]["version"])
        self.assertEqual(before, "\n".join(self.store._db.iterdump()))
        self.assertEqual(actual["record_id"], self.store.search(self.ctx, "验收")[0]["id"])

    def test_file_cannot_supply_principal_permissions_or_approval_commands(self):
        fields = {"tenant_id": "other", "app_id": "other", "actor_id": "owner",
                  "is_owner": True, "owner": True, "allowed_project_ids": ["other"],
                  "all_projects": True, "ctx": {}, "approve": True, "status": "approved"}
        items = [self.item(key=f"bad.{name}", **{name: value}) for name, value in fields.items()]
        report = self.run_import(*items)
        self.assertFalse(report["ok"])
        self.assertEqual(len(fields), report["counts"]["errors"])
        self.assertEqual({"IMPORT_INVALID_FIELDS"}, {r["error"] for r in report["results"]})
        self.assertEqual([], self.store.review_candidates(self.ctx))
        self.assertEqual("tenant-a", self.ctx.tenant_id)

    def test_colleague_import_cannot_share_facts_or_self_approve(self):
        colleague = replace(self.ctx, actor_id="engineer", is_owner=False)
        private = self.item(key="private.fact", kind="fact", scope="private")
        denied_shared = self.item(key="shared.fact", kind="fact", scope="project", project_id="project-a")
        report = self.importer.import_jsonl(colleague, self.lines(private, denied_shared))
        self.assertEqual((1, 1), (report["counts"]["created"], report["counts"]["errors"]))
        self.assertEqual("KNOWLEDGE_OWNER_REQUIRED", report["results"][1]["error"])
        record_id = report["results"][0]["record_id"]
        self.assertEqual("candidate", self.store.get(colleague, record_id)["status"])
        for ctx in (colleague, replace(colleague, is_owner=True)):
            result = self.importer.import_jsonl(ctx, self.lines(self.item(key="cannot.approve", kind="fact", scope="private")),
                                                approve=True)
            self.assertEqual("KNOWLEDGE_OWNER_REQUIRED", result["results"][0]["error"])
        self.assertEqual(1, len(self.store.review_candidates(colleague)))
        self.assertEqual([], self.store.review_candidates(self.ctx))

    def test_key_cannot_change_scope_or_cross_a_private_session(self):
        private = self.item(scope="private")
        original = self.run_import(private, approve=True)["results"][0]
        shared_attempt = self.run_import(self.item())
        self.assertEqual("IMPORT_ITEM_DEFINITION_CHANGED", shared_attempt["results"][0]["error"])
        other_chat = replace(self.ctx, chat_id="other-chat")
        inaccessible = self.importer.import_jsonl(other_chat, self.lines(private), approve=True)
        self.assertEqual("KNOWLEDGE_NOT_FOUND", inaccessible["results"][0]["error"])
        self.assertNotIn("record_id", inaccessible["results"][0])
        self.assertEqual("private", self.store.get(self.ctx, original["record_id"])["scope"])
        project_item = self.item(key="project.rule", scope="project", project_id="project-a")
        self.run_import(project_item, approve=True)
        reduced = replace(self.ctx, allowed_project_ids=frozenset())
        hidden = self.importer.import_jsonl(reduced, self.lines(project_item), dry_run=True)
        self.assertEqual("PROJECT_FORBIDDEN", hidden["results"][0]["error"])

    def test_each_failed_line_is_reported_and_later_valid_lines_still_import(self):
        importer = KnowledgeImporter(self.store, max_line_bytes=1024)
        inputs = [b"not-json\n", b"\xff\n", b"x" * 2000,
                  self.lines(self.item(key="valid.one")),
                  '{"item_key":"duplicate","kind":"fact","kind":"rule","content":"x","source":{}}',
                  self.lines(self.item(key="valid.two"))]
        report = importer.import_jsonl(self.ctx, inputs)
        self.assertFalse(report["ok"])
        self.assertTrue(report["complete"])
        self.assertEqual((2, 4), (report["counts"]["created"], report["counts"]["errors"]))
        self.assertEqual([1, 2, 3, 4, 5, 6], [r["line"] for r in report["results"]])
        self.assertEqual("IMPORT_DUPLICATE_JSON_FIELD", report["results"][4]["error"])
        self.assertEqual(2, len(self.store.review_candidates(self.ctx)))

    def test_failed_approval_rolls_back_both_record_and_deduplication_mapping(self):
        with patch.object(self.store, "approve", side_effect=ConversationError("SIMULATED_APPROVAL_FAILURE")):
            failed = self.run_import(self.item(), approve=True)
        self.assertEqual("SIMULATED_APPROVAL_FAILURE", failed["results"][0]["error"])
        self.assertEqual([], self.store.review_candidates(self.ctx))
        self.assertEqual([], self.store.search(self.ctx, "验收"))
        retry = self.run_import(self.item(), approve=True)
        self.assertEqual(1, retry["counts"]["created"])
        self.assertEqual(1, retry["results"][0]["version"])

    def test_concurrent_imports_create_one_logical_object(self):
        stores = [KnowledgeStore(self.path, owner_ids=self.owners) for _ in range(2)]
        importers = [KnowledgeImporter(store) for store in stores]
        barrier = threading.Barrier(2)

        def run(index):
            barrier.wait(timeout=5)
            return importers[index].import_jsonl(self.ctx, self.lines(self.item()), approve=True)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                reports = list(pool.map(run, range(2)))
        finally:
            for store in stores:
                store.close()
        self.assertTrue(all(report["ok"] for report in reports))
        self.assertEqual(1, sum(r["counts"]["created"] for r in reports))
        self.assertEqual(1, sum(r["counts"]["unchanged"] for r in reports))
        self.assertEqual(reports[0]["results"][0]["record_id"], reports[1]["results"][0]["record_id"])
        self.assertEqual(1, len(self.store.search(self.ctx, "验收")))

    def test_import_identity_is_scoped_by_tenant_application_and_namespace(self):
        original = self.run_import(self.item(), approve=True)["results"][0]
        namespace = self.run_import(self.item(), namespace="another", approve=True)["results"][0]
        other_ctx = replace(self.ctx, tenant_id="tenant-b")
        tenant = self.importer.import_jsonl(other_ctx, self.lines(self.item()), approve=True)["results"][0]
        self.assertEqual(3, len({original["record_id"], namespace["record_id"], tenant["record_id"]}))
        self.assertEqual([tenant["record_id"]], [r["id"] for r in self.store.search(other_ctx, "验收")])

    def test_file_reader_drains_large_lines_and_keeps_physical_line_numbers(self):
        path = Path(self.temp.name) / "sample.jsonl"
        path.write_bytes(b"x" * 20000 + b"\n" + self.lines(self.item()).encode("utf-8") + b"\n")
        report = KnowledgeImporter(self.store, max_line_bytes=1024).import_file(self.ctx, path)
        self.assertEqual("IMPORT_LINE_TOO_LARGE", report["results"][0]["error"])
        self.assertEqual(2, report["results"][1]["line"])
        self.assertEqual(1, report["counts"]["created"])

    def test_item_limit_also_bounds_malformed_inputs_and_reports_incomplete(self):
        report = KnowledgeImporter(self.store, max_items=2).import_jsonl(self.ctx, ["bad"] * 100)
        self.assertFalse(report["complete"])
        self.assertEqual(3, report["processed"])
        self.assertEqual("IMPORT_ITEM_LIMIT", report["results"][-1]["error"])

    def test_same_content_with_new_source_does_not_falsify_original_provenance(self):
        original = self.run_import(self.item(), approve=True)["results"][0]
        reread = self.item()
        reread["source"]["observed_at"] = "2026-10-31T09:00:00+08:00"
        reread["source"]["version"] = "v2"
        report = self.run_import(reread)
        self.assertEqual("unchanged", report["results"][0]["action"])
        self.assertIn("IMPORT_UNCHANGED_SOURCE_RETAINED", report["results"][0]["warnings"])
        source = self.store.get(self.ctx, original["record_id"])["source"]
        self.assertEqual("v1", source["version"])

    def test_packaged_examples_are_synthetic_and_importable(self):
        example = Path(__file__).resolve().parents[1] / "examples" / "knowledge.example.jsonl"
        report = self.importer.import_file(self.ctx, example, approve=True)
        self.assertTrue(report["ok"])
        self.assertEqual(2, report["counts"]["created"])
        records = [self.store.get(self.ctx, row["record_id"]) for row in report["results"]]
        self.assertTrue(all(record["source"]["uri"].startswith("synthetic://") for record in records))


if __name__ == "__main__":
    unittest.main()
