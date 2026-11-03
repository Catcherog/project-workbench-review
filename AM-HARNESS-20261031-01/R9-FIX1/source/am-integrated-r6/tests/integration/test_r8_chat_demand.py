"""Ordinary-chat dispatch and real-process supervision with synthetic messages."""
import json
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import pytest
from bridge import Bridge
import am_training_control as control
import am_training_window.native_r5 as native
from am_training_window.process_guard import digest
from am_training_window.window import HostBinding, HostObservation, ModelIdentity
from test_r7_training_control import make_request


@pytest.fixture
def chat_host(tmp_path):
    calls, sent = [], []
    bridge = Bridge({'app_id': 'synthetic', 'state_directory': str(tmp_path/'chat')},
                    lambda mid, text: sent.append((mid, text)),
                    lambda messages: calls.append(messages) or 'synthetic answer')
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    db.executescript('CREATE TABLE am_harness_runs(state TEXT);'
                    'CREATE TABLE am_inbox(state TEXT,expires REAL);'
                    'CREATE TABLE tasks(state TEXT);'
                    'CREATE TABLE outbox(state TEXT,expires REAL);')
    host = object.__new__(control.NativeTrainingControl)
    host.store = SimpleNamespace(clock=time.time, rows=lambda sql, args=():
                                 list(db.execute(sql, args)))
    bridge.am_self = SimpleNamespace(training_requires_model=lambda row: True,
                                     conversation_futures=set())
    host.bridge = bridge
    def enqueue(text):
        mid = str(bridge.db.execute('SELECT count(*) FROM inbox').fetchone()[0])
        bridge.db.execute('INSERT INTO inbox VALUES(?,?,?,?,?,?,?,NULL)',
                          (mid, json.dumps(['tenant', 'app', 'chat', 'synthetic-user']), 'synthetic-user', text,
                           time.time(), time.time(), 'queued'))
        bridge.db.commit()
        return mid
    yield host, enqueue, calls, sent
    bridge.db.close(); db.close()


@pytest.mark.parametrize('command', ['/status', '/help', '/new', '/input-too-long'])
def test_control_alone_does_not_preempt_and_dispatches_while_paused(chat_host, command):
    host, enqueue, calls, sent = chat_host
    mid = enqueue(command)
    before = list(host.bridge.db.execute('SELECT * FROM inbox'))
    assert host.queue_counts()['ordinary_chat'] == 0
    assert [tuple(r) for r in before] == [tuple(r) for r in host.bridge.db.execute('SELECT * FROM inbox')]
    host.bridge.poc = SimpleNamespace(store=SimpleNamespace(meta=lambda key: 'maintenance'),
                                      config=SimpleNamespace(users=()), model_busy=lambda: False)
    assert host.bridge.process_one() is True
    assert not calls and sent[0][0] == mid
    assert host.bridge.db.execute('SELECT state FROM inbox').fetchone()[0] == 'done'


@pytest.mark.parametrize('text', ['real model question', '/status extra', '/STATUS', '', b'/help'])
def test_unknown_or_nonexact_input_still_counts_as_demand(chat_host, text):
    host, enqueue, _, _ = chat_host
    enqueue(text)
    assert host.queue_counts()['ordinary_chat'] == 1


def test_mixed_queue_preserves_demand_control_order_and_normal_answer(chat_host):
    host, enqueue, calls, sent = chat_host
    model_id = enqueue('real model question')
    for text in ('/help', '/status', '/input-too-long', '/new'): enqueue(text)
    host.bridge.poc = SimpleNamespace(store=SimpleNamespace(meta=lambda key: 'maintenance'),
                                      config=SimpleNamespace(users=()), model_busy=lambda: False)
    for _ in range(4):
        assert host.queue_counts()['ordinary_chat'] == 1
        assert host.bridge.process_one() is True
    assert not host.bridge.process_one() and not calls
    assert [mid for mid, _ in sent] == ['1', '2', '3', '4']
    host.bridge.poc = None
    assert host.bridge.process_one() is True
    assert calls == [[{'role': 'user', 'content': 'real model question'}]]
    assert sent[-1] == (model_id, 'synthetic answer')
    assert host.queue_counts()['ordinary_chat'] == 0


def test_model_arrival_uses_original_supervisor_and_stops_real_fixture_process(chat_host, tmp_path, monkeypatch):
    host, enqueue, _, _ = chat_host
    template, request = make_request(tmp_path, monkeypatch)
    host.root, host.plan_scope = template.root, template.plan_scope
    python = os.environ['AM_R7_TEST_PYTHON']
    plan_path = Path(request['plan']); plan = json.loads(plan_path.read_text())
    plan.update(python_interpreter={'path': python}, config={'path': str(tmp_path/'config.json')})
    plan_path.write_text(json.dumps(plan)); request['plan_sha256'] = digest(plan_path)
    monkeypatch.setattr(control, 'OriginalR5InputGate', lambda p: lambda: None)
    monkeypatch.setattr(native, 'OriginalR5InputGate', lambda p: lambda: None)
    command = [python, '-c', 'import time; time.sleep(30)']
    # The original executor hashes run.py; keep its genuine package root.
    from am_style_r5 import pilot
    monkeypatch.setattr(native.OriginalPilotExecutor, 'command', staticmethod(lambda p, v:
        (command, dict(os.environ, AM_R5_HOST_SRC='synthetic', AM_R5_TRAINING_ROOT='synthetic'), pilot.PACKAGE_ROOT)))
    binding = HostBinding('synthetic-instance', 'b'*64, ModelIdentity('original', 'a'*64), 'llamacpp')
    for text in ('/status', '/help', '/new', '/input-too-long'): enqueue(text)
    observations = []
    window_owner = None
    def inspect():
        # First sample permits the control-only queue; second occurs after Popen.
        if observations: enqueue('new real model question')
        counts = host.queue_counts(); observations.append(counts['ordinary_chat'])
        return HostObservation(binding, 1, True, True, 0, sum(counts.values()), (), window_owner)
    metrics = {'available_memory_GiB': 40, 'memory_pressure': 1, 'swap_used_GiB': 0,
               'pending_business': 0, 'loaded_models': []}
    monkeypatch.setattr(host, 'setup', lambda: (SimpleNamespace(inspect=inspect), binding,
        SimpleNamespace(events=[]), None, lambda: metrics.copy()))
    captured = []
    class Window:
        def __init__(self, *args):
            nonlocal window_owner
            window_owner = args[-1].data['window_id']
        def train(self, gate, executor, stopped):
            captured.append(executor)
            observation = executor()
            assert observation.status == 'blocked_or_failed'
            assert stopped() is True
            return {'status': 'failed_restored', 'synthetic_window_only': True}
    monkeypatch.setattr(control, 'TrainingWindow', Window)
    p = host.root/'test.request.claimed'; p.write_text(json.dumps(request))
    try:
        host.run(p)
        result = json.loads((host.root/'test.result.json').read_text())
        assert 'error' not in result, result
        execution = json.loads((host.root/(request['request_id']+'.evidence')/'execution.json').read_text())
        assert observations == [0, 1]
        assert execution['stop_reason'] == 'new_business_model_demand'
        assert execution['cli_start_attempts'] == 1
        assert execution['independent_worker_groups_gone'] is True
        assert execution['original_cli_group_gone'] is True
        assert captured[0].process.poll() is not None
    finally:
        for executor in captured:
            if executor.process is not None and executor.process.poll() is None:
                executor.guard.stop('fixture_cleanup', reap=executor.process.poll)
