"""Protocol simulations only: never construct a real capability proof or call a model."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from model_lab.core import canonical, file_sha, read_json, write_json
from model_lab.fixtures import fixture_spec
from model_lab.providers import codex_generate, mlx_generate_batch


class ProviderProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def ref(self, name, value):
        p = write_json(self.root/name, value)
        return {"path": str(p), "sha256": file_sha(p)}

    def codex_setup(self):
        case = fixture_spec()["cases"][0]
        binary = self.root/"protocol-fixture-binary"
        binary.write_text("unit fixture; never executable\n")
        arm = {"kind": "codex_cli", "identity": {"model": "fixture-model", "cli_version": "fixture-version"},
               "settings": {"timeout_seconds": 1}, "runtime": {
                   "binary": {"path": str(binary), "sha256": file_sha(binary)},
                   "capability_proof": self.ref("fixture-only-proof.json", {"fixture": True, "not_a_real_proof": True}),
                   "profile": "fixture"}}
        original = ModuleType("am_style.providers")
        original.CodexCLIProvider = lambda **kw: SimpleNamespace(_preflight=lambda *a: ({"features.shell_tool": False}, "fixture-version"))
        original.restricted_environment = lambda proof: {"PATH": "/fixture-path"}
        original.inspect_events = lambda raw: {"events": 1, "tools_called": []}
        return arm, case, original

    def test_codex_exact_argv_stdin_and_raw_protocol_capture(self):
        arm, case, original = self.codex_setup()
        observed = {}
        def launch(argv, **kwargs):
            observed.update(argv=argv, kwargs=kwargs)
            def communicate(payload, timeout):
                observed["stdin"] = payload
                kwargs["stdout"].write(b'{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":7}}\n')
                Path(argv[argv.index("--output-last-message")+1]).write_text(canonical(case["fixture_outputs"]["q8"]["output"]))
            return SimpleNamespace(returncode=0, communicate=communicate)
        with patch.dict(sys.modules, {"am_style.providers": original}), \
             patch("model_lab.providers.preflight_arm", return_value={"status": "ready", "blockers": []}), \
             patch("model_lab.providers.subprocess.Popen", side_effect=launch):
            result = codex_generate(arm, case, self.root/"codex-protocol")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(observed["stdin"].decode(), canonical(case["messages"]))
        self.assertEqual(observed["argv"][1], "exec")
        self.assertIn("--json", observed["argv"])
        self.assertIn("--ephemeral", observed["argv"])
        self.assertIn("features.shell_tool=false", observed["argv"])
        self.assertNotIn("shell", observed["kwargs"])
        self.assertEqual(result["measurements"]["tokens"]["input"]["value"], 5)
        self.assertEqual({r["role"] for r in result["raw"]}, {"stdin", "request", "schema", "events", "stderr", "final"})

    def test_codex_timeout_does_not_claim_remote_stop(self):
        arm, case, original = self.codex_setup()
        fake = SimpleNamespace(pid=99999999, returncode=None)
        fake.communicate = lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("fixture", 1))
        fake.poll = lambda: fake.returncode
        def wait(timeout): fake.returncode = -15; return -15
        fake.wait = wait
        with patch.dict(sys.modules, {"am_style.providers": original}), \
             patch("model_lab.providers.preflight_arm", return_value={"status": "ready", "blockers": []}), \
             patch("model_lab.providers.subprocess.Popen", return_value=fake), \
             patch("model_lab.providers.os.killpg"):
            result = codex_generate(arm, case, self.root/"timeout-protocol")
        self.assertEqual(result["status"], "stop_unknown")
        self.assertIn("remote_stop_not_proven", result["error"])
        self.assertTrue((self.root/"timeout-protocol/events.jsonl").is_file())

    def test_codex_unexpected_tool_surface_halts_even_after_cli_exit(self):
        arm, case, original = self.codex_setup()
        original.inspect_events = lambda raw: {"events": 1, "tools_called": [{"type": "command_execution"}]}
        def launch(argv, **kwargs):
            def communicate(*args, **kw):
                kwargs["stdout"].write(b'{"type":"turn.completed","usage":{}}\n')
                Path(argv[argv.index("--output-last-message")+1]).write_text('{}')
            return SimpleNamespace(returncode=0, communicate=communicate)
        with patch.dict(sys.modules, {"am_style.providers": original}), \
             patch("model_lab.providers.preflight_arm", return_value={"status": "ready", "blockers": []}), \
             patch("model_lab.providers.subprocess.Popen", side_effect=launch):
            result = codex_generate(arm, case, self.root/"tool-violation-protocol")
        self.assertEqual(result["status"], "stop_unknown")
        self.assertIn("tool_surface_violation", result["error"])

    def test_mlx_dispatches_only_original_eval_window_and_requires_restore(self):
        control = self.root/"training-window-r7"; control.mkdir()
        arm = {"kind": "mlx_adapter", "runtime": {"pilot_plan": self.ref("pilot.json", {}),
               "python": {"path": str(Path(sys.executable).resolve()), "sha256": file_sha(Path(sys.executable).resolve())}}}
        plan_path = self.root/"plan.json"; plan_path.write_text("{}")
        case = fixture_spec()["cases"][0]
        observed = {}
        def submit(argv, **kwargs):
            observed["argv"] = argv
            request_id = argv[argv.index("--request-id")+1]
            run_id = argv[argv.index("--run-id")+1]
            native = self.root/"AM-HARNESS-20261031-01/R7/private"/run_id
            write_json(native/"parent-result.json", {"status": "completed", "stop_confirmed": True})
            (native/"results.jsonl").write_text("")
            write_json(control/(request_id+".result.json"), {"window": {"status": "completed", "restore_verified": True},
                "trainer_start_attempts": 0, "real_platform_sends": 0})
            return SimpleNamespace(returncode=0, stdout="fixture submission", stderr="")
        outcome = {case["case_id"]: {"status": "completed", "protocol_fixture": True}}
        with patch("model_lab.providers.preflight_arm", return_value={"status": "ready", "blockers": [], "control_directory": str(control)}), \
             patch("model_lab.providers._roots", return_value=self.root), \
             patch("model_lab.providers._r5_plan", return_value=(plan_path, {})), \
             patch("model_lab.providers.subprocess.run", side_effect=submit), \
             patch("model_lab.providers._import_r5", return_value=outcome):
            result = mlx_generate_batch(arm, [case], self.root/"mlx-protocol")
        self.assertEqual(result, outcome)
        self.assertEqual(observed["argv"][2], "eval-mlx")
        self.assertTrue(observed["argv"][1].endswith("am-integrated-r6/tools/training_control.py"))
        self.assertNotIn("train", observed["argv"])


if __name__ == "__main__":
    unittest.main()
