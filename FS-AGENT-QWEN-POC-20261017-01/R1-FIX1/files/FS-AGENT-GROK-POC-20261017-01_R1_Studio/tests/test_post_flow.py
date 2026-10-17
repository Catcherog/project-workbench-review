"""Synthetic integration of the actual bridge, EmbeddedPoC and Gateway."""
import copy
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from test_embedded import PROJECT, drain, event, rig


def post(text, number, user="ou_a", *, nodes=None):
    payload = event(text, number, user)
    message = payload["event"]["message"]
    message["message_type"] = "post"
    message["content"] = json.dumps({"title": "", "content": [
        nodes if nodes is not None else [{"tag": "text", "text": text}]
    ]})
    return payload


def test_post_doc_uses_real_ingress_once_and_fixed_markdown(rig):
    bridge, api, provider, calls, _ = rig
    payload = post("", 1, nodes=[
        {"tag": "text", "text": "  /doc ", "style": ["codeInline"]},
        {"tag": "text", "text": "sample  "},
    ])
    original = copy.deepcopy(payload)
    assert bridge.ingest(payload)
    assert payload == original
    assert api.checks == 0 and calls == []
    assert bridge.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0
    assert len(bridge.poc.store.rows("SELECT * FROM inbox")) == 1
    drain(bridge)
    assert calls == ["poc"] and len(provider.prompts) == 1
    tasks = bridge.poc.store.rows("SELECT state FROM tasks")
    assert tasks == [{"state": "completed"}]
    files = [row for row in api.sent if row["kind"] == "file"]
    assert len(files) == 1
    assert "## 整理结果\n\n合成整理结果" in Path(files[0]["artifact"]).read_text()


def test_post_modes_and_replayed_messages_never_cross_stores(rig):
    bridge, _, provider, calls, replies = rig
    ordinary = post("普通合成问候", 1)
    select = post(" /doc ", 2)
    sample = post(" sample ", 3)
    assert bridge.ingest(ordinary)
    assert bridge.ingest(select)
    expires = bridge.poc.store.rows("SELECT expires FROM bridge_mode")[0]["expires"]
    assert bridge.ingest(sample)
    assert bridge.poc.store.rows("SELECT expires FROM bridge_mode")[0]["expires"] == expires
    assert bridge.ingest(post(" /chat ", 4))
    assert bridge.ingest(post("回到普通聊天的合成问候", 5))
    for original in (ordinary, select, sample):
        replay = copy.deepcopy(original)
        replay["header"]["event_id"] += "-platform-retry"
        assert not bridge.ingest(replay)
    # A body-changed replay remains the same receipt, even on the long-input path.
    replay = copy.deepcopy(select)
    replay["header"]["event_id"] += "-long-retry"
    replay["event"]["message"]["content"] = json.dumps({"title": "", "content": [[
        {"tag": "text", "text": "x" * 6001}]]})
    assert not bridge.ingest(replay)
    assert bridge.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 2
    drain(bridge)
    assert len(provider.prompts) == 1 and calls.count("general") == 2
    assert len(replies) == 2
    assert bridge.poc.store.rows("SELECT mode FROM bridge_mode") == [{"mode": "chat"}]


def test_post_poc_allowlist_and_existing_private_chat_scope_stay_separate(rig):
    bridge, _, provider, calls, replies = rig
    assert not bridge.ingest(post("/doc sample", 1, "ou_outsider"))
    assert not bridge.ingest(post("/progress sample", 2, "ou_outsider"))
    assert bridge.ingest(post("普通合成问题", 3, "ou_outsider"))
    assert bridge.ingest(post("/progress sample", 4, "ou_b"))
    drain(bridge)
    assert calls == ["general"] and provider.prompts == []
    assert len(replies) == 1 and replies[0][0] == "om_3"
    assert bridge.poc.store.rows("SELECT user,state,model FROM tasks") == [{
        "user": "ou_b", "state": "completed", "model": "python:synthetic-progress-v1"}]


@pytest.mark.parametrize("case,accepted", [
    ("valid", True), ("metadata_only", False), ("node_only", False),
    ("wrong_bot", False), ("wrong_chat", False),
])
def test_group_post_requires_both_real_mention_signals_and_keeps_original_fields(rig, case, accepted):
    bridge, _, _, calls, _ = rig
    config = replace(bridge.poc.config, chats=("oc_synthetic_group",))
    bridge.poc.config = bridge.poc.gateway.config = config
    nodes = [{"tag": "at", "user_id": "@_user_1"}, {"tag": "text", "text": " /doc sample "}]
    if case == "metadata_only":
        nodes = [{"tag": "text", "text": "@_user_1 /doc sample"}]
    payload = post("", 1, nodes=nodes)
    message = payload["event"]["message"]
    message.update(chat_type="group", chat_id="oc_wrong" if case == "wrong_chat" else "oc_synthetic_group")
    message["create_time"] = str(int((time.time() - 30) * 1000))
    message["mentions"] = [] if case == "node_only" else [{
        "key": "@_user_1", "id": {"open_id": "ou_other" if case == "wrong_bot" else "ou_bot"}}]
    original = copy.deepcopy(payload)
    assert bridge.ingest(payload) is accepted
    assert payload == original and calls == []
    rows = bridge.poc.store.rows("SELECT app,tenant,user,chat,message_id,body,expires FROM inbox")
    assert len(rows) == int(accepted)
    assert bridge.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0
    if accepted:
        assert rows[0] == {"app": "cli_test", "tenant": "tenant", "user": "ou_a",
                           "chat": "oc_synthetic_group", "message_id": "om_1", "body": "/doc sample",
                           "expires": int(message["create_time"]) / 1000 + 86400}


@pytest.mark.parametrize("tag", ["a", "img", "unknown"])
@pytest.mark.parametrize("poc_mode", [False, True])
def test_unsupported_post_never_falls_back_to_general_model(rig, tag, poc_mode):
    bridge, _, _, calls, _ = rig
    if poc_mode:
        assert bridge.ingest(post("/doc", 1))
        drain(bridge)
    before = len(bridge.poc.store.rows("SELECT * FROM inbox"))
    payload = post("", 2, nodes=[{"tag": "text", "text": "/d"},
                                {"tag": tag, "text": "untrusted", "href": "https://example.invalid/"},
                                {"tag": "text", "text": "oc sample"}])
    assert not bridge.ingest(payload)
    assert len(bridge.poc.store.rows("SELECT * FROM inbox")) == before
    assert bridge.db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0
    drain(bridge)
    assert calls == []


def test_post_does_not_revive_expired_input_and_execution_rechecks_permission(rig):
    bridge, api, provider, calls, _ = rig
    stale = post("/doc sample", 1)
    stale["event"]["message"]["create_time"] = str(int((time.time() - 86401) * 1000))
    assert not bridge.ingest(stale)
    assert not bridge.poc.store.rows("SELECT * FROM inbox")
    assert bridge.ingest(post("/doc sample", 2))
    gateway, store = bridge.poc.gateway, bridge.poc.store
    assert gateway.receive_one()
    api.authorized = lambda row: False
    gateway.run_task(store.claim(1))
    drain(bridge)
    assert provider.prompts == [] and calls == [] and api.sent == []
    assert store.rows("SELECT state FROM tasks") == [{"state": "failed"}]


def test_original_bridge_works_without_optional_poc_package(tmp_path):
    bridge_path = PROJECT.parent / "local-qwen3.8/feishu-bridge/bridge.py"
    code = '''
import importlib.util, json, sys
assert importlib.util.find_spec("fs_agent") is None
spec = importlib.util.spec_from_file_location("standalone_bridge", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
b = module.Bridge({"app_id":"cli_test", "access_mode":"all_private_users",
                   "state_directory":sys.argv[2]}, lambda *args: None)
payload = json.loads(sys.argv[3])
assert b.ingest(payload)
payload["event"]["message"].update(message_id="standalone-post", message_type="post",
    content=json.dumps({"title":"", "content":[[{"tag":"text","text":"synthetic"}]]}))
assert not b.ingest(payload)
b.db.close()
print("standalone-text-ok; unsupported-post-rejected")
'''
    # -I alone still loads editable packages from this service environment.
    # -S models the intended no-PoC installation without altering the real venv.
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(bridge_path),
                             str(tmp_path / "standalone"), json.dumps(event("合成文字", 1))],
                            capture_output=True, text=True, timeout=15, check=True)
    assert result.stdout.strip() == "standalone-text-ok; unsupported-post-rejected"


def test_ordinary_text_input_limit_keeps_local_notice_without_inference(rig):
    bridge, _, _, calls, replies = rig
    assert bridge.ingest(event("x" * 6001, 1, "ou_outsider"))
    assert bridge.db.execute("SELECT text FROM inbox").fetchone()[0] == "/input-too-long"
    drain(bridge)
    assert calls == [] and len(replies) == 1 and "6000" in replies[0][1]
