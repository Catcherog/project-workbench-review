"""No real CLI, model, network, or business actions are invoked by these tests."""
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from am_style.contracts import ModelRequest, ModelResult, SpeechFrame, canonical, digest
from am_style.providers import (CodexCLIProvider, CoordinatorProvider, OllamaHTTPProvider,
                                SHOW_FIELDS, _file_sha, capability_overrides, inspect_events, validate_codex_proof)
from am_style.runtime import ModelUnavailable, StopUnconfirmed


def request():
    return ModelRequest(canonical([{"role": "system", "content": "Output JSON only."},
                                   {"role": "user", "content": "Synthetic question"}]), "a" * 64, "b" * 64, 20)


def proof_fixture(root):
    binary = root / "codex"
    binary.write_text("fixture executable, never launched", encoding="utf-8")
    profile = root / "am-expression-eval.config.toml"
    profile.write_text('[mcp_servers.business]\nenabled=true\n[apps.test_app]\nenabled=true\n', encoding="utf-8")
    sources = [{"path": str(profile), "sha256": _file_sha(profile)}]
    proof = {"schema": "am-codex-capabilities/1", "profile": "am-expression-eval",
             "binary_sha256": _file_sha(binary), "cli_version": "codex-cli fixture",
             "effective_inventory_verified": True, "observed_tool_names": [], "synthetic_only": True,
             "valid_until_unix": time.time() + 600, "mcp_server_ids": ["business"], "app_ids": ["test_app"],
             "config_sources": sources}
    proof["overrides_sha256"] = digest(capability_overrides(proof))
    evidence = root / "observed-surface.json"
    evidence.write_text(canonical({"schema": "am-codex-observed-surface/1", "profile": proof["profile"],
                                  "cli_version": proof["cli_version"], "overrides_sha256": proof["overrides_sha256"],
                                  "config_sources_sha256": digest(sources), "observed_tool_names": [],
                                  "verified_by": "fixture-only", "policy_and_agents_preserved": True}), encoding="utf-8")
    proof["tool_surface_evidence"] = {"path": str(evidence), "sha256": _file_sha(evidence)}
    return binary, proof


class CoordinatorTests(unittest.TestCase):
    def test_delegates_to_original_callback_exactly_once(self):
        seen = []
        def invoke(r):
            seen.append(r)
            return ModelResult('{"text":"已完成。"}', "original-coordinator", "original-qwen", 1)
        r = request()
        result = CoordinatorProvider(invoke).generate(r)
        self.assertEqual(seen, [r])
        self.assertEqual(result.provider, "original-coordinator")

    def test_timeout_is_not_stop_confirmation(self):
        def invoke(r):
            raise TimeoutError()
        with self.assertRaises(StopUnconfirmed):
            CoordinatorProvider(invoke).generate(request())


class FakeOpener:
    def __init__(self, show, timeout=False):
        self.show, self.timeout, self.requests = show, timeout, []
    def open(self, req, timeout):
        payload = json.loads(req.data)
        self.requests.append((req.full_url, payload))
        if req.full_url.endswith("/api/show"):
            return io.BytesIO(canonical(self.show).encode())
        if self.timeout:
            raise TimeoutError()
        return io.BytesIO(canonical({"model": payload["model"], "done": True,
                                     "message": {"content": '{"text":"测试还在进行。"}'}}).encode())


class OllamaTests(unittest.TestCase):
    def provider(self, show, opener):
        observed = {k: show.get(k) for k in SHOW_FIELDS}
        return OllamaHTTPProvider(endpoint="http://127.0.0.1:11435", production_endpoint="http://127.0.0.1:11434",
            model="exact-original-tag", isolation_record={"verified": True, "endpoint": "http://127.0.0.1:11435",
                                                         "instance_id": "fixture", "evidence_sha256": "a" * 64},
            expected_show_sha256=digest(observed), opener=opener)

    def test_direct_production_and_remote_endpoints_rejected(self):
        for endpoint in ("http://127.0.0.1:11434", "https://provider.example:443", "http://localhost:11435"):
            with self.assertRaises(ModelUnavailable):
                OllamaHTTPProvider(endpoint=endpoint, production_endpoint="http://127.0.0.1:11434", model="tag",
                                   isolation_record={}, expected_show_sha256="a" * 64)

    def test_no_second_consumer_without_real_isolation_record(self):
        with self.assertRaisesRegex(ModelUnavailable, "isolation|isolated"):
            OllamaHTTPProvider(endpoint="http://127.0.0.1:11435", production_endpoint="http://127.0.0.1:11434", model="tag",
                               isolation_record=None, expected_show_sha256="a" * 64)

    def test_think_flag_comes_from_show_capability(self):
        for capabilities, values, expected in ((["completion", "thinking"], [True, False], True),
                                                (["completion"], [], False),
                                                (["completion", "thinking"], ["low", "high"], False)):
            show = {"capabilities": capabilities, "thinking": {"values": values}}
            opener = FakeOpener(show)
            self.provider(show, opener).generate(request())
            payload = opener.requests[-1][1]
            self.assertEqual("think" in payload, expected)
            self.assertFalse(payload["stream"])
            self.assertEqual(payload["format"]["required"], ["text"])

    def test_socket_timeout_does_not_release_model_lane(self):
        show = {"capabilities": ["completion"]}
        with self.assertRaises(StopUnconfirmed):
            self.provider(show, FakeOpener(show, timeout=True)).generate(request())


class CodexProofTests(unittest.TestCase):
    def test_missing_proof_blocks_before_subprocess(self):
        provider = CodexCLIProvider(binary="/not/a/binary", model="exact-model", profile="am-expression-eval", capability_proof={})
        with patch("am_style.providers.subprocess.run") as run:
            with self.assertRaises(ModelUnavailable):
                provider.generate(request())
            run.assert_not_called()
            self.assertFalse(provider.last_model_attempted)

    def test_specific_app_and_mcp_overrides_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary, proof = proof_fixture(Path(tmp))
            proof["app_ids"] = []
            with self.assertRaisesRegex(ModelUnavailable, "specific_enabled"):
                validate_codex_proof(str(binary), "am-expression-eval", proof)

    def test_configuration_change_invalidates_capability_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary, proof = proof_fixture(root)
            (root / "am-expression-eval.config.toml").write_text('[apps.new_tool]\nenabled=true\n')
            with self.assertRaisesRegex(ModelUnavailable, "configuration_changed"):
                validate_codex_proof(str(binary), "am-expression-eval", proof)

    def test_post_run_events_cannot_hide_tools(self):
        event = {"type": "item.completed", "item": {"type": "mcp_tool_call", "name": "business_write"}}
        self.assertEqual(len(inspect_events(json.dumps(event))["tools_called"]), 1)

    def test_argv_stdin_and_account_memory_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary, proof = proof_fixture(Path(tmp))
            captures = {}
            help_flags = "--json --output-schema --output-last-message --ephemeral --sandbox --profile --skip-git-repo-check"
            def run(argv, **kwargs):
                return SimpleNamespace(stdout=proof["cli_version"] if argv[-1] == "--version" else help_flags)
            class FakeProcess:
                pid = 999999
                returncode = 0
                def __init__(self, argv, **kwargs):
                    captures.update(argv=argv, kwargs=kwargs)
                    captures["empty_cwd"] = list(Path(kwargs["cwd"]).iterdir()) == []
                    self.argv, self.out = argv, kwargs["stdout"]
                def communicate(self, data=None, timeout=None):
                    captures["stdin"] = data
                    Path(self.argv[self.argv.index("--output-last-message") + 1]).write_text('{"text":"已完成。"}')
                    self.out.write((canonical({"type": "item.completed", "item": {"type": "agent_message", "text": '{"text":"已完成。"}'}}) + "\n").encode())
                    return None, None
            with patch("am_style.providers.subprocess.run", run), patch("am_style.providers.subprocess.Popen", FakeProcess):
                r = request()
                result = CodexCLIProvider(binary=str(binary), model="selected-explicit-model", profile="am-expression-eval", capability_proof=proof).generate(r)
            self.assertEqual(captures["stdin"], r.messages_json.encode())
            self.assertTrue(captures["empty_cwd"])
            self.assertNotIn("shell", captures["kwargs"])
            self.assertTrue(captures["kwargs"]["start_new_session"])
            self.assertIn("memories.use_memories=false", captures["argv"])
            self.assertIn("memories.generate_memories=false", captures["argv"])
            self.assertIn('mcp_servers.business.enabled=false', captures["argv"])
            self.assertIn('apps.test_app.enabled=false', captures["argv"])
            self.assertEqual(result.model, "selected-explicit-model")
            self.assertEqual(json.loads(result.metadata_json)["returncode"], 0)

    def test_timeout_kills_local_group_but_keeps_remote_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary, proof = proof_fixture(Path(tmp))
            class FakeProcess:
                pid, returncode = 999999, None
                calls = 0
                def __init__(self, *args, **kwargs):
                    pass
                def communicate(self, data=None, timeout=None):
                    self.calls += 1
                    if self.calls == 1:
                        raise subprocess.TimeoutExpired(["codex"], timeout)
                    self.returncode = -15
                    return None, None
                def poll(self):
                    return self.returncode
            with patch.object(CodexCLIProvider, "_preflight", return_value=(capability_overrides(proof), proof["cli_version"])), \
                 patch("am_style.providers.subprocess.Popen", FakeProcess), patch("am_style.providers.os.killpg") as killpg:
                with self.assertRaises(StopUnconfirmed) as caught:
                    CodexCLIProvider(binary=str(binary), model="chosen-model", profile="am-expression-eval", capability_proof=proof).generate(request())
                killpg.assert_called_once()
                self.assertFalse(caught.exception.metadata["remote_stop_confirmed"])


class ComparisonTests(unittest.TestCase):
    def test_unknown_stop_prevents_later_arms(self):
        path = Path(__file__).resolve().parents[1] / "scripts/run_model_comparison.py"
        spec = importlib.util.spec_from_file_location("comparison", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        frame = {"schema_version": "am-style-frame/1", "binding": {"turn_id": "test", "scope_id": "synthetic",
            "outcome_hash": "a" * 64, "source_revision": "fixture", "revision": 1, "cancel_epoch": 0},
            "expires_at": time.time() + 600, "question": "负责人是谁？", "family": "query",
            "units": [{"id": "owner", "covers": ["owner"], "variants": ["测试项目由林工负责。"], "authority": "typed_host"}],
            "obligations": ["owner"], "canonical_units": ["owner"]}
        called = []
        class Provider:
            def generate(self, r):
                raise StopUnconfirmed("fixture unknown stop")
        def factory(arm):
            called.append(arm["name"])
            return Provider()
        report = module.run_comparison([{"case_id": "fixture", "synthetic": True, "frame": frame},
                                        {"case_id": "second-fixture", "synthetic": True, "frame": frame}],
            [{"name": "one", "enabled": True}, {"name": "two", "enabled": True}], provider_factory=factory)
        self.assertEqual(called, ["one"])
        self.assertTrue(report["stopped_for_reconciliation"])
        self.assertEqual(report["rows"][1]["naturalness"], "not_scored")
        self.assertEqual(report["expected_cases"], ["fixture", "second-fixture"])
        self.assertEqual(report["active_arms"], ["host_canonical", "one", "two"])
        self.assertEqual(len(report["rows"]), 6)
        skipped = [r for r in report["rows"] if r["status"] == "skipped_stop_unconfirmed"]
        self.assertEqual(len(skipped), 3)
        self.assertTrue(all(r["attempted"] is False and r["duration_ms"] is None for r in skipped))
        self.assertEqual(report["summary"]["expected_cases_per_arm"], 2)
        self.assertEqual(report["summary"]["arms"]["one"]["attempted"], 1)
        self.assertEqual(report["summary"]["arms"]["two"]["attempted"], 0)
        self.assertEqual(report["summary"]["arms"]["host_canonical"]["attempted"], 0)
        def invalid_configuration(arm):
            raise ModelUnavailable("fixture configuration unavailable")
        unavailable = module.run_comparison([{"case_id": "fixture", "synthetic": True, "frame": frame}],
            [{"name": "one", "enabled": True}], provider_factory=invalid_configuration)
        self.assertEqual(unavailable["rows"][1]["status"], "unavailable")
        self.assertFalse(unavailable["rows"][1]["attempted"])
        self.assertEqual(unavailable["summary"]["arms"]["one"]["attempted"], 0)


if __name__ == "__main__":
    unittest.main()
