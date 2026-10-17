"""Synthetic, offline verification. Nothing in this module calls Grok or Feishu."""
import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from fs_agent.config import Config
from fs_agent.feishu import SendUnknown, SendRejected
from fs_agent.gateway import Gateway
from fs_agent.provider import Result
from fs_agent.store import Store


class Clock:
    now = 1_800_000_000.0

    def __call__(self):
        return self.now


class OfflineApi:
    allowed = True

    def __init__(self):
        self.sent = []
        self.error = None
        self.checks = 0

    def authorized(self, row):
        self.checks += 1
        return self.allowed

    def send(self, row, guard):
        assert guard()
        if self.error:
            raise self.error
        self.sent.append(dict(row))
        return "om_" + row["id"]


class OfflineProvider:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return Result("OFFLINE_SYNTHETIC_RESULT", "grok-test-fixture", .01)


@pytest.fixture
def rig(tmp_path):
    for name in ("state", "tasks", "artifacts"):
        (tmp_path / name).mkdir()
    config = Config("_fsagent", tmp_path, tmp_path / "grok", tmp_path / "key", tmp_path / "secret",
                    "cli_test", "tenant_test", "ou_bot", ("ou_a", "ou_b"), ("od_test",),
                    ("oc_group1", "oc_group2"), "ou_a", True)
    clock, api, provider = Clock(), OfflineApi(), OfflineProvider()
    store = Store(tmp_path / "state" / "gateway.sqlite3", clock=clock)
    gateway = Gateway(config, store, api, provider)
    yield gateway, store, api, provider, clock
    gateway.stop()
    store.close()


def event(text="/doc sample", *, number=1, user="ou_a", chat="oc_dm", group=False, mentioned=True):
    return {"header": {"app_id": "cli_test", "tenant_key": "tenant_test", "event_id": f"e{number}",
                       "event_type": "im.message.receive_v1"},
            "event": {"sender": {"sender_type": "user", "tenant_key": "tenant_test", "sender_id": {"open_id": user}},
                      "message": {"message_id": f"om{number}", "chat_id": chat, "chat_type": "group" if group else "p2p",
                                  "message_type": "text", "create_time": "1800000000000",
                                  "content": json.dumps({"text": ("@_bot " if group and mentioned else "") + text}),
                                  "mentions": [{"key": "@_bot", "id": {"open_id": "ou_bot"}}] if mentioned else []}}}


def run_one(g, s, payload=None):
    assert g.ingest(payload or event())
    assert g.receive_one()
    task = s.claim()
    assert task
    g.run_task(task)
    return task


def drain(g):
    while g.deliver_one():
        pass


def test_offline_doc_fixed_file_and_private_delivery(rig):
    g, s, api, provider, _ = rig
    task = run_one(g, s)
    drain(g)
    path = g.config.root / "artifacts" / f"{task['id']}.md"
    assert path.read_text().startswith("# 合成文档")
    assert all(row["user"] == "ou_a" and row["chat_type"] == "p2p" for row in api.sent)
    assert {row["kind"] for row in api.sent} == {"text", "file"}
    assert len(provider.prompts) == 1


def test_api_recovery_keeps_unknown_server_request_blocked(rig):
    g, s, _, _, _ = rig
    g.config = replace(g.config, provider_kind="local_qwen_api", concurrency=1)
    assert g.ingest(event()) and g.receive_one()
    task = s.claim(1)
    directory = g.config.root / "tasks" / task["run_id"]
    directory.mkdir()
    (directory / "process.json").write_text(json.dumps({"state": "stopped"}))
    (directory / "api-state.json").write_text(json.dumps({"state": "in_flight"}))
    (directory / "request.json").write_text('synthetic prompt body')
    g.recover()
    row = s.rows("SELECT state,error FROM tasks WHERE id=?", (task["id"],))[0]
    assert row == {"state": "stop_unknown", "error": "STOP_UNKNOWN"}
    assert not (directory / "request.json").exists()
    assert g.ingest(event(number=2, user="ou_b")) and g.receive_one()
    assert s.claim(1) is None


def test_group_never_receives_model_detail_or_file(rig):
    g, s, api, _, _ = rig
    run_one(g, s, event(chat="oc_group1", group=True))
    drain(g)
    group = [r for r in api.sent if r["chat_type"] == "group"]
    assert group and all(r["kind"] == "text" and "OFFLINE" not in r["body"] for r in group)
    assert any(r["kind"] == "file" and r["chat_type"] == "p2p" for r in api.sent)


@pytest.mark.parametrize("payload", [event(user="ou_stranger"), event(chat="oc_other", group=True),
                                     event(chat="oc_group1", group=True, mentioned=False)])
def test_hard_scope_filter_before_persistence(rig, payload):
    g, s, *_ = rig
    assert not g.ingest(payload)
    assert not s.rows("SELECT * FROM inbox")


def test_tenant_and_app_mismatch(rig):
    g, s, *_ = rig
    for key in ("tenant_key", "app_id"):
        payload = event()
        payload["header"][key] = "wrong"
        assert not g.ingest(payload)


def test_message_dedupe_uses_app_tenant_message_not_just_event_id(rig):
    g, s, *_ = rig
    assert g.ingest(event())
    repeated = event()
    repeated["header"]["event_id"] = "different-platform-event"
    assert not g.ingest(repeated)
    assert len(s.rows("SELECT * FROM inbox")) == 1


def test_unselected_and_real_text_do_not_call_model(rig):
    g, s, _, provider, _ = rig
    assert g.ingest(event("arbitrary body"))
    g.receive_one()
    assert not s.claim()
    assert not provider.prompts
    assert s.rows("SELECT body FROM inbox")[0]["body"] is None


def test_menu_action_real_operator_and_version_binding(rig):
    g, s, api, *_ = rig
    g.ingest(event("/menu"))
    g.receive_one()
    drain(g)
    row = api.sent[0]
    card = {"header": {"app_id": "cli_test", "tenant_key": "tenant_test", "event_id": "card1", "event_type": "card.action.trigger"},
            "event": {"operator": {"open_id": "ou_b"}, "action": {"value": {"nonce": row["nonce"], "route": "doc", "user": "ou_a"}},
                      "context": {"open_chat_id": "oc_dm", "open_message_id": "om_" + row["id"]}}}
    assert not g.ingest(card)
    card["event"]["operator"]["open_id"] = "ou_a"
    assert g.ingest(card)
    g.receive_one()
    selection = s.rows("SELECT * FROM selection")[0]
    assert selection["route"] == "doc"
    card["header"]["event_id"] = "card2"
    card["event"]["action"]["value"]["route"] = "progress"
    assert g.ingest(card)
    g.receive_one()
    assert s.rows("SELECT * FROM selection")[0]["route"] == "doc"  # stale version ignored


def test_permission_rechecked_at_execution_and_delivery(rig):
    g, s, api, provider, _ = rig
    g.ingest(event())
    g.receive_one()
    api.allowed = False
    g.run_task(s.claim())
    assert not provider.prompts
    drain(g)
    assert not api.sent
    assert s.rows("SELECT state FROM tasks")[0]["state"] == "failed"


def test_unknown_send_never_blindly_retries_after_restart(rig):
    g, s, api, *_ = rig
    run_one(g, s)
    api.error = SendUnknown("SEND_RECEIPT_UNKNOWN")
    g.deliver_one()
    first = s.rows("SELECT * FROM outbox ORDER BY rowid")[0]
    assert first["state"] == "unknown"
    g.recover()
    assert s.rows("SELECT state FROM outbox WHERE id=?", (first["id"],))[0]["state"] == "unknown"


def test_private_delivery_failure_does_not_leak_to_group(rig):
    g, s, api, *_ = rig
    run_one(g, s, event(chat="oc_group1", group=True))
    api.error = SendRejected("NO_PRIVATE_SCOPE")
    drain(g)
    assert not api.sent
    assert all("OFFLINE" not in (r["body"] or "") for r in s.rows("SELECT * FROM outbox WHERE chat_type='group'"))


def test_absolute_ttl_includes_derived_results_and_files(rig):
    g, s, api, provider, clock = rig
    first = run_one(g, s)
    first_expiry = first["expires"]
    clock.now += 3600
    second_event = event("sample", number=2)
    second_event["event"]["message"]["create_time"] = str(int(clock.now * 1000))
    second = run_one(g, s, second_event)
    assert "OFFLINE_SYNTHETIC_RESULT" in provider.prompts[-1]
    assert s.rows("SELECT expires FROM tasks WHERE id=?", (second["id"],))[0]["expires"] == first_expiry
    clock.now = first_expiry
    g.cleanup()
    assert not g.deliver_one()
    assert not list((g.config.root / "artifacts").iterdir())
    assert all(r["body"] is None for r in s.rows("SELECT body FROM context"))
    assert all(r["body"] is None for r in s.rows("SELECT body FROM outbox"))
    assert not s.history(second)


def test_context_isolation_all_dimensions_and_future_messages(rig):
    g, s, *_ = rig
    first = run_one(g, s)
    for key, value in (("user", "ou_b"), ("chat", "oc_group1"), ("app", "other"), ("tenant", "other")):
        from fs_agent.store import scope_of
        other = dict(first, **{key: value})
        other["scope"] = scope_of(other, "doc")
        other["seq"] = 99
        assert not s.history(other)
    assert not s.history(first)  # Same seq is never included as previous history.


def test_scheduler_two_users_but_same_user_cross_chat_serial(rig):
    g, s, *_ = rig
    for number, user, chat in ((1, "ou_a", "oc_dm"), (2, "ou_a", "oc_group1"), (3, "ou_b", "oc_group2")):
        g.ingest(event(number=number, user=user, chat=chat, group=number > 1))
        g.receive_one()
    a = s.claim(2)
    b = s.claim(2)
    assert {a["user"], b["user"]} == {"ou_a", "ou_b"}
    assert s.claim(2) is None
    s.finish(a, "failed", "OFFLINE_TEST")
    assert s.claim(2)["user"] == "ou_a"


def test_actual_offline_worker_overlap_and_bound(rig):
    g, s, *_ = rig
    release, started = threading.Event(), threading.Event()
    calls = []
    def complete(prompt, **kwargs):
        calls.append(kwargs["run_id"])
        if len(calls) == 2:
            started.set()
        assert release.wait(3)
        return Result("OFFLINE_CONCURRENCY", "grok-test-fixture", .1)
    g.provider.complete = complete
    for number, user in ((1, "ou_a"), (2, "ou_b"), (3, "ou_a")):
        g.ingest(event(number=number, user=user))
        g.receive_one()
    assert g.schedule_one() and g.schedule_one()
    assert started.wait(2)
    assert not g.schedule_one()
    release.set()
    g.pool.shutdown(wait=True)
    assert len(calls) == 2


def test_queue_deadline_survives_restart_and_explicit_retry(rig):
    g, s, _, _, clock = rig
    g.ingest(event())
    g.receive_one()
    task = s.claim()
    g.recover()
    row = s.rows("SELECT * FROM inbox")[0]
    assert s.retry(row, task["id"])
    assert s.rows("SELECT queue_deadline FROM tasks")[0]["queue_deadline"] == task["queue_deadline"]
    clock.now += 601
    assert not s.claim()
    assert not s.retry(row, task["id"])


def test_stop_unknown_reserves_user_and_global_slot(rig):
    g, s, *_ = rig
    g.ingest(event())
    g.receive_one()
    task = s.claim()
    s.finish(task, "stop_unknown", "STOP_UNKNOWN")
    g.ingest(event(number=2, chat="oc_group1", group=True))
    g.receive_one()
    assert s.claim() is None
    g.ingest(event(number=3, user="ou_b"))
    g.receive_one()
    assert s.claim()["user"] == "ou_b"


def test_restart_keeps_committed_results_without_reexecution(rig):
    g, s, api, provider, _ = rig
    run_one(g, s)
    g.recover()
    drain(g)
    assert len(provider.prompts) == 1
    assert len(api.sent) == 3


def test_private_result_still_checks_original_group_scope(rig):
    g, s, api, *_ = rig
    run_one(g, s, event(chat="oc_group1", group=True))
    g.config = replace(g.config, chats=())
    drain(g)
    assert not api.sent


def test_missing_directory_does_not_prove_process_stopped(rig, monkeypatch):
    g, s, *_ = rig
    g.ingest(event())
    g.receive_one()
    task = s.claim()
    s.execute("UPDATE tasks SET pgid=987654,process_identity='old-identity' WHERE id=?", (task["id"],))
    monkeypatch.setattr("fs_agent.gateway.group_alive", lambda pid: True)
    monkeypatch.setattr("fs_agent.gateway.process_identity", lambda pid: "different-process")
    g.recover()
    assert s.rows("SELECT state FROM tasks")[0]["state"] == "stop_unknown"


def test_expired_redelivery_cannot_recreate_context(rig):
    g, s, _, _, clock = rig
    run_one(g, s)
    clock.now += 86401
    g.cleanup()
    replay = event()
    replay["header"]["event_id"] = "late-replay"
    assert not g.ingest(replay)
    assert len(s.rows("SELECT * FROM tasks")) == 1
