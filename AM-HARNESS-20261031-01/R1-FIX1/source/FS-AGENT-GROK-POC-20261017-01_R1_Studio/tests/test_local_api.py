"""Loopback fake server tests. No real model or Feishu requests."""
import json
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from fs_agent.config import BoundaryError, Config
from fs_agent.local_api import LocalQwenClient, validate_endpoint
from fs_agent.qwen_provider import LocalQwenProvider, api_request_unknown
from fs_agent.feishu import Feishu

MODEL = "qwen3.8:27b-bartowski-q8_0"
DIGEST = "a" * 64


def fixture_config(tmp_path, monkeypatch):
    """Use a synthetic OS account, including when the exported template is redacted."""
    template = Path(__file__).parents[1] / "config/environment.example.json"
    data = json.loads(template.read_text())
    data["service"]["user"] = "synthetic_service"
    data["service"]["root_directory"] = "/Users/synthetic-service/.local/share/local-qwen-feishu/poc"
    import fs_agent.config as config_module
    original = config_module.pwd.getpwnam
    monkeypatch.setattr(config_module.pwd, "getpwnam", lambda name:
                        SimpleNamespace(pw_dir="/Users/synthetic-service")
                        if name == "synthetic_service" else original(name))
    path = tmp_path / "synthetic-config.json"
    path.write_text(json.dumps(data))
    return Config.load(path, provider_setup=True), data


def test_existing_app_cannot_open_competing_consumer(tmp_path, monkeypatch):
    config, data = fixture_config(tmp_path, monkeypatch)
    api = Feishu.__new__(Feishu)
    api.config = config
    with pytest.raises(BoundaryError, match="EXISTING_BRIDGE_REQUIRED"):
        api.socket(None)
    data["feishu"]["event_transport"] = "standalone"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    with pytest.raises(BoundaryError, match="EXISTING_BRIDGE_REQUIRED"):
        Config.load(path, provider_setup=True)


@pytest.fixture
def server():
    state = {"requests": [], "delay": 0, "digest": DIGEST, "status": 200, "model": MODEL}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def respond(self, value):
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except BrokenPipeError:
                pass
        def do_GET(self):
            if self.path == "/api/version":
                self.respond({"version": "0.40.5"})
            else:
                self.respond({"models": [{"name": MODEL, "digest": state["digest"]}]})
        def do_POST(self):
            state["requests"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            time.sleep(state["delay"])
            if state["status"] != 200:
                self.send_response(state["status"])
                self.send_header("Location", "http://example.invalid/forbidden")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.respond({"model": state["model"], "choices": [{"finish_reason": "stop",
                    "message": {"role": "assistant", "content": "5"}}], "usage": {"completion_tokens": 1}})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/v1", state
    httpd.shutdown()
    httpd.server_close()
    thread.join()


@pytest.mark.parametrize("url", ["https://127.0.0.1:11434/v1", "http://localhost:11434/v1",
                                "http://example.com:11434/v1", "http://key@127.0.0.1:11434/v1",
                                "http://127.0.0.1:11434/v1?secret=x"])
def test_no_remote_or_credential_bearing_endpoint(url):
    with pytest.raises(BoundaryError, match="LOCAL_LOOPBACK_API_REQUIRED"):
        validate_endpoint(url)


def test_api_ignores_environment_proxy_and_sends_no_tools(server, monkeypatch):
    url, state = server
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-do-not-send")
    client = LocalQwenClient(url, MODEL, DIGEST)
    assert client.fingerprint()["model_digest"] == DIGEST
    assert client.complete("synthetic arithmetic") == "5"
    request = state["requests"][0]
    assert request["tools"] == [] and request["tool_choice"] == "none"
    assert request["reasoning_effort"] == "none"
    assert request["messages"] == [{"role": "user", "content": "synthetic arithmetic"}]
    assert "synthetic-do-not-send" not in json.dumps(request)


def test_changed_weights_or_response_model_rejected(server):
    url, state = server
    client = LocalQwenClient(url, MODEL, DIGEST)
    state["digest"] = "b" * 64
    with pytest.raises(BoundaryError, match="LOCAL_MODEL_CHANGED"):
        client.fingerprint()
    assert not state["requests"]
    state["model"] = "other-model"
    with pytest.raises(BoundaryError, match="MODEL_CHANGED"):
        client.complete("synthetic")


def test_redirect_is_rejected_without_forwarding_prompt(server):
    url, state = server
    state["status"] = 302
    with pytest.raises(BoundaryError, match="LOCAL_API_REJECTED"):
        LocalQwenClient(url, MODEL, DIGEST).complete("synthetic")
    assert len(state["requests"]) == 1


def local_provider(tmp_path, monkeypatch, url):
    config, _ = fixture_config(tmp_path, monkeypatch)
    config = replace(config, root=tmp_path, api_base_url=url, api_model_digest=DIGEST)
    for name in ("state", "tasks"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(Config, "check_service", lambda self: None)
    return LocalQwenProvider(config)


def test_disposable_client_pins_model_and_cleans_payload(server, tmp_path, monkeypatch):
    provider = local_provider(tmp_path, monkeypatch, server[0])
    receipt = provider.p1()
    assert receipt["real_p1_success"] and receipt["model_digest"] == DIGEST
    assert not list((tmp_path / "tasks").iterdir())
    assert provider.pin()["provider"] == "local_qwen_api"


def test_timeout_does_not_claim_shared_model_stopped(server, tmp_path, monkeypatch):
    provider = local_provider(tmp_path, monkeypatch, server[0])
    server[1]["delay"] = 1
    with pytest.raises(BoundaryError, match="STOP_UNKNOWN"):
        provider.complete("synthetic", run_id="c" * 32, timeout=.3, discover=True)
    directory = tmp_path / "tasks" / ("c" * 32)
    assert api_request_unknown(directory)
    assert json.loads((directory / "process.json").read_text())["state"] == "stopped"
    assert not (directory / "request.json").exists()
    assert not (directory / "stdout.tmp").exists()
