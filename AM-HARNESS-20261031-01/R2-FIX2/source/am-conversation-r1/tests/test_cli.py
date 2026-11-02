"""Local command tests using synthetic administrator configurations only."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from am_conversation.cli import DEMO_NOTICE, import_knowledge, load_import_config, main, run_demo
from am_conversation.knowledge import KnowledgeStore
from am_conversation.types import ConversationError


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "administrator.json"
        self.data_path = self.root / "knowledge.jsonl"
        self.config = {"tenant_id": "synthetic-tenant", "app_id": "synthetic-app",
                       "actor_id": "synthetic-admin", "chat_id": "synthetic-private-chat",
                       "owner_ids": ["synthetic-admin"], "allowed_project_ids": ["synthetic-project"],
                       "all_projects": False, "database": "knowledge.sqlite3"}
        self.item = {"item_key": "synthetic.rule", "kind": "rule", "scope": "tenant",
                     "content": "合成规则：测试记录需有可核对的来源。",
                     "source": {"uri": "synthetic://cli/rule", "observed_at": "2026-10-30T09:00:00+08:00"}}
        self.write_config()
        self.write_items(self.item)

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def write_items(self, *items):
        self.data_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in items), encoding="utf-8")

    def invoke(self, arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(arguments)
        return code, json.loads(output.getvalue())

    def import_args(self, *options):
        return ["import-knowledge", "--config", str(self.config_path), "--file", str(self.data_path), *options]

    def test_demo_runs_real_state_transitions_without_network(self):
        with patch("socket.socket", side_effect=AssertionError("NETWORK_FORBIDDEN")):
            result = run_demo()
        self.assertEqual(DEMO_NOTICE, result["notice"])
        self.assertTrue(result["ok"])
        self.assertTrue(all(result["checks"].values()))
        observed = result["observed"]
        self.assertEqual(2, len(observed["notes_after_restart"]))
        self.assertEqual({row["id"] for row in observed["notes_before_restart"]},
                         {row["id"] for row in observed["notes_after_restart"]})
        self.assertEqual(1, len(observed["executions"]))
        self.assertEqual("succeeded", observed["executed_action"]["status"])
        self.assertEqual("cancelled", observed["cancelled_action"]["status"])
        self.assertEqual(2, observed["executed_action"]["version"])
        replay = next(step for step in result["steps"] if step["name"] == "同一事件重放")
        self.assertTrue(replay["reply"]["replayed"])
        self.assertEqual(0, replay["model_calls"])

    def test_module_entrypoint_json_is_parseable_and_reports_success(self):
        package_root = Path(__file__).resolve().parents[1]
        env = {**os.environ, "PYTHONPATH": str(package_root / "src")}
        process = subprocess.run([sys.executable, "-m", "am_conversation", "demo", "--json"],
                                 cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(DEMO_NOTICE, result["notice"])
        self.assertTrue(result["ok"])

    def test_demo_failure_does_not_return_zero_or_fabricate_all_checks_passed(self):
        with patch("am_conversation.cli.run_demo", return_value={
                "ok": False, "notice": DEMO_NOTICE, "checks": {"persisted": False}}):
            code, result = self.invoke(["demo", "--json"])
        self.assertEqual(1, code)
        self.assertFalse(result["ok"])

    def test_config_derives_owner_from_ids_and_resolves_database_relative_to_config(self):
        ctx, owners, path = load_import_config(self.config_path)
        self.assertTrue(ctx.is_owner)
        self.assertEqual({"synthetic-admin"}, owners[(ctx.tenant_id, ctx.app_id)])
        self.assertEqual((self.root / "knowledge.sqlite3").resolve(), path)
        self.config["actor_id"] = "synthetic-member"
        self.write_config()
        ctx, _, _ = load_import_config(self.config_path)
        self.assertFalse(ctx.is_owner)

    def test_explicit_import_approval_and_partial_errors_have_correct_exit_codes(self):
        code, report = self.invoke(self.import_args())
        self.assertEqual(0, code)
        self.assertEqual("candidate", report["results"][0]["status"])
        code, approved = self.invoke(self.import_args("--approve"))
        self.assertEqual(0, code)
        self.assertEqual(1, approved["counts"]["approved"])
        self.assertEqual(report["results"][0]["record_id"], approved["results"][0]["record_id"])
        self.data_path.write_text("invalid-json\n" + json.dumps({**self.item, "item_key": "another.rule"}), encoding="utf-8")
        code, partial = self.invoke(self.import_args())
        self.assertEqual(1, code)
        self.assertFalse(partial["ok"])
        self.assertEqual((1, 1), (partial["counts"]["created"], partial["counts"]["errors"]))

    def test_new_database_dry_run_does_not_create_file_or_parent_directory(self):
        self.config["database"] = "not-created/subdirectory/knowledge.sqlite3"
        self.write_config()
        code, report = self.invoke(self.import_args("--dry-run", "--approve"))
        self.assertEqual(0, code)
        self.assertEqual("memory_dry_run", report["database_mode"])
        self.assertEqual(1, report["planned"]["created"])
        self.assertEqual(0, report["counts"]["created"])
        self.assertFalse((self.root / "not-created").exists())

    def test_existing_database_dry_run_preserves_bytes_and_versions(self):
        actual = import_knowledge(self.config_path, self.data_path, approve=True)
        ident = actual["results"][0]["record_id"]
        database = self.root / "knowledge.sqlite3"
        before = database.read_bytes()
        self.write_items({**self.item, "content": "修改后的合成候选规则，不应写入原库。"})
        code, planned = self.invoke(self.import_args("--dry-run", "--approve"))
        self.assertEqual(0, code)
        self.assertEqual((1, 1), (planned["planned"]["updated"], planned["planned"]["approved"]))
        self.assertEqual(before, database.read_bytes())
        ctx, owners, _ = load_import_config(self.config_path)
        with KnowledgeStore(database, owner_ids=owners) as store:
            self.assertEqual([], store.review_candidates(ctx))
            self.assertEqual([ident], [row["id"] for row in store.search(ctx, "合成规则")])
            self.assertEqual(1, store.get(ctx, ident)["version"])

    def test_config_identity_overrides_and_placeholders_are_rejected_without_writes(self):
        original = dict(self.config)
        cases = [({"is_owner": True}, "CONFIG_INVALID_FIELDS"),
                 ({"tenant_id": "YOUR_TENANT_ID"}, "CONFIG_PLACEHOLDER_VALUE"),
                 ({"actor_id": "<actor-id>"}, "CONFIG_PLACEHOLDER_VALUE"),
                 ({"database": "REPLACE_ME/knowledge.sqlite3"}, "CONFIG_PLACEHOLDER_VALUE"),
                 ({"owner_ids": ["TODO"]}, "CONFIG_PLACEHOLDER_VALUE"),
                 ({"chat_id": "CHANGE_ME"}, "CONFIG_PLACEHOLDER_VALUE"),
                 ({"all_projects": 1}, "CONFIG_INVALID_VALUE"),
                 ({"api_key": "not-a-real-credential"}, "CONFIG_INVALID_FIELDS")]
        for updates, expected in cases:
            with self.subTest(fields=sorted(updates)):
                self.config = {**original, **updates}
                self.write_config()
                code, result = self.invoke(self.import_args("--approve"))
                self.assertEqual(2, code)
                self.assertEqual(expected, result["error"])
                self.assertFalse((self.root / "knowledge.sqlite3").exists())

    def test_member_cannot_use_cli_approve_to_elevate_authority(self):
        self.config["actor_id"] = "synthetic-member"
        self.write_config()
        self.write_items({**self.item, "kind": "fact", "scope": "private"})
        code, result = self.invoke(self.import_args("--approve"))
        self.assertEqual(1, code)
        self.assertEqual("KNOWLEDGE_OWNER_REQUIRED", result["results"][0]["error"])
        code, candidate = self.invoke(self.import_args())
        self.assertEqual(0, code)
        self.assertEqual(1, candidate["counts"]["created"])
        self.assertEqual("candidate", candidate["results"][0]["status"])

    def test_jsonl_cannot_override_administrator_context(self):
        self.write_items({**self.item, "tenant_id": "injected-tenant", "is_owner": True})
        code, result = self.invoke(self.import_args("--approve"))
        self.assertEqual(1, code)
        self.assertEqual("IMPORT_INVALID_FIELDS", result["results"][0]["error"])

    def test_invalid_existing_database_dry_run_reports_error_without_replacing_it(self):
        database = self.root / "knowledge.sqlite3"
        database.write_bytes(b"not a sqlite database")
        before = database.read_bytes()
        code, result = self.invoke(self.import_args("--dry-run"))
        self.assertEqual(2, code)
        self.assertEqual("IMPORT_DATABASE_UNAVAILABLE", result["error"])
        self.assertEqual(before, database.read_bytes())


if __name__ == "__main__":
    unittest.main()
