"""A durable execution marker distinguishes new code work from old API work."""
from dataclasses import replace

import pytest

from fs_agent.store import CODE_PROGRESS_MODEL
from test_gateway import event, rig


@pytest.mark.parametrize("kind,expected", [
    ("code", "interrupted"), ("legacy_api", "stop_unknown"),
    ("inconsistent_marker", "stop_unknown"),
])
def test_recovery_only_exempts_explicit_code_execution(rig, kind, expected):
    gateway, store, _, provider, _ = rig
    gateway.config = replace(gateway.config, provider_kind="local_qwen_api", concurrency=1)
    assert gateway.ingest(event("/progress sample")) and gateway.receive_one()
    task = store.claim(1)
    assert task["model"] == CODE_PROGRESS_MODEL
    if kind == "legacy_api":
        store.execute("UPDATE tasks SET model=NULL WHERE id=?", (task["id"],))
    elif kind == "inconsistent_marker":
        store.execute("UPDATE tasks SET process_identity='unverified' WHERE id=?", (task["id"],))
    gateway.recover()
    assert store.rows("SELECT state FROM tasks WHERE id=?", (task["id"],)) == [{"state": expected}]
    assert provider.prompts == []
    assert gateway.ingest(event("/doc sample", number=2, user="ou_b")) and gateway.receive_one()
    following = store.claim(1)
    if kind == "code":
        assert following and following["user"] == "ou_b"
        store.finish(following, "failed", "SYNTHETIC_TEST_END")
        assert store.retry(task, task["id"])
    else:
        assert following is None
        assert not store.retry(task, task["id"])
