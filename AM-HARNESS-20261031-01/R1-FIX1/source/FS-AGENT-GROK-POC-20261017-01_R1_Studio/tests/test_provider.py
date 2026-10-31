import json
import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from fs_agent.config import BoundaryError, Config
from fs_agent.provider import (GrokCliProvider, ProcessRunner, atomic_json, classify_error, group_alive, parse_result,
                               safe_environment, sandbox_profile, validate_inspect)


def test_json_contract_observed_model_required():
    data = {"text": "5", "stopReason": "end_turn", "num_turns": 1,
            "modelUsage": {"grok-test-fixture": {"modelCalls": 1}}}
    assert parse_result(json.dumps(data).encode(), .1, None).model == "grok-test-fixture"
    with pytest.raises(BoundaryError, match="MODEL_CHANGED"):
        parse_result(json.dumps(data).encode(), .1, "grok-other")
    del data["modelUsage"]
    with pytest.raises(BoundaryError):
        parse_result(json.dumps(data).encode(), .1, None)


def test_sanitized_environment_never_inherits_personal_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("HOME", "/Users/synthetic-personal-home")
    monkeypatch.setenv("GROK_HOME", "/Users/synthetic-personal-grok")
    env = safe_environment(tmp_path)
    assert "OPENAI_API_KEY" not in env and "XAI_API_KEY" not in env
    assert env["HOME"] == str(tmp_path / "home")
    assert env["GROK_MEMORY"] == "0" and env["GROK_CLAUDE_MCPS_ENABLED"] == "0"


def test_process_timeout_kills_owned_group_and_preserves_safe_journal(tmp_path):
    runner = ProcessRunner()
    pids = []
    with pytest.raises(BoundaryError, match="EXECUTION_TIMEOUT"):
        runner.run(["/bin/sleep", "10"], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"}, directory=tmp_path,
                   timeout=.1, on_start=lambda pgid, identity: pids.append(pgid))
    assert pids and not group_alive(pids[0])
    assert json.loads((tmp_path / "process.json").read_text())["state"] == "stopped"


def test_process_output_cap(tmp_path):
    with pytest.raises(BoundaryError, match="OUTPUT_LIMIT"):
        ProcessRunner().run(["/usr/bin/yes", "SYNTHETIC"], cwd=tmp_path,
                            env={"PATH": "/usr/bin:/bin"}, directory=tmp_path, timeout=3)
    assert json.loads((tmp_path / "process.json").read_text())["state"] == "stopped"


def test_os_sandbox_blocks_sibling_task_files(tmp_path):
    root = tmp_path.resolve()
    task = root / "task"
    task.mkdir()
    secret = root / "synthetic-secret.txt"
    secret.write_text("synthetic canary only")
    allowed = task / "synthetic-input.txt"
    allowed.write_text("synthetic allowed")
    profile = task / "sandbox.sb"
    profile.write_text(sandbox_profile(root, task, Path("/bin/cat")))
    denied = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/cat", str(secret)], capture_output=True)
    permitted = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/cat", str(allowed)], capture_output=True)
    assert denied.returncode != 0 and b"synthetic canary" not in denied.stdout
    assert permitted.returncode == 0 and permitted.stdout == b"synthetic allowed"


def test_inspect_rejects_connectors_and_unknown_schema(tmp_path):
    empty = {k: [] for k in ("projectInstructions", "hooks", "skills", "agents", "plugins", "mcpServers", "lspServers")}
    empty["configSources"] = {"layers": []}
    validate_inspect(empty, tmp_path)
    empty["mcpServers"] = [{"name": "synthetic-forbidden-connector"}]
    with pytest.raises(BoundaryError):
        validate_inspect(empty, tmp_path)
    with pytest.raises(BoundaryError):
        validate_inspect({}, tmp_path)


@pytest.mark.parametrize("text,code", [(b"HTTP 401", "AUTH_FAILED"), (b"insufficient credits", "QUOTA_EXHAUSTED"),
                                       (b"HTTP 429", "RATE_LIMITED"), (b"secret body", "CLI_FAILED")])
def test_errors_never_echo_untrusted_body(text, code):
    assert classify_error(text) == code


def test_template_cannot_start_live_runtime():
    path = Path(__file__).parents[1] / "config" / "environment.grok.example.json"
    with pytest.raises(BoundaryError, match="CONFIG_IS_TEMPLATE"):
        Config.load(path)


@pytest.mark.parametrize("exitcode", [0, 1])
def test_dedicated_oauth_refresh_survives_and_task_is_cleaned(tmp_path, monkeypatch, exitcode):
    path = Path(__file__).parents[1] / "config" / "environment.grok.example.json"
    config = replace(Config.load(path, provider_setup=True), root=tmp_path,
                     executable=tmp_path / "bin" / "grok", credential_file=tmp_path / "secrets" / "grok_auth.json")
    for name in ("tasks", "secrets", "bin"):
        (tmp_path / name).mkdir()
    config.executable.write_bytes(b"synthetic executable placeholder; never run")
    atomic_json(config.credential_file, {"synthetic_session": "old"})
    monkeypatch.setattr(Config, "check_service", lambda self: None)
    provider = GrokCliProvider(config)
    monkeypatch.setattr(provider, "inspect", lambda *a, **k: {})

    def synthetic_invoke(directory, arguments, **kwargs):
        assert kwargs["key"] is None
        assert config.read_auth_json(directory / "grok" / "auth.json")["synthetic_session"] == "old"
        atomic_json(directory / "grok" / "auth.json", {"synthetic_session": "refreshed"})
        atomic_json(directory / "process.json", {"state": "stopped"})
        result = {"text": "5", "stopReason": "end_turn", "num_turns": 1,
                  "modelUsage": {"grok-test-fixture": {"modelCalls": 1}}}
        return exitcode, json.dumps(result).encode(), b"401" if exitcode else b""

    monkeypatch.setattr(provider, "invoke", synthetic_invoke)
    if exitcode:
        with pytest.raises(BoundaryError, match="AUTH_FAILED"):
            provider.complete("synthetic prompt", run_id="a" * 32, discover=True)
    else:
        assert provider.complete("synthetic prompt", run_id="a" * 32, discover=True).text == "5"
    assert config.read_auth_json(config.credential_file) == {"synthetic_session": "refreshed"}
    assert not list((tmp_path / "tasks").iterdir())


def test_oauth_parallel_refresh_is_not_silently_enabled(tmp_path):
    path = Path(__file__).parents[1] / "config" / "environment.grok.example.json"
    data = json.loads(path.read_text())
    data["limits"]["global_concurrency"] = 2
    target = tmp_path / "environment.json"
    target.write_text(json.dumps(data))
    with pytest.raises(BoundaryError, match="OAUTH_SINGLE_LANE_REQUIRED"):
        Config.load(target, provider_setup=True)
