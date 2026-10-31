from contextvars import ContextVar
import threading
import time
import unittest

from am_harness.tool_policy import (SourceEvidence, ToolExecutor, ToolInvocation,
                                    ToolPolicyError, ToolResult, ToolSpec)


class ToolPolicyTests(unittest.TestCase):
    def run_calls(self, calls, specs, **kw):
        return ToolExecutor(**kw.pop("config", {})).execute(calls, **(dict(
            resolve=lambda name, args: specs[name], authorize=lambda spec, call: True,
            guard=lambda: None) | kw))

    def test_parallel_reads_overlap_and_keep_order(self):
        barrier = threading.Barrier(2)
        ctx = ContextVar("ctx")
        ctx.set("host-fence")
        def handler(call):
            self.assertEqual(ctx.get(), "host-fence")
            barrier.wait(timeout=2)
            return {"id": call.call_id}
        spec = ToolSpec("read", "read", handler, parallel_safe=True, independent=True)
        results = self.run_calls([ToolInvocation("c1", "read", {}), ToolInvocation("c2", "read", {})], {"read": spec})
        self.assertEqual([r.call_id for r in results], ["c1", "c2"])
        self.assertTrue(all(r.status == "succeeded" for r in results))
        self.assertFalse(any(r.verified for r in results))

    def test_external_handler_never_called(self):
        reached = []
        spec = ToolSpec("send", "external", lambda _: reached.append(True))
        r, = self.run_calls([ToolInvocation("c", "send", {})], {"send": spec})
        self.assertEqual(r.status, "requires_approval")
        self.assertEqual(r.execution_state, "not_started")
        self.assertEqual(reached, [])
        with self.assertRaisesRegex(ToolPolicyError, "ONLY_READS"):
            ToolSpec("send", "external", lambda _: None, parallel_safe=True)

    def test_dependencies_and_validation_are_before_execution(self):
        reached = []
        specs = {"read": ToolSpec("read", "read", lambda c: (_ for _ in ()).throw(RuntimeError("secret"))),
                 "local": ToolSpec("local", "local", lambda c: reached.append(c.call_id))}
        results = self.run_calls([ToolInvocation("r", "read", {}), ToolInvocation("w", "local", {}, ("r",))], specs)
        self.assertEqual([r.status for r in results], ["failed", "not_run"])
        self.assertEqual(reached, [])
        with self.assertRaisesRegex(ToolPolicyError, "INVALID_CALL_GRAPH"):
            self.run_calls([ToolInvocation("w", "local", {}, ("later",))], specs)
        self.assertEqual(reached, [])

    def test_scope_and_changed_fence_discard_results(self):
        spec = ToolSpec("read", "read", lambda _: "private")
        r, = self.run_calls([ToolInvocation("c", "read", {})], {"read": spec}, authorize=lambda *_: False)
        self.assertEqual(r.error_code, "ACCESS_DENIED")
        calls = 0
        def guard():
            nonlocal calls
            calls += 1
            if calls > 1:
                raise RuntimeError("cancelled")
        r, = self.run_calls([ToolInvocation("c", "read", {})], {"read": spec}, guard=guard)
        self.assertEqual(r.status, "stale")
        self.assertIsNone(r.data)
        calls = 0
        r, = self.run_calls([ToolInvocation("c", "write_note", {})],
                           {"write_note": ToolSpec("write_note", "local", lambda _: "done")}, guard=guard)
        self.assertEqual(r.status, "unknown")
        self.assertEqual(r.error_code, "FENCE_CHANGED_AFTER_LOCAL_EFFECT")

    def test_timeout_reports_running_thread_truthfully(self):
        started, release = threading.Event(), threading.Event()
        def handler(_):
            started.set()
            release.wait(timeout=2)
            return "eventual"
        spec = ToolSpec("read", "read", handler, parallel_safe=True, independent=True)
        try:
            r, = self.run_calls([ToolInvocation("c", "read", {})], {"read": spec}, deadline=time.monotonic() + 0.05)
            self.assertTrue(started.is_set())
            self.assertEqual((r.status, r.execution_state), ("unknown", "may_continue"))
            self.assertIsNone(r.data)
        finally:
            release.set()

    def test_envelope_preserves_unknown_and_reported_evidence(self):
        evidence = SourceEvidence("s", "P1", "v1", 100, 200, "reported")
        spec = ToolSpec("read", "read", lambda c: ToolResult(c.call_id, c.name, "unknown", {"missing": True}, (evidence,)))
        r, = self.run_calls([ToolInvocation("c", "read", {})], {"read": spec})
        self.assertEqual(r.status, "unknown")
        self.assertEqual(r.sources[0].evidence_state, "reported")
        self.assertFalse(r.verified)

    def test_size_and_mismatched_call_id_do_not_escape(self):
        spec = ToolSpec("read", "read", lambda _: "x" * 5000, max_result_bytes=300)
        r, = self.run_calls([ToolInvocation("c", "read", {})], {"read": spec})
        self.assertEqual(r.status, "result_too_large")
        self.assertIsNone(r.data)
        spec = ToolSpec("read", "read", lambda _: ToolResult("wrong", "read", "succeeded"))
        r, = self.run_calls([ToolInvocation("c", "read", {})], {"read": spec})
        self.assertEqual(r.error_code, "TOOL_RESULT_ID_MISMATCH")

    def test_handler_upstream_execution_evidence_is_preserved(self):
        spec = ToolSpec("read", "read", lambda c: ToolResult(c.call_id, c.name, "unknown", execution_state="may_continue"))
        r, = self.run_calls([ToolInvocation("c", "read", {})], {"read": spec})
        self.assertEqual((r.status, r.execution_state), ("unknown", "may_continue"))
        spec = ToolSpec("local", "local", lambda c: ToolResult(c.call_id, c.name, "failed", execution_state="not_started"))
        r, = self.run_calls([ToolInvocation("c", "local", {})], {"local": spec})
        self.assertEqual((r.status, r.execution_state), ("failed", "not_started"))

    def test_early_parallel_result_is_rechecked_at_batch_boundary(self):
        first_checked = threading.Event()
        revoked = threading.Event()
        authorizations = {"first": 0, "second": 0}
        lock = threading.Lock()
        def authorize(spec, call):
            with lock:
                authorizations[call.call_id] += 1
                count = authorizations[call.call_id]
            if call.call_id == "first" and count == 2:
                first_checked.set()
            return not revoked.is_set()
        def guard():
            if revoked.is_set():
                raise RuntimeError("revoked")
        def handler(call):
            if call.call_id == "second":
                if not first_checked.wait(timeout=2):
                    raise RuntimeError("first result never completed")
                revoked.set()
            return "sensitive result"
        spec = ToolSpec("read", "read", handler, parallel_safe=True, independent=True)
        results = self.run_calls([ToolInvocation("first", "read", {}), ToolInvocation("second", "read", {})],
                                 {"read": spec}, authorize=authorize, guard=guard)
        self.assertTrue(first_checked.is_set())
        self.assertEqual([r.status for r in results], ["stale", "stale"])
        self.assertTrue(all(r.data is None for r in results))


if __name__ == "__main__":
    unittest.main()
