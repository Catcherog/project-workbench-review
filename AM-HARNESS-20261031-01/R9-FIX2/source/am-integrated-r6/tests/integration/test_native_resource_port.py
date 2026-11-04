"""Production control port rejects training requests before touching the host."""
import json
import time
from types import SimpleNamespace

import am_resource_window


def test_diagnostic_port_does_not_accept_trainer(tmp_path,monkeypatch):
    host=object.__new__(am_resource_window.NativeResourceWindow)
    monkeypatch.setattr(host,'setup',lambda:(_ for _ in ()).throw(AssertionError('setup reached')))
    request=tmp_path/'test.request.claimed'
    request.write_text(json.dumps({'operation':'train','expires_at':time.time()+10}))
    host.run(request)
    result=json.loads((tmp_path/'test.result.json').read_text())
    assert result['error']=='diagnostic_port_has_no_trainer'
    assert result['trainer_start_attempts']==0 and not result['ok']


def test_native_tick_keeps_live_control_thread_unique(tmp_path):
    host=object.__new__(am_resource_window.NativeResourceWindow)
    host.root=tmp_path
    host.thread=SimpleNamespace(is_alive=lambda:True)
    request=tmp_path/'queued.request.json';request.write_text('{}');request.chmod(0o600)
    assert host.tick() is False and request.exists()


def test_native_tick_does_not_claim_nonprivate_request(tmp_path):
    host=object.__new__(am_resource_window.NativeResourceWindow)
    host.root=tmp_path;host.thread=None
    request=tmp_path/'unsafe.request.json';request.write_text('{}');request.chmod(0o644)
    assert host.tick() is False and request.exists()
