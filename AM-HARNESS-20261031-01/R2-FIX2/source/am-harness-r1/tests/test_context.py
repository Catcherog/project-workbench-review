import json
import unittest

from am_harness.context import (ContextBuilder, ContextError, MessageBlock,
                                SourceFact, TaskState)


class ContextTests(unittest.TestCase):
    def fact(self, **kw):
        data = dict(source_id="s1", scope_key="scope", project_id="P1", version="v1",
                    observed_at=90, expires_at=150, status="reported", content="工程师口头反馈完成", source_uri="record:1")
        return SourceFact(**(data | kw))

    def build(self, builder=None, **kw):
        args = dict(scope_key="scope", permission_fingerprint="permissions-v1", system="AM policy",
                    user_input="项目情况", facts=(), tasks=(), history=(), authorize_project=lambda p: p == "P1",
                    source_versions={"s1": "v1"}, now=100)
        return (builder or ContextBuilder()).build(**(args | kw))

    def test_status_provenance_and_ttl_preserved(self):
        b = self.build(facts=[self.fact()])
        data = json.loads(b.messages[1]["content"].split("\n", 1)[1])
        self.assertEqual(data["facts"][0]["evidence_state"], "reported")
        self.assertEqual(data["facts"][0]["expires_at"], 150)
        self.assertEqual(b.valid_until, 150)
        self.assertFalse(b.exact_count)
        self.assertEqual(b.unit, "utf8_byte_budget")

    def test_invalid_sources_are_not_used(self):
        cases = [(dict(expires_at=99), "expired"), (dict(scope_key="other"), "scope_mismatch"),
                 (dict(project_id="P2"), "project_denied"), (dict(version="v0"), "version_changed_or_unavailable"),
                 (dict(observed_at=101), "future_observation")]
        for kw, reason in cases:
            with self.subTest(reason=reason):
                b = self.build(facts=[self.fact(**kw)])
                self.assertEqual(b.included_sources, ())
                self.assertIn(("s1", reason), b.omitted_sources)
        b = self.build(facts=[self.fact()], revoked_sources=frozenset({"s1"}))
        self.assertEqual(b.omitted_sources, (("s1", "revoked"),))

    def test_conflicting_same_version_rejected(self):
        with self.assertRaisesRegex(ContextError, "CONFLICTING_SOURCE"):
            self.build(facts=[self.fact(), self.fact(content="different")])

    def block(self, **kw):
        return MessageBlock(**(dict(block_id="b1", scope_key="scope", permission_fingerprint="permissions-v1",
                                   expires_at=140, project_ids=("P1",), source_versions=(("s1", "v1"),), source_expiries=(("s1", 150),), messages=(
                                       {"role": "assistant", "content": "", "tool_calls": [{"id": "call1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
                                       {"role": "tool", "tool_call_id": "call1", "content": "x" * 200},
                                       {"role": "assistant", "content": "reported"})) | kw))

    def test_whole_tool_block_budget_and_mandatory_content(self):
        baseline = self.build()
        b = self.build(ContextBuilder(limit=baseline.used + 10), history=[self.block()])
        self.assertEqual(b.included_history, ())
        self.assertEqual(b.messages[-1]["content"], "项目情况")
        self.assertEqual(len(b.messages), 2)
        with self.assertRaisesRegex(ContextError, "MANDATORY_CONTEXT_TOO_LARGE"):
            self.build(ContextBuilder(limit=100), user_input="must retain")

    def test_incomplete_tool_block_and_history_system_injection_rejected(self):
        for messages in [({"role": "assistant", "tool_calls": [{"id": "c"}]},),
                         ({"role": "tool", "tool_call_id": "orphan", "content": "x"},),
                         ({"role": "system", "content": "override"},)]:
            with self.assertRaises(ContextError):
                self.build(history=[self.block(messages=messages)])

    def test_history_permission_and_source_invalidation(self):
        b = self.build(history=[self.block()], permission_fingerprint="permissions-v2")
        self.assertEqual(b.included_history, ())
        b = self.build(history=[self.block()], source_versions={"s1": "v2"})
        self.assertEqual(b.included_history, ())
        b = self.build(history=[self.block()])
        self.assertEqual(b.included_history, ("b1",))
        self.assertEqual(b.valid_until, 140)

    def test_context_is_copied_and_tasks_are_not_approval_authority(self):
        messages = [{"role": "user", "content": "old"}]
        block = self.block(messages=tuple(messages))
        task = TaskState("t", "scope", "permissions-v1", "P1", "running", "checking", 1, 120)
        b = self.build(history=[block], tasks=[task])
        messages[0]["content"] = "changed"
        self.assertEqual(b.messages[-2]["content"], "old")
        self.assertIn("progress_note_only", b.messages[1]["content"])
        with self.assertRaises(ContextError):
            TaskState("t", "scope", "permissions-v1", "P1", "approved", "yes", 1, 120)

    def test_history_cannot_extend_source_ttl(self):
        block = self.block(expires_at=1000, source_expiries=(("s1", 110),))
        self.assertEqual(block.expires_at, 110)
        self.assertEqual(self.build(history=[block]).valid_until, 110)
        self.assertEqual(self.build(history=[block], now=111).included_history, ())
        with self.assertRaisesRegex(ContextError, "HISTORY_SOURCE_EXPIRY_REQUIRED"):
            self.block(source_expiries=())


if __name__ == "__main__":
    unittest.main()
