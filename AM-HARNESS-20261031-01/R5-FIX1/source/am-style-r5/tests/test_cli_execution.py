"""CLI status propagation with explicit returned-report fixtures, no execution."""
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

from am_style_r5.cli import main


class ExecutionCLIStatusTests(unittest.TestCase):
    def invoke(self, command, report, runner):
        args = [command, "--plan", "fixture.json", "--output", "/never-written", "--execute"]
        if command == "eval-qwen":
            args += ["--queue-config", "fixture-queue.json"]
        else:
            args += ["--manifest", "fixture-manifest.json", "--arm", "mlx_base"]
        stream = io.StringIO()
        with patch("am_style_r5.cli.read_json", return_value={}), patch(runner, return_value=report), redirect_stdout(stream):
            code = main(args)
        self.assertEqual(json.loads(stream.getvalue()), report)
        return code

    def test_unknown_qwen_returns_nonzero_while_retaining_report(self):
        code = self.invoke("eval-qwen", {"status": "stop_unknown", "stop_unknown": True},
                           "am_style_r5.runners.run_original_qwen")
        self.assertEqual(code, 2)

    def test_failed_mlx_returns_nonzero_even_after_confirmed_stop(self):
        code = self.invoke("eval-mlx", {"status": "failed", "stop_confirmed": True},
                           "am_style_r5.runners.run_mlx_arm")
        self.assertEqual(code, 2)

    def test_completed_run_returns_zero(self):
        code = self.invoke("eval-mlx", {"status": "completed", "stop_confirmed": True},
                           "am_style_r5.runners.run_mlx_arm")
        self.assertEqual(code, 0)

    def test_blocked_preflight_returns_nonzero(self):
        stream = io.StringIO()
        with patch("am_style_r5.pilot.preflight_pilot", return_value={"ready_for_launch": False}), redirect_stdout(stream):
            code = main(["pilot-preflight", "--plan", "fixture-only.json"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(stream.getvalue())["ready_for_launch"])


if __name__ == "__main__":
    unittest.main()
