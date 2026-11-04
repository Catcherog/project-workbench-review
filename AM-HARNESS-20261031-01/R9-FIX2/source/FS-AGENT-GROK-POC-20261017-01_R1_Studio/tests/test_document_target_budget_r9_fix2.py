"""Read budgets use a synthetic monotonic clock and mocked subprocess; no waits."""
from contextvars import Context
import json
from types import SimpleNamespace

import pytest

import fs_agent.document_delivery as delivery_module
import fs_agent.meegle_port as port_module
from fs_agent.config import BoundaryError
from fs_agent.document_delivery import discover_targets
from fs_agent.meegle_port import MeeglePort
from test_document_targets_r9_fix2 import target_rig, rig, base_rig, charter, assert_no_write


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def real_runner(monkeypatch, port, *, step=0.0, after=None, response=None):
    """Exercise production _run, replacing only the subprocess boundary."""
    clock = Clock()
    clock_module = SimpleNamespace(monotonic=clock)
    monkeypatch.setattr(port_module, "time", clock_module)
    monkeypatch.setattr(delivery_module, "time", clock_module)
    original = port._run
    calls = []

    def process(command, *, env, capture_output, timeout):
        calls.append({"args": command[1:-4], "timeout": timeout})
        data = original(command[1:-4]) if response is None else response
        clock.now += step
        if after is not None:
            after()
        return SimpleNamespace(returncode=0, stdout=json.dumps(data).encode())

    monkeypatch.setattr(port_module.subprocess, "run", process)
    port._run = MeeglePort._run.__get__(port, MeeglePort)
    return clock, calls


def test_subprocess_timeout_uses_remaining_outer_budget_and_nested_scope_cannot_extend_it(target_rig, monkeypatch):
    _, store, row, _, port, _, _ = target_rig
    row = dict(row, expires=store.clock() + 500)
    clock, calls = real_runner(monkeypatch, port, step=20, response={})
    with port.read_scope(row, deadline=clock() + 55):
        port._run(["user", "me"])
        with port.read_scope(row, deadline=clock() + 120):
            port._run(["user", "me"])
        assert port._read_timeout() == 15
    assert [call["timeout"] for call in calls] == [40, 35]
    assert port._read_context.get() is None


def test_expired_scope_never_starts_a_subprocess(target_rig, monkeypatch):
    _, _, row, _, port, state, _ = target_rig
    clock, calls = real_runner(monkeypatch, port, response={})
    with port.read_scope(row, deadline=clock()):
        with pytest.raises(BoundaryError, match="BUSINESS_READ_DEADLINE"):
            port._run(["user", "me"])
    assert calls == []
    assert_no_write(state)


def test_guard_is_checked_after_io_and_before_any_later_io(target_rig, monkeypatch):
    _, _, row, _, port, state, _ = target_rig
    allowed = [True]
    clock, calls = real_runner(monkeypatch, port, response={}, after=lambda: allowed.__setitem__(0, False))
    with port.read_scope(row, guard=lambda: allowed[0], deadline=clock() + 20):
        with pytest.raises(BoundaryError, match="DOCUMENT_DELIVERY_SCOPE_CHANGED"):
            port._run(["user", "me"])
        with pytest.raises(BoundaryError, match="DOCUMENT_DELIVERY_SCOPE_CHANGED"):
            port._run(["user", "me"])
    assert len(calls) == 1
    assert_no_write(state)


def test_io_finishing_at_deadline_is_not_used_and_next_read_is_not_started(target_rig, monkeypatch):
    _, _, row, _, port, _, _ = target_rig
    clock, calls = real_runner(monkeypatch, port, step=5, response={})
    with port.read_scope(row, deadline=clock() + 5):
        for _ in range(2):
            with pytest.raises(BoundaryError, match="BUSINESS_READ_DEADLINE"):
                port._run(["user", "me"])
    assert len(calls) == 1 and calls[0]["timeout"] == 5


@pytest.mark.parametrize("ttl,step,expected", [(500, 40, [40, 40, 40]), (7, 7, [7])])
def test_standalone_state_has_whole_read_budget_and_row_expiry(target_rig, monkeypatch, ttl, step, expected):
    _, store, row, _, port, state, _ = target_rig
    row = dict(row, expires=store.clock() + ttl)
    _, calls = real_runner(monkeypatch, port, step=step)
    with pytest.raises(BoundaryError, match="BUSINESS_READ_DEADLINE"):
        port.resolve(row, "report")
    assert [call["timeout"] for call in calls] == expected
    assert_no_write(state)


def test_discovery_and_identity_reread_share_one_budget(target_rig, monkeypatch):
    _, store, row, _, port, state, binding = target_rig
    row = dict(row, expires=store.clock() + 500)
    charter(state, binding)
    clock, calls = real_runner(monkeypatch, port, step=1)
    result = discover_targets(port, row, project_code="IRAD-2099-001", doc_type="charter",
                              guard=lambda: True, deadline=clock() + 8)
    assert result["state"] == "unresolved" and result["targets"] == []
    assert result["diagnostics"][0]["stage"] == "document_identity"
    assert result["diagnostics"][0]["error_code"] == "BUSINESS_READ_DEADLINE"
    assert [call["timeout"] for call in calls] == list(range(8, 0, -1))
    assert_no_write(state)


def test_metadata_page_does_not_renew_budget_or_start_next_page_after_expiry(target_rig, monkeypatch):
    _, _, row, _, port, state, _ = target_rig
    state["metadata_response"] = {"list": [], "pagination": {"has_more": True}}
    clock, calls = real_runner(monkeypatch, port, step=1)
    result = discover_targets(port, row, project_code="IRAD-2099-001", doc_type="charter",
                              guard=lambda: True, deadline=clock() + 2)
    assert result["state"] == "unresolved"
    assert result["diagnostics"][0]["error_code"] == "BUSINESS_READ_DEADLINE"
    assert [call["args"][:2] for call in calls] == [["user", "me"], ["workitem", "meta-fields"]]
    assert calls[-1]["timeout"] == 1
    assert_no_write(state)


def test_read_budget_is_context_local_and_restored_after_nested_exception(target_rig, monkeypatch):
    _, _, row, _, port, _, _ = target_rig
    clock, _ = real_runner(monkeypatch, port, response={})
    with port.read_scope(row, deadline=clock() + 10):
        assert port._read_timeout() == 10
        assert Context().run(port._read_timeout) == 40
        with pytest.raises(ValueError):
            with port.read_scope(row, deadline=clock() + 2):
                assert port._read_timeout() == 2
                raise ValueError("synthetic")
        assert port._read_timeout() == 10
    assert port._read_context.get() is None
