from pathlib import Path
import tempfile
import unittest
import json
from am_conversation.evaluation import run_cases
from am_conversation.metrics import JsonlMetrics, summarize
from am_conversation.model import ScriptedModel
from am_conversation.types import ModelTurn, ToolCall


class EvaluationTests(unittest.TestCase):
    def test_observable_checks_are_separate_from_manual_quality_review(self):
        cases = [{"id": "case", "title": "来源查询", "messages": ["17进展"], "checks": {"read_projects": ["p17"]}, "manual_rubric": ["区分首批与全部测试"]}]
        def factory():
            return ScriptedModel([ModelTurn(tool_calls=(ToolCall("one", "read_project", {"project_id": "p17"}),)), ModelTurn(text="首批测试完成，其他批次还未开始。")])
        report = run_cases(factory, cases)
        self.assertEqual(1, report["automated_pass_count"])
        self.assertEqual(0, report["external_business_calls"])
        self.assertFalse(report["manual_review_completed"])
        self.assertTrue(report["results"][0]["manual_review_required"])

    def test_plausible_answer_does_not_replace_actual_required_read(self):
        cases = [{"id": "case", "title": "来源查询", "messages": ["17进展"], "checks": {"read_projects": ["p17"]}, "manual_rubric": ["事实要有来源"]}]
        report = run_cases(lambda: ScriptedModel([ModelTurn(text="看起来进行顺利。")]), cases)
        self.assertEqual(0, report["automated_pass_count"])

    def test_metrics_exclude_content_and_summarize_actual_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timings.jsonl"
            sink = JsonlMetrics(path)
            sink({"event_id": "fixture", "span": "model", "seconds": .2, "text": "must not be logged"})
            sink({"event_id": "fixture", "span": "model", "seconds": .8})
            self.assertNotIn("must not", path.read_text())
            report = summarize([json.loads(line) for line in path.read_text().splitlines()])
            self.assertEqual(2, report["spans"]["model"]["count"])
            self.assertEqual(.8, report["spans"]["model"]["p95_seconds"])


if __name__ == "__main__":
    unittest.main()
