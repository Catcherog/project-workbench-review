"""Original-AM port contract tests with synthetic data; no live Feishu sends."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import uuid

from am_conversation.legacy import LegacyConversationBridge, _hash
from am_conversation.tools import Tool, obj, string
from am_conversation.types import AccessContext, ConversationError, canonical


class SourceLoading(Exception):
    pass


class OriginalStore:
    """Only the original Store interfaces/schema used by this adapter."""
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = time.time
        self.conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE am_inbox(id TEXT PRIMARY KEY,app TEXT,tenant TEXT,user TEXT,chat TEXT,
                chat_type TEXT,created REAL,expires REAL,body TEXT,kind TEXT,state TEXT,error TEXT);
            CREATE TABLE outbox(id TEXT PRIMARY KEY,app TEXT,tenant TEXT,user TEXT,chat TEXT,
                chat_type TEXT,kind TEXT,body TEXT,expires REAL,state TEXT DEFAULT 'pending',message_id TEXT);
            CREATE TABLE am_outbox_events(outbox_id TEXT PRIMARY KEY,event_id TEXT);
            CREATE TABLE am_query_deliveries(outbox_id TEXT PRIMARY KEY,scope_hash TEXT,denial INTEGER);
            CREATE TABLE action_items(id TEXT PRIMARY KEY,version INTEGER,owner TEXT,project_ref TEXT,
                description TEXT,requirements TEXT,assignees TEXT,deadline TEXT,deadline_kind TEXT,
                timezone TEXT,state TEXT,paused INTEGER,updated REAL,latest_feedback TEXT);
        """)

    @contextmanager
    def tx(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def execute(self, sql, args=()):
        with self.tx() as conn:
            return conn.execute(sql, args).rowcount

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(row) for row in self.conn.execute(sql, args)]


class CoordinatorStub:
    def __init__(self):
        self.outputs = []
        self.calls = []
        self.callback = None

    def complete(self, prompt, **options):
        self.calls.append((prompt, options))
        if self.callback:
            self.callback()
        output = self.outputs.pop(0) if self.outputs else {"type": "answer", "text": "这条合成信息还需要进一步核对。"}
        return SimpleNamespace(text=json.dumps(output, ensure_ascii=False))


def call(name, arguments):
    return {"type": "tool_calls", "tool_calls": [{"id": uuid.uuid4().hex, "name": name, "arguments": arguments}]}


def answer(text):
    return {"type": "answer", "text": text}


class FakeService:
    def __init__(self, root):
        self.s = OriginalStore()
        self.owner = "ou_owner"
        self.g = SimpleNamespace(config=SimpleNamespace(root=root, app_id="app-test", tenant_key="tenant-test", owner=self.owner),
                                 provider=CoordinatorStub())
        self.flags = {"query": True, "items": True}
        self.revoked = False
        self.management_allowed = True
        self.management_checks = []
        self.grant_calls = []
        self.grants = {"ou_member": ["需求1"], "ou_other": ["需求2"]}
        self.ledger = SimpleNamespace(port=SimpleNamespace(authorize_user=self.authorize_user))
        self.meta = {}
        self.loading = False
        self.wait_calls = []
        self.snapshots = SimpleNamespace(get=self.wait_snapshot)
        self.projects = [
            {"key": "project-a", "title": "需求1 合成项目Aurora", "business_id": "需求1", "identity_status": "verified",
             "项目进展": "测试资料待整理", "关键日期": "2026-11-02 报告检查", "人员与职责": "合成人员甲：测试", "待办": "整理报告"},
            {"key": "project-b", "title": "需求2 合成项目Borealis", "business_id": "需求2", "identity_status": "verified",
             "项目进展": "仅项目B可见的合成资料", "关键日期": "2026-11-03 设计检查"},
        ]

    def authorize_user(self, actor):
        self.management_checks.append(actor)
        if not self.management_allowed or actor != self.owner:
            raise ConversationError("MANAGEMENT_REVOKED")

    def source_meta(self, row):
        return self.meta.get(row["id"], {})

    def query_grant(self, row, *, verify=True):
        self.grant_calls.append(row["user"])
        if verify and self.revoked:
            raise ConversationError("QUERY_IDENTITY_REVOKED")
        if row["user"] == self.owner:
            return ["*"]
        value = self.grants.get(row["user"])
        if not value:
            raise ConversationError("PRIVATE_QUERY_SCOPE_MISSING")
        return list(value)

    def query_projects(self, row):
        if self.loading:
            raise SourceLoading("SOURCE_LOADING")
        grant = row["_query_grant"]
        row["_snapshot_version"] = "snapshot-1"
        row["_observed_at"] = 1793322000.0
        row["_snapshot_meta"] = {"version": "snapshot-1", "observed_at": row["_observed_at"],
                                 "complete": True, "stale": False, "source": "synthetic-source"}
        return [dict(project) for project in self.projects if "*" in grant or project["business_id"] in grant]

    def wait_snapshot(self, version=None, *, wait=True):
        self.wait_calls.append(wait)
        self.loading = False
        return {"version": "snapshot-1"}

    def notify(self, row, text=None, *, card=None, kind="status", conn=None, event_key=None):
        if card is not None:
            raise AssertionError("Conversation bridge must not create a card")
        if conn is None:
            with self.s.tx() as connection:
                return self.notify(row, text, card=card, kind=kind, conn=connection, event_key=event_key)
        ident = uuid.uuid4().hex
        conn.execute("INSERT INTO outbox(id,app,tenant,user,chat,chat_type,kind,body,expires) VALUES(?,?,?,?,?,'p2p','text',?,?)",
                     (ident, row["app"], row["tenant"], row["user"], row["chat"], text, row["expires"]))
        conn.execute("INSERT INTO am_outbox_events VALUES(?,?)", (ident, row["id"]))
        if row.get("_query_read") or row.get("_query_denial"):
            conn.execute("INSERT INTO am_query_deliveries VALUES(?,?,?)", (ident, _hash(row.get("_query_grant", [])), bool(row.get("_query_denial"))))
        return ident

    def query_delivery_authorized(self, row):
        notes = self.s.rows("SELECT * FROM am_query_deliveries WHERE outbox_id=?", (row["id"],))
        if not notes:
            return None
        original = self.s.rows("SELECT i.* FROM am_inbox i JOIN am_outbox_events e ON e.event_id=i.id WHERE e.outbox_id=?", (row["id"],))
        if not original or any(original[0][k] != row[k] for k in ("app", "tenant", "user", "chat")) or row["expires"] <= self.s.clock():
            return False
        if notes[0]["denial"]:
            return True
        try:
            return notes[0]["scope_hash"] == _hash(sorted(set(self.query_grant(row))))
        except Exception:
            return False

    def inbox(self, actor="ou_member", text="Aurora现在怎么样了？", *, event=None, thread=""):
        row = {"id": event or uuid.uuid4().hex, "app": "app-test", "tenant": "tenant-test", "user": actor,
               "chat": "chat-" + actor, "chat_type": "p2p", "created": self.s.clock(),
               "expires": self.s.clock() + 86400, "body": text, "kind": "conversation", "state": "received", "error": None}
        self.s.execute("INSERT INTO am_inbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", tuple(row.values()))
        self.meta[row["id"]] = {"thread": thread}
        return row

    def deliver(self, bridge, outbox_id, message_id="om-synthetic"):
        row = self.s.rows("SELECT * FROM outbox WHERE id=?", (outbox_id,))[0]
        if not self.query_delivery_authorized(row):
            return False
        # Stand-in for the original gateway's post-send/readback transaction.
        with self.s.tx() as conn:
            conn.execute("UPDATE outbox SET state='sent',message_id=? WHERE id=?", (message_id, outbox_id))
            return bridge.delivered(row, message_id, conn=conn)


class LegacyBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = FakeService(Path(self.temp.name))
        self.bridge = LegacyConversationBridge(self.service, {"enabled": True})

    def tearDown(self):
        self.bridge.close()
        self.service.s.conn.close()
        self.temp.cleanup()

    def output_context(self, outbox_id):
        row = self.service.s.rows("SELECT context FROM am_conversation_outputs WHERE outbox_id=?", (outbox_id,))[0]
        return AccessContext(**json.loads(row["context"]))

    def test_disabled_mode_creates_no_state_and_preserves_slash_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = FakeService(Path(temporary))
            disabled = LegacyConversationBridge(service, {})
            self.assertFalse(disabled.wants("项目进展"))
            self.assertFalse((Path(temporary) / "state").exists())
            with self.assertRaisesRegex(ConversationError, "^CONVERSATION_DISABLED$"):
                disabled.process(service.inbox())
            disabled.close()
            service.s.conn.close()
        self.assertTrue(self.bridge.wants("测试做到哪了"))
        self.assertFalse(self.bridge.wants("/project 需求1"))
        self.assertFalse(self.bridge.wants(" /help"))
        self.assertFalse(self.bridge.wants("  "))

    def test_member_query_reuses_authorized_project_snapshot_and_text_outbox(self):
        self.service.g.provider.outputs = [call("read_project", {"project_id": "project-a"}), answer("Aurora目前在整理测试资料，接下来检查报告。")]
        outbox = self.bridge.process(self.service.inbox())
        stored = self.service.s.rows("SELECT * FROM outbox WHERE id=?", (outbox,))[0]
        ctx = self.output_context(outbox)
        self.assertEqual(stored["kind"], "text")
        self.assertEqual(ctx.allowed_project_ids, frozenset({"project-a"}))
        self.assertFalse(ctx.is_owner)
        self.assertFalse(ctx.all_projects)
        self.assertTrue(self.service.query_delivery_authorized(stored))
        self.assertIn("snapshot-1", self.service.g.provider.calls[-1][0])
        self.assertNotIn("仅项目B可见的合成资料", self.service.g.provider.calls[-1][0])
        self.assertFalse(self.service.management_checks)
        self.assertEqual({tool.effect for tool in self.bridge.registry._tools.values()}, {"read", "local"})

    def test_cold_snapshot_waits_in_worker_without_card_fallback(self):
        self.service.loading = True
        row = self.service.inbox()
        outbox = self.bridge.process(row)
        self.assertEqual(self.service.wait_calls, [True])
        self.assertIn("_conversation_source_wait_seconds", row)
        self.assertEqual(self.service.s.rows("SELECT kind FROM outbox WHERE id=?", (outbox,))[0]["kind"], "text")

    def test_repeated_event_does_not_generate_or_enqueue_twice(self):
        row = self.service.inbox()
        first = self.bridge.process(row)
        second = self.bridge.process(dict(row))
        self.assertEqual(first, second)
        self.assertEqual(len(self.service.g.provider.calls), 1)
        self.assertEqual(len(self.service.s.rows("SELECT * FROM outbox")), 1)
        with self.assertRaisesRegex(ConversationError, "^CONVERSATION_EVENT_CONFLICT$"):
            self.bridge.process(dict(row, body="同一个事件伪造了不同正文"))

    def test_revocation_after_model_prevents_outgoing_reply(self):
        self.service.g.provider.callback = lambda: setattr(self.service, "revoked", True)
        with self.assertRaisesRegex(ConversationError, "^QUERY_IDENTITY_REVOKED$"):
            self.bridge.process(self.service.inbox())
        self.assertFalse(self.service.s.rows("SELECT * FROM outbox"))

    def test_scope_change_after_model_does_not_disclose_original_scope(self):
        self.service.g.provider.callback = lambda: self.service.grants.update({"ou_member": ["需求2"]})
        with self.assertRaisesRegex(ConversationError, "^CONVERSATION_SCOPE_CHANGED$"):
            self.bridge.process(self.service.inbox())
        self.assertFalse(self.service.s.rows("SELECT * FROM outbox"))

    def test_management_uses_live_owner_check_even_with_query_grant(self):
        self.service.management_allowed = False
        self.service.g.provider.outputs = [call("save_work_note", {"project_id": "project-a", "title": "合成工作事项"}), answer("当前尚未保存这个工作事项。")]
        outbox = self.bridge.process(self.service.inbox("ou_owner", "记下报告检查"))
        ctx = self.output_context(outbox)
        self.assertTrue(self.service.management_checks)
        self.assertEqual(set(self.service.management_checks), {"ou_owner"})
        self.assertEqual(self.bridge.store.list_tasks(ctx), [])

    def test_group_or_other_tenant_cannot_enter_private_conversation(self):
        for changes in ({"chat_type": "group"}, {"tenant": "different-tenant"}, {"app": "different-app"}):
            row = self.service.inbox()
            with self.assertRaisesRegex(ConversationError, "^CONVERSATION_IDENTITY_INVALID$"):
                self.bridge.process(dict(row, **changes))
        self.assertFalse(self.service.g.provider.calls)

    def test_thread_identity_is_not_shared(self):
        first = self.bridge.process(self.service.inbox(thread="thread-a"))
        second = self.bridge.process(self.service.inbox(thread="thread-b"))
        left, right = self.output_context(first), self.output_context(second)
        self.assertNotEqual(left.session_id, right.session_id)
        self.assertEqual(left.thread_id, "thread-a")
        self.assertEqual(right.thread_id, "thread-b")

    def test_delivery_revocation_keeps_original_outbox_blocked(self):
        outbox = self.bridge.process(self.service.inbox())
        self.service.revoked = True
        self.assertFalse(self.service.deliver(self.bridge, outbox))
        saved = self.service.s.rows("SELECT state FROM am_conversation_outputs WHERE outbox_id=?", (outbox,))[0]
        self.assertEqual(saved["state"], "pending")

    def test_preview_ack_requires_exact_completed_delivery(self):
        # Synthetic external tool exists only in this test to exercise the
        # generic preview contract. Production LegacyConversationBridge has none.
        self.bridge.registry.register(Tool("synthetic_send", "合成发送工具", obj({"project_id": string()}, ("project_id",)),
            lambda *_: self.fail("No external tool may execute in this test"), "external", True,
            preview=lambda _ctx, _args: "合成目标：本人\n合成正文：请核对资料。"))
        self.service.g.provider.outputs = [call("synthetic_send", {"project_id": "project-a"})]
        outbox = self.bridge.process(self.service.inbox("ou_owner", "准备一条合成提醒"))
        ctx = self.output_context(outbox)
        action = self.bridge.store.list_actions(ctx)[0]
        row = self.service.s.rows("SELECT * FROM outbox WHERE id=?", (outbox,))[0]
        self.assertIsNone(action["presented_version"])
        self.assertFalse(self.bridge.delivered(row, "om-not-yet-sent"))
        self.assertIsNone(self.bridge.store.get_action(ctx, action["id"])["presented_version"])
        self.assertTrue(self.service.deliver(self.bridge, outbox))
        self.assertEqual(self.bridge.store.get_action(ctx, action["id"])["presented_version"], 1)
        self.assertFalse(self.bridge.delivered(dict(row, user="ou_other"), "om-synthetic"))
        self.assertFalse(self.bridge.delivered(row, "om-wrong-message"))

    def test_old_delivered_preview_does_not_approve_revised_content(self):
        self.bridge.registry.register(Tool("synthetic_send", "合成发送工具", obj({"project_id": string()}, ("project_id",)),
            lambda *_: self.fail("No execution"), "external", True, preview=lambda _ctx, _args: "合成旧正文"))
        self.service.g.provider.outputs = [call("synthetic_send", {"project_id": "project-a"})]
        outbox = self.bridge.process(self.service.inbox("ou_owner", "准备合成消息"))
        ctx = self.output_context(outbox)
        action = self.bridge.store.list_actions(ctx)[0]
        self.bridge.store.revise_action(ctx, action["id"], expected_version=1,
                                       arguments={"project_id": "project-a"}, preview="合成新正文")
        self.assertTrue(self.service.deliver(self.bridge, outbox))
        revised = self.bridge.store.get_action(ctx, action["id"])
        self.assertEqual(revised["version"], 2)
        self.assertIsNone(revised["presented_version"])

    def test_followups_keep_assignment_and_project_boundaries(self):
        for ident, project, actors, owner in (("follow-a", "project-a", ["ou_member"], "ou_owner"),
                                              ("follow-b", "project-a", ["ou_other"], "ou_owner"),
                                              ("follow-c", "project-b", ["ou_member"], "ou_owner"),
                                              ("follow-d", "project-a", ["ou_other"], "different-owner")):
            self.service.s.execute("INSERT INTO action_items VALUES(?,1,?,?,'合成跟进','合成交付',?,NULL,'unspecified','Asia/Shanghai','waiting',0,1,NULL)",
                                   (ident, owner, project, canonical(actors)))
        self.service.g.provider.outputs = [call("list_followups", {}), answer("目前有一项已登记的合成跟进。")]
        self.bridge.process(self.service.inbox())
        prompt = self.service.g.provider.calls[-1][0]
        self.assertIn("follow-a", prompt)
        self.assertNotIn("follow-b", prompt)
        self.assertNotIn("follow-c", prompt)
        self.assertNotIn("follow-d", prompt)
        self.assertIn("am_followup", prompt)
        self.assertIn("private_work_notes", prompt)
        self.service.g.provider.outputs = [call("list_followups", {"project_id": "project-a"}), answer("已读取获准范围内的合成跟进。")]
        self.bridge.process(self.service.inbox("ou_owner"))
        owner_prompt = self.service.g.provider.calls[-1][0]
        self.assertIn("follow-a", owner_prompt)
        self.assertIn("follow-b", owner_prompt)
        self.assertNotIn("follow-c", owner_prompt)
        self.assertNotIn("follow-d", owner_prompt)

    def test_external_execution_cannot_be_enabled_by_settings(self):
        with self.assertRaisesRegex(ConversationError, "^CONVERSATION_EXTERNAL_ACTIONS_UNBOUND$"):
            LegacyConversationBridge(self.service, {"enabled": True, "runtime": {"allow_external_actions": True}})

    def test_disabled_original_query_flag_is_not_bypassed(self):
        self.service.flags["query"] = False
        self.assertFalse(self.bridge.wants("查看项目"))
        with self.assertRaisesRegex(ConversationError, "^QUERY_NOT_ENABLED$"):
            self.bridge.process(self.service.inbox())
        with self.assertRaisesRegex(ConversationError, "^QUERY_NOT_ENABLED$"):
            LegacyConversationBridge(self.service, {"enabled": True})
        self.assertFalse(self.service.g.provider.calls)

    def test_replay_rechecks_grant_and_actual_project_capabilities(self):
        row = self.service.inbox()
        self.bridge.process(row)
        self.service.grants["ou_member"] = ["需求2"]
        with self.assertRaisesRegex(ConversationError, "^CONVERSATION_SCOPE_CHANGED$"):
            self.bridge.process(dict(row))
        self.service.grants["ou_member"] = ["需求1"]
        self.service.projects[0]["key"] = "project-a-remapped"
        with self.assertRaisesRegex(ConversationError, "^CONVERSATION_SCOPE_CHANGED$"):
            self.bridge.process(dict(row))
        self.assertEqual(len(self.service.s.rows("SELECT * FROM outbox")), 1)
        self.assertEqual(len(self.service.g.provider.calls), 1)

    def test_model_mentions_are_inert_in_history_outbox_and_ack_record(self):
        self.service.g.provider.outputs = [answer('请先核对 <at user_id="all">所有人</at> 这段引用。')]
        row = self.service.inbox()
        outbox = self.bridge.process(row)
        ctx = self.output_context(outbox)
        saved = self.service.s.rows("SELECT * FROM am_conversation_outputs WHERE outbox_id=?", (outbox,))[0]
        text = self.service.s.rows("SELECT body FROM outbox WHERE id=?", (outbox,))[0]["body"]
        history = self.bridge.store.history(ctx)
        self.assertNotIn("<at", text)
        self.assertNotIn("</at", text)
        self.assertIn("＜at", text)
        self.assertEqual(json.loads(saved["reply"])["text"], text)
        self.assertEqual(history[-1]["content"], text)
        self.assertEqual(self.bridge.store.claim_event(ctx, row["id"], row["body"])["reply"]["text"], text)
        self.assertTrue(self.service.deliver(self.bridge, outbox))

    def test_full_legacy_tool_catalog_fits_existing_schema_transport_limit(self):
        self.bridge.process(self.service.inbox("ou_owner"))
        schema = self.service.g.provider.calls[0][1]["json_schema"]
        schema_size = len(json.dumps(schema))
        self.assertLessEqual(schema_size, 20000)
        self.assertIn("list_followups", json.dumps(schema))

    def test_large_facts_get_context_reply_before_model_without_truncation(self):
        first = self.bridge.process(self.service.inbox("ou_owner"))
        ctx = self.output_context(first)
        details = "完整合成事实不能截断。" * 240
        for number in range(3):
            self.bridge.store.create_task(ctx, project_id="project-a", title="合成事项" + str(number), details=details)
        self.bridge.close()
        self.bridge = LegacyConversationBridge(self.service, {"enabled": True,
            "model": {"max_input_chars": 9000}, "runtime": {"max_context_chars": 26000}})
        self.service.g.provider.calls.clear()
        output = self.bridge.process(self.service.inbox("ou_owner", "合成事项现在怎么样？"))
        record = self.service.s.rows("SELECT reply FROM am_conversation_outputs WHERE outbox_id=?", (output,))[0]
        self.assertEqual(json.loads(record["reply"])["status"], "context_limit")
        self.assertFalse(self.service.g.provider.calls)
        self.assertEqual([task["details"] for task in self.bridge.store.list_tasks(ctx)], [details] * 3)

    def test_history_selection_accounts_for_complete_tool_and_wrapper_overhead(self):
        first = self.bridge.process(self.service.inbox("ou_owner"))
        ctx = self.output_context(first)
        for index in range(12):
            self.bridge.store.append_message(ctx, "assistant", "OLD-" + str(index) + ":" + "合成历史" * 250 + ":END")
        self.bridge.close()
        self.bridge = LegacyConversationBridge(self.service, {"enabled": True,
            "model": {"max_input_chars": 9000}, "runtime": {"max_context_chars": 26000}})
        self.service.g.provider.calls.clear()
        self.bridge.process(self.service.inbox("ou_owner", "继续说合成项目"))
        prompt = self.service.g.provider.calls[0][0]
        self.assertLessEqual(len(prompt), 9000)
        payload = json.loads(prompt[prompt.index('{"messages":'):])
        historical = [message["content"] for message in payload["messages"]
                      if type(message["content"]) is str and message["content"].startswith("OLD-")]
        self.assertLess(len(historical), 12)
        self.assertTrue(all(value.endswith(":END") and value.count("合成历史") == 250 for value in historical))


class LegacyPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("am_build_legacy_patch", cls.root / "scripts" / "build_legacy_patch.py")
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)
        cls.reference = Path(__import__("os").environ.get("AM_REFERENCE_ROOT", cls.root.parent / "reference_am"))
        if not all((cls.reference / relative).is_file() for relative in cls.builder.EXPECTED):
            raise unittest.SkipTest("Fixed GitHub baseline must be supplied to test patch application")

    def test_overlay_compiles_and_patch_applies_to_exact_fixed_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            manifest = self.builder.build(self.reference, output)
            self.assertEqual(manifest["python_compile"], "passed")
            self.assertFalse(manifest["production_enabled"])
            self.assertEqual(len(manifest["changed_files"]), 2)
            if not shutil.which("git"):
                self.skipTest("git is required only for the external patch application smoke check")
            working = Path(temporary) / "working"
            for relative in self.builder.EXPECTED:
                destination = working / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.reference / relative, destination)
            patch = output / "legacy-am-conversation.patch"
            for options in (["--check"], []):
                applied = subprocess.run(["git", "apply", *options, str(patch)], cwd=working,
                                         text=True, capture_output=True, check=False)
                self.assertEqual(applied.returncode, 0, applied.stderr)
            for relative in self.builder.EXPECTED:
                self.assertEqual((working / relative).read_bytes(), (output / "overlay" / relative).read_bytes())
            source = (output / "overlay/local-qwen3.8/feishu-bridge/am_service.py").read_text()
            self.assertIn("conversation_settings=None", source)
            self.assertIn("self.conversation.process(row)", source)

    def test_modified_baseline_is_refused_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            reference = Path(temporary) / "reference"
            for relative in self.builder.EXPECTED:
                destination = reference / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.reference / relative, destination)
            path = reference / next(iter(self.builder.EXPECTED))
            path.write_text(path.read_text() + "\n# newer source must be deliberately rebased\n")
            output = Path(temporary) / "output"
            with self.assertRaisesRegex(ValueError, "^BASELINE_SHA256_MISMATCH:"):
                self.builder.build(reference, output)
            self.assertFalse(output.exists())

    def test_real_baseline_ingest_step_and_delivery_use_plain_text(self):
        """Run actual patched AM/Gateway/Store with synthetic transport/model ports."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            self.builder.build(self.reference, output)
            script = r'''
import json, sys, types
from pathlib import Path
from types import SimpleNamespace
reference, overlay, package, runtime = map(Path, sys.argv[1:])
sys.path[:0] = [str(overlay/'local-qwen3.8/feishu-bridge'), str(reference/'local-qwen3.8/feishu-bridge'),
               str(reference/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'), str(package/'src')]
# The cloud bundle has no Feishu SDK. Only its import-time names are substituted;
# any attempt to instantiate or call a real SDK operation fails this test.
class DisabledSdk:
    def __init__(self,*a,**k): raise AssertionError('No live SDK operation in synthetic smoke test')
    @classmethod
    def builder(cls,*a,**k): raise AssertionError('No SDK builder in synthetic smoke test')
sdk_modules={
    'lark_oapi':[], 'lark_oapi.api':[], 'lark_oapi.api.contact':[],
    'lark_oapi.api.contact.v3':['GetUserRequest'], 'lark_oapi.api.im':[],
    'lark_oapi.api.im.v1':['CreateFileRequest','CreateFileRequestBody','CreateMessageRequest','CreateMessageRequestBody',
                          'GetMessageResourceRequest','GetChatRequest','GetChatMembersRequest','IsInChatChatMembersRequest',
                          'GetMessageRequest','ListMessageRequest'],
    'lark_oapi.event':[], 'lark_oapi.event.callback':[], 'lark_oapi.event.callback.model':[],
    'lark_oapi.event.callback.model.p2_card_action_trigger':['P2CardActionTriggerResponse'],
    'lark_oapi.ws':[], 'lark_oapi.ws.client':[],
}
for name,names in sdk_modules.items():
    module=types.ModuleType(name)
    for item in names:setattr(module,item,DisabledSdk)
    sys.modules[name]=module
sys.modules['lark_oapi.ws.client'].Client=DisabledSdk
sys.modules['lark_oapi.ws'].client=sys.modules['lark_oapi.ws.client']
from fs_agent.config import Config
from fs_agent.gateway import Gateway
from fs_agent.model_coordinator import ModelCoordinator
from fs_agent.store import Store
from group_ledger import GroupLedger
from am_service import AmSelfService

class Clock:
    def __call__(self): return 1800000000.0
class Provider:
    def __init__(self): self.calls=[]
    def complete(self,prompt,**kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=json.dumps({'type':'answer','text':'合成资料仍待核对。'}),model='synthetic',elapsed=0.01)
class Api:
    def __init__(self): self.sent=[]
    def authorized(self,row): return True
    def send(self,row,guard):
        assert guard()
        self.sent.append(dict(row))
        return 'om_synthetic_'+row['id']
    def verify_card(self,message_id,row): return True
class Port:
    app_id='app-test'
    tenant_key='tenant-test'
    def authorize_user(self,user):
        assert user in ('ou_owner','ou_staff')
    authorize_private_user=authorize_user
    def read(self):
        return [{'row':2,'title':'需求1 合成项目Aurora','关键日期':'2026-11-02 检查报告',
                 '待办':'整理合成资料','项目进展':'报告待检查','人员与职责':'合成人员甲'}]

for name in ('state','tasks','artifacts'):(runtime/name).mkdir(parents=True,exist_ok=True)
config=Config('_fsagent',runtime,runtime/'grok',runtime/'key',runtime/'secret',
              'app-test','tenant-test','ou_bot',('ou_owner',),('od-test',),('oc-group',),'ou_owner',True)
clock=Clock(); store=Store(runtime/'state/gateway.sqlite3',clock=clock)
provider=Provider(); coordinator=ModelCoordinator(provider,store,runtime/'state')
api=Api(); gateway=Gateway(config,store,api,coordinator)
ledger=GroupLedger(runtime,Port(),lambda *_: None,clock=clock)
service=AmSelfService(gateway,ledger,flags={'query':True,'items':True},
    query_settings={'private_scope':{'users':{'ou_staff':['需求1']}},'identity_cache_seconds':600},
    conversation_settings={'enabled':True})
bridge=service.conversation
def payload(text,number,user='ou_staff',kind='text',chat_type='p2p'):
    return {'header':{'app_id':'app-test','tenant_key':'tenant-test','event_id':'ev'+str(number),'event_type':'im.message.receive_v1'},
        'event':{'sender':{'sender_type':'user','tenant_key':'tenant-test','sender_id':{'open_id':user}},
        'message':{'message_id':'message'+str(number),'chat_id':'oc_'+user,'chat_type':chat_type,'message_type':kind,
                   'create_time':str(int(clock()*1000)),'content':json.dumps({'text':text}) if kind=='text' else json.dumps({'file_key':'synthetic_file','file_name':'sample.docx'}),
                   'mentions':[]}}}
try:
    assert service.ingest(payload('报告现在怎么样了',1))==(True,True)
    assert store.rows('SELECT kind FROM am_inbox')[0]['kind']=='conversation'
    assert service.step()
    first=store.rows("SELECT * FROM am_inbox WHERE id='message1'")[0]
    assert first['state']=='done',first
    assert not store.rows('SELECT * FROM am_cards')
    assert store.rows('SELECT kind FROM outbox')[0]['kind']=='text'
    assert gateway.deliver_one()
    assert len(api.sent)==1 and api.sent[0]['kind']=='text'
    assert store.rows('SELECT state FROM am_conversation_outputs')[0]['state']=='acknowledged',store.rows('SELECT state,error FROM am_conversation_outputs')+store.rows('SELECT state,error FROM outbox')
    assert provider.calls[0]['native_chat'] is True
    assert service.ingest(payload('/project 需求1',2,'ou_owner'))==(True,True)
    assert store.rows("SELECT kind FROM am_inbox WHERE id='message2'")[0]['kind']=='text'
    assert service.step()
    assert store.rows('SELECT * FROM am_cards')
    assert service.ingest(payload('合成附件',3,kind='file'))==(False,False)
    assert service.ingest(payload('群聊原链路',4,chat_type='group'))==(False,False)
    service.conversation=None
    assert service.ingest(payload('一般聊天内容',5))==(False,False)
    print(json.dumps({'actual_baseline':'passed','transport':'synthetic','model':'synthetic'}))
finally:
    service.close_query();bridge.close();gateway.stop();ledger.close();store.close()
'''
            result = subprocess.run([sys.executable, "-c", script, str(self.reference), str(output / "overlay"),
                                     str(self.root), str(Path(temporary) / "runtime")],
                                    text=True, capture_output=True, check=False, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('"actual_baseline": "passed"', result.stdout)


if __name__ == "__main__":
    unittest.main()
