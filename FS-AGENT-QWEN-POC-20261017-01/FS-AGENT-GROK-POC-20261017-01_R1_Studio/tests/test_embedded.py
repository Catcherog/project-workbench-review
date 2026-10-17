"""Exercise the real bridge and gateway together with synthetic model/Feishu APIs."""
import importlib.util
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from fs_agent.config import BoundaryError, Config
from fs_agent.embedded import EmbeddedPoC
from fs_agent.gateway import Gateway
from fs_agent.provider import Result
from fs_agent.store import Store

PROJECT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("integration_bridge", PROJECT.parent / "local-qwen3.8/feishu-bridge/bridge.py")
bridge_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_module)


def event(text, number, user="ou_a"):
    return {"header": {"app_id": "cli_test", "tenant_key": "tenant", "event_id": "e"+str(number),
                       "event_type": "im.message.receive_v1"},
            "event": {"sender": {"sender_type": "user", "tenant_key": "tenant", "sender_id": {"open_id": user}},
                      "message": {"message_id": "om_"+str(number), "chat_id": "oc_"+user,
                                  "chat_type": "p2p", "message_type": "text",
                                  "create_time": str(int(time.time()*1000)),
                                  "content": json.dumps({"text": text})}}}


class FakeApi:
    def __init__(self):
        self.checks, self.sent = 0, []
    def authorized(self, row):
        self.checks += 1
        return True
    def send(self, row, guard):
        assert guard()
        self.sent.append(dict(row))
        return "om_result_"+row["id"]


class FakeProvider:
    def __init__(self, calls):
        self.calls, self.prompts = calls, []
    def complete(self, prompt, **kwargs):
        self.calls.append("poc")
        self.prompts.append(prompt)
        return Result("合成整理结果", "synthetic-model", .01)


@pytest.fixture
def rig(tmp_path):
    root = tmp_path / "poc"
    for name in ("state", "tasks", "artifacts"):
        (root/name).mkdir(parents=True)
    config = replace(Config.load(PROJECT/"config/environment.example.json", provider_setup=True),
                     root=root, app_id="cli_test", tenant_key="tenant", users=("ou_a", "ou_b"),
                     owner="ou_a", bot_open_id="ou_bot", departments=("od_test",),
                     department_match="any_exact", exclusive_consumer=True)
    calls, replies = [], []
    api, provider = FakeApi(), FakeProvider(calls)
    gateway = Gateway(config, Store(config.db), api, provider)
    poc = EmbeddedPoC(gateway)
    def general(messages):
        calls.append("general")
        assert all("合成资料" not in m["content"] for m in messages)
        return "普通聊天结果"
    bridge = bridge_module.Bridge({"app_id":"cli_test", "access_mode":"all_private_users",
                                  "state_directory":str(tmp_path/"chat")},
                                 lambda mid, text: replies.append((mid,text)), general, poc=poc)
    yield bridge, api, provider, calls, replies
    bridge.db.close()
    bridge.poc.close()


def drain(bridge):
    for _ in range(40):
        if not bridge.process_cycle():
            return
    pytest.fail("worker did not become idle")


def test_rapid_selection_and_input_stay_in_poc_before_worker(rig):
    b, api, provider, _, _ = rig
    assert b.ingest(event("/doc", 1))
    assert b.ingest(event("sample", 2))
    assert api.checks == 0 and not provider.prompts
    assert b.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0
    assert len(b.poc.store.rows("SELECT * FROM inbox")) == 2
    drain(b)
    assert len(provider.prompts) == 1
    files = [r for r in api.sent if r["kind"] == "file"]
    assert len(files) == 1 and Path(files[0]["artifact"]).read_text().startswith("# 合成文档")
    assert b.poc.gateway.threads == [] and not b.poc.gateway.pool._threads


def test_test_routes_remain_two_person_but_general_chat_keeps_access(rig):
    b, _, provider, calls, replies = rig
    assert not b.ingest(event("/doc sample", 1, "ou_outsider"))
    assert b.ingest(event("ordinary synthetic question", 2, "ou_outsider"))
    assert b.ingest(event("/progress sample", 3, "ou_b"))
    drain(b)
    assert calls == ["poc", "general"] and len(provider.prompts) == 1
    assert len(replies) == 1 and replies[0][0] == "om_2"
    assert b.poc.store.rows("SELECT user FROM tasks") == [{"user":"ou_b"}]


def test_replayed_messages_never_cross_between_stores(rig):
    b, _, provider, calls, replies = rig
    general, doc, leave = event("ordinary synthetic question", 1), event("/doc sample", 2), event("/chat", 3)
    assert b.ingest(general)
    assert b.ingest(doc)
    assert not b.ingest(general)
    assert b.ingest(leave)
    assert not b.ingest(doc)
    assert b.ingest(event("back to ordinary synthetic chat", 4))
    drain(b)
    assert len(provider.prompts) == 1 and calls.count("general") == 2
    assert len(replies) == 2
    assert not b.ingest(doc) and not b.ingest(general)


def test_mode_survives_restart_and_does_not_extend_on_plain_input(rig):
    b, api, provider, _, _ = rig
    assert b.ingest(event("/progress", 1))
    expires = b.poc.store.rows("SELECT expires FROM bridge_mode")[0]["expires"]
    config = b.poc.config
    b.poc.close()
    b.poc = EmbeddedPoC(Gateway(config, Store(config.db), api, provider))
    assert b.ingest(event("sample", 2))
    assert b.poc.store.rows("SELECT expires FROM bridge_mode")[0]["expires"] == expires
    drain(b)
    assert len(provider.prompts) == 1


def test_inbox_and_mode_transaction_roll_back_together(rig):
    b, _, _, _, _ = rig
    def fail(conn, row, expires):
        conn.execute("INSERT INTO bridge_mode VALUES ('synthetic','poc',?)", (expires,))
        raise RuntimeError("synthetic disk fault")
    with pytest.raises(RuntimeError):
        b.poc.gateway.ingest(event("/doc", 1), on_insert=fail)
    assert not b.poc.store.rows("SELECT * FROM inbox")
    assert not b.poc.store.rows("SELECT * FROM bridge_mode")


def test_poc_worker_fault_does_not_stop_other_users_general_chat(rig, monkeypatch):
    b, _, _, calls, _ = rig
    def fail():
        raise RuntimeError("synthetic PoC storage fault")
    monkeypatch.setattr(b.poc.gateway, "cleanup", fail)
    assert b.ingest(event("ordinary synthetic question", 1, "ou_outsider"))
    assert b.process_cycle()
    assert b.poc.suspended and calls == ["general"]
    with pytest.raises(BoundaryError, match="POC_SUSPENDED"):
        b.ingest(event("sample", 2))
    assert not b.ingest(event("/doc sample", 3, "ou_outsider"))


def test_approved_login_mode_keeps_private_paths_and_secret_reference(tmp_path, monkeypatch):
    account = SimpleNamespace(pw_uid=os.getuid(), pw_dir=str(tmp_path))
    monkeypatch.setattr("fs_agent.config.pwd.getpwnam", lambda _: account)
    data = json.loads((PROJECT/"config/environment.example.json").read_text())
    root = tmp_path/".local/share/local-qwen-feishu/poc"
    data["service"]["root_directory"] = str(root)
    for path in [root]+[root/n for n in ("home", "state", "tasks", "artifacts", "secrets")]:
        path.mkdir(mode=0o700,parents=True,exist_ok=True)
    path = tmp_path/"config.json"
    path.write_text(json.dumps(data))
    config = Config.load(path, provider_setup=True)
    config.check_service()
    secret = root.parent/"secrets/app_secret"
    secret.parent.mkdir(mode=0o700)
    secret.write_text("synthetic-secret"); secret.chmod(0o600)
    assert config.read_secret(secret) == "synthetic-secret"
    foreign = tmp_path/"unrelated-secret"
    foreign.write_text("must not read"); foreign.chmod(0o600)
    with pytest.raises(BoundaryError, match="SECRET_NOT_DEDICATED"):
        config.read_secret(foreign)
    (root/"state").chmod(0o755)
    with pytest.raises(BoundaryError, match="SERVICE_DIRECTORY_NOT_PRIVATE"):
        config.check_service()
