"""Legacy runtime configuration cannot touch credentials or execute a provider."""
import json
from types import SimpleNamespace

import pytest

from fs_agent import cli


@pytest.mark.parametrize("command", ["p1", "serve", "login"])
def test_non_qwen_runtime_is_rejected_before_execution(monkeypatch, capsys, command):
    def forbidden(*args, **kwargs):
        raise AssertionError("old provider configuration must not touch runtime services")
    config = SimpleNamespace(provider_kind="grok_cli", check_service=forbidden)
    monkeypatch.setattr(cli.Config, "load", lambda *args, **kwargs: config)
    monkeypatch.setattr(cli, "LocalQwenProvider", forbidden)
    monkeypatch.setattr("sys.argv", ["fs-agent", command, "--config", "synthetic-only.json"])
    assert cli.main() == 2
    assert json.loads(capsys.readouterr().err) == {"error": "QWEN_RUNTIME_REQUIRED"}
