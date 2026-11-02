import json
from pathlib import Path
import tempfile
import unittest

from am_harness.telemetry import MetadataTrace, TraceError, summarize


class TelemetryTests(unittest.TestCase):
    def test_only_metadata_and_hashed_run_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            trace = MetadataTrace(path)
            trace.emit("private-event-123", "queued", queue_depth=2, revision=1)
            row = json.loads(path.read_text())
            self.assertNotIn("private-event-123", path.read_text())
            self.assertEqual(row["run_ref"], trace.run_ref("private-event-123"))
            for kwargs in [dict(prompt="secret"), dict(actor_id="person"), dict(output="secret"), dict(source_uri="private")]:
                with self.assertRaisesRegex(TraceError, "NOT_ALLOWED"):
                    trace.emit("run", "queued", **kwargs)
            self.assertEqual(len(path.read_text().splitlines()), 1)

    def test_phase_timings_and_distinct_useful_vs_final(self):
        now = [1.0]
        trace = MetadataTrace(clock=lambda: now[0], wall_clock=lambda: 100.0)
        trace.start_run("run")
        with trace.span("run", "model", input_units=100, exact_token_count=False):
            now[0] = 2.0
        self.assertTrue(trace.mark_first_useful("run"))
        self.assertFalse(trace.mark_first_useful("run"))
        now[0] = 3.0
        self.assertTrue(trace.mark_final("run", status="succeeded"))
        data = summarize(trace.records)
        self.assertEqual(data["first_useful"]["mean_ms"], 1000)
        self.assertEqual(data["final"]["mean_ms"], 2000)
        self.assertEqual(data["phases"]["model"]["n"], 1)

    def test_exception_text_is_never_logged(self):
        trace = MetadataTrace()
        with self.assertRaisesRegex(RuntimeError, "secret"):
            with trace.span("r", "tool", tool_name="read_project"):
                raise RuntimeError("secret")
        self.assertNotIn("secret", json.dumps(trace.records))
        self.assertEqual(trace.records[-1]["status"], "error")

    def test_limits_and_bad_values(self):
        trace = MetadataTrace(max_records=2)
        for _ in range(4):
            trace.emit("run", "queued", queue_depth=0)
        self.assertEqual(len(trace.records), 2)
        for fields in [dict(queue_ms=float("nan")), dict(queue_ms=-1), dict(status="contains private data"), dict(exact_token_count=1)]:
            with self.assertRaises(TraceError):
                trace.emit("run", "queued", **fields)

    def test_sink_failure_keeps_business_flow_and_memory_record(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = MetadataTrace(directory)  # opening a directory as a file fails
            trace.emit("r", "queued")
            self.assertEqual(trace.sink_errors, 1)
            self.assertEqual(len(trace.records), 1)


if __name__ == "__main__":
    unittest.main()
