"""Training control wiring uses synthetic ports; no actual fit is claimed."""
import json
from pathlib import Path
from types import SimpleNamespace
import time
import uuid
import sqlite3
import threading
from bridge import Bridge

import am_training_control as control
from am_training_window.native_r5 import OriginalPilotExecutor
from am_training_window.process_guard import digest
from am_training_window.window import HostBinding, ModelIdentity


def make_request(tmp_path, monkeypatch):
    monkeypatch.setattr(control, 'REPO', tmp_path)
    host = object.__new__(control.NativeTrainingControl)
    host.root = tmp_path/'control'; host.root.mkdir()
    host.plan_scope = tmp_path/'private'; host.plan_scope.mkdir()
    host.last_queue_classification = {'model_demand': {}}
    plan_dir = host.plan_scope/'plan'; plan_dir.mkdir()
    plan = plan_dir/'plan.json'
    plan.write_text(json.dumps({'runtime_source_binding': {'roots': {
        'am_style': str(tmp_path/'am-conversation-r1/src'), 'training': str(tmp_path/'am-style-r3')}},
        'manifest': {'path': str(tmp_path/'AM-HARNESS-20261031-01/R4/private/mlx-base.json')},
        'run_directory': str(host.plan_scope/'run-001')}))
    request = {'operation': 'train', 'request_id': str(uuid.uuid4()), 'expires_at': time.time()+60,
               'plan': str(plan), 'plan_sha256': digest(plan), 'run_id': 'run-001'}
    return host, request


def test_train_request_reaches_original_window_and_duplicate_never_relaunches(tmp_path, monkeypatch):
    host, request = make_request(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(control, 'OriginalR5InputGate', lambda path: lambda: calls.append('fresh_gate'))
    binding = HostBinding('test-instance', 'b'*64, ModelIdentity('original', 'a'*64), 'llamacpp')
    monkeypatch.setattr(host, 'setup', lambda: (None, binding, SimpleNamespace(events=[]), None, lambda: {}))
    class Window:
        def __init__(self, *args): self.journal = args[-1]
        def train(self, gate, executor, stopped):
            calls.append('TrainingWindow.train')
            assert isinstance(executor, OriginalPilotExecutor)
            assert executor.request_id == request['request_id']
            gate()
            return {'status': 'completed', 'synthetic_wiring_only': True}
    monkeypatch.setattr(control, 'TrainingWindow', Window)
    p = host.root/'first.request.claimed'; p.write_text(json.dumps(request)); host.run(p)
    assert json.loads((host.root/'first.result.json').read_text())['ok'] is True
    p = host.root/'duplicate.request.claimed'; p.write_text(json.dumps(request)); host.run(p)
    assert json.loads((host.root/'duplicate.result.json').read_text())['ok'] is False
    assert calls.count('TrainingWindow.train') == 1


def test_changed_plan_rejected_before_host_lifecycle(tmp_path, monkeypatch):
    host, request = make_request(tmp_path, monkeypatch)
    Path(request['plan']).write_text('{}')
    monkeypatch.setattr(host, 'setup', lambda: (_ for _ in ()).throw(AssertionError('host touched')))
    p = host.root/'changed.request.claimed'; p.write_text(json.dumps(request)); host.run(p)
    assert json.loads((host.root/'changed.result.json').read_text())['error'] == 'training_plan_scope_or_digest'


def test_cancel_is_bound_to_request_and_plan(tmp_path, monkeypatch):
    host, request = make_request(tmp_path, monkeypatch)
    p = host.root/(request['request_id']+'.cancel.json')
    p.write_text(json.dumps({k: request[k] for k in ('request_id', 'plan_sha256', 'expires_at')})); p.chmod(0o600)
    assert host.cancelled(request)


def test_native_cli_uses_real_run_file_and_explicit_current_roots(tmp_path):
    plan = {'python_interpreter': {'path': '/test/python'},
            'runtime_source_binding': {'roots': {'am_style': '/test/host', 'training': '/test/training'}}}
    argv, env, cwd = OriginalPilotExecutor.command(tmp_path/'plan.json', plan)
    assert argv[1] == str(cwd/'run.py') and (cwd/'run.py').is_file()
    assert argv[2:] == ['pilot-execute', '--plan', str(tmp_path/'plan.json'), '--execute']
    assert env['AM_R5_HOST_SRC'] == '/test/host' and env['AM_R5_TRAINING_ROOT'] == '/test/training'


def test_complete_model_demand_observation_preserves_pure_io(tmp_path):
    host = object.__new__(control.NativeTrainingControl)
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    db.executescript('''CREATE TABLE am_harness_runs(state TEXT);
        CREATE TABLE am_inbox(state TEXT,expires REAL,kind TEXT);
        CREATE TABLE tasks(state TEXT); CREATE TABLE outbox(state TEXT,expires REAL);
        INSERT INTO am_inbox VALUES('source_wait',99999999999,'conversation');
        INSERT INTO am_inbox VALUES('source_wait',99999999999,'text');
        INSERT INTO am_inbox VALUES('received',99999999999,'text');
        INSERT INTO outbox VALUES('pending',99999999999);''')
    host.store = SimpleNamespace(clock=lambda: time.time(), rows=lambda sql, args=():
                                [dict(r) for r in db.execute(sql, args)])
    chat = sqlite3.connect(':memory:'); chat.execute('CREATE TABLE inbox(state TEXT,text TEXT)')
    group = sqlite3.connect(':memory:'); group.row_factory = sqlite3.Row
    group.executescript("CREATE TABLE ledger_inbox(state TEXT,question TEXT);"
                       "INSERT INTO ledger_inbox VALUES('queued','help');"
                       "INSERT INTO ledger_inbox VALUES('queued','model query');")
    info_root = tmp_path/'info'; info_root.mkdir()
    with sqlite3.connect(info_root/'information.sqlite3') as c:
        from am_info_sync.models import Source
        c.executescript("CREATE TABLE jobs(kind TEXT,state TEXT,payload_json TEXT);"
                       "CREATE TABLE sources(source_id TEXT,config_json TEXT);")
        c.execute('INSERT INTO sources VALUES(?,?)', ('chat', json.dumps(Source('chat','im_chat','remote','tenant','owner').to_dict())))
        c.execute('INSERT INTO jobs VALUES(?,?,?)', ('extract','pending',json.dumps({'source_id':'chat'})))
        c.execute('INSERT INTO jobs VALUES(?,?,?)', ('collect','leased','{}'))
    probe = tmp_path/'probe'; (probe/'requests').mkdir(parents=True)
    finalizer = SimpleNamespace(directory=probe, future=None)
    am = SimpleNamespace(training_requires_model=lambda row: row['kind']=='conversation',
        conversation_futures=set(), conversation=SimpleNamespace(agent=SimpleNamespace(output_finalizer=finalizer)))
    host.bridge = SimpleNamespace(am_self=am, mutex=threading.RLock(), db=chat,
        ordinary_chat_requires_model=Bridge.ordinary_chat_requires_model,
        group_ledger=SimpleNamespace(mutex=threading.RLock(), db=group,
                                    can_process_without_model=lambda row: row['question']=='help'),
        information=SimpleNamespace(root=info_root))
    counts = host.queue_counts()
    assert counts['source_wait']==1 and counts['group_ledger_model']==1 and counts['information_extract']==1
    assert host.last_queue_classification['pure_io_am_rows']==2
    assert host.last_queue_classification['delivery_outbox']==1
    assert sum(counts.values())==3
    db.execute("DELETE FROM am_inbox WHERE kind='conversation'")
    group.execute("DELETE FROM ledger_inbox WHERE question='model query'")
    with sqlite3.connect(info_root/'information.sqlite3') as c:
        c.execute("DELETE FROM jobs WHERE kind='extract'")
    assert sum(host.queue_counts().values())==0
    (probe/'requests/queued.json').write_text('{}')
    assert host.queue_counts()['original_probe_queue']==1
    db.close(); chat.close(); group.close()


def test_structured_information_jobs_do_not_need_model_or_change_business_state(tmp_path):
    from am_info_sync.models import Source
    host=object.__new__(control.NativeTrainingControl)
    info=SimpleNamespace(root=tmp_path)
    path=tmp_path/'information.sqlite3'
    with sqlite3.connect(path) as c:
        c.executescript('CREATE TABLE sources(source_id TEXT,config_json TEXT);'
            'CREATE TABLE jobs(kind TEXT,state TEXT,payload_json TEXT);'
            'CREATE TABLE observations(source_id TEXT,object_id TEXT,version TEXT,payload_json TEXT);')
        sources=[Source('fields','bitable_snapshot','remote','tenant','owner',settings={'fact_mappings':{'record':{}}}),
                 Source('text','bitable_snapshot','remote','tenant','owner',settings={'fact_mappings':{'record':{}},'extract_text':True}),
                 Source('chat','im_chat','remote','tenant','owner',settings={'fact_mappings':{'record':{}}})]
        for s in sources:
            c.execute('INSERT INTO sources VALUES(?,?)',(s.source_id,json.dumps(s.to_dict())))
            c.execute('INSERT INTO jobs VALUES(?,?,?)',('extract','pending',json.dumps({'source_id':s.source_id})))
        c.execute('INSERT INTO jobs VALUES(?,?,?)',('extract','leased','{}'))
    before=path.read_bytes()
    assert host.information_demand(info)=={'model_required':2,'deterministic_io':1,'unknown':1}
    assert path.read_bytes()==before


def test_expired_request_does_not_touch_host(tmp_path, monkeypatch):
    host, request = make_request(tmp_path, monkeypatch)
    request['expires_at'] = time.time()-1
    monkeypatch.setattr(host, 'setup', lambda: (_ for _ in ()).throw(AssertionError('host touched')))
    p = host.root/'expired.request.claimed'; p.write_text(json.dumps(request)); host.run(p)
    assert json.loads((host.root/'expired.result.json').read_text())['error']=='training_request_expired_or_unbounded'


def test_eval_uses_same_training_window_without_bypassing_original_pilot(tmp_path, monkeypatch):
    host, request = make_request(tmp_path, monkeypatch)
    original = Path(request['plan'])
    eval_dir = host.plan_scope/'eval'; eval_dir.mkdir()
    plan = eval_dir/'plan.json'; plan.write_text('{}')
    request.update(operation='eval-mlx', pilot_plan=str(original), pilot_plan_sha256=digest(original),
                   plan=str(plan), plan_sha256=digest(plan), arm='mlx_base', run_id='eval-base-001')
    calls=[]
    monkeypatch.setattr(control, 'OriginalEvaluationGate', lambda *args: lambda: calls.append('eval_gate'))
    binding=HostBinding('test-instance','b'*64,ModelIdentity('original','a'*64),'llamacpp')
    monkeypatch.setattr(host,'setup',lambda:(None,binding,SimpleNamespace(events=[]),None,lambda:{}))
    class Window:
        def __init__(self,*args): pass
        def train(self,gate,executor,stopped):
            assert isinstance(executor,control.OriginalMlxEvalExecutor)
            calls.append('eval_window');gate()
            return {'status':'completed','synthetic_wiring_only':True}
    monkeypatch.setattr(control,'TrainingWindow',Window)
    p=host.root/'eval.request.claimed';p.write_text(json.dumps(request));host.run(p)
    assert json.loads((host.root/'eval.result.json').read_text())['ok'] is True
    assert calls.count('eval_window')==1 and calls.count('eval_gate')==2


def test_synthetic_request_is_explicit_and_keeps_original_window(tmp_path, monkeypatch):
    host,request=make_request(tmp_path,monkeypatch)
    request['operation']='train-synthetic'
    path=Path(request['plan']);plan=json.loads(path.read_text());plan['mode']='train';path.write_text(json.dumps(plan));request['plan_sha256']=digest(path)
    calls=[]
    monkeypatch.setattr(control,'SyntheticInputGate',lambda path:lambda:calls.append('synthetic_gate'))
    monkeypatch.setattr(control,'OriginalR5InputGate',lambda path:(_ for _ in ()).throw(AssertionError('gold gate repurposed')))
    binding=HostBinding('test-instance','b'*64,ModelIdentity('original','a'*64),'llamacpp')
    monkeypatch.setattr(host,'setup',lambda:(None,binding,SimpleNamespace(events=[]),None,lambda:{}))
    class Window:
        def __init__(self,*args):self.journal=args[-1]
        def train(self,gate,executor,stopped):
            assert isinstance(executor,control.SyntheticExecutor)
            assert self.journal.data['execution_kind']=='synthetic_SFT'
            gate();calls.append('original_resource_window');return {'status':'completed','fixture_only':True}
    monkeypatch.setattr(control,'TrainingWindow',Window)
    p=host.root/'synthetic.request.claimed';p.write_text(json.dumps(request));host.run(p)
    assert json.loads((host.root/'synthetic.result.json').read_text())['ok'] is True
    assert calls.count('original_resource_window')==1
    p=host.root/'duplicate-synthetic.request.claimed';p.write_text(json.dumps(request));host.run(p)
    assert json.loads((host.root/'duplicate-synthetic.result.json').read_text())['ok'] is False
    assert calls.count('original_resource_window')==1


def test_synthetic_mode_mismatch_stops_before_host(tmp_path,monkeypatch):
    host,request=make_request(tmp_path,monkeypatch);request['operation']='eval-synthetic'
    p=Path(request['plan']);plan=json.loads(p.read_text());plan['mode']='train';p.write_text(json.dumps(plan));request['plan_sha256']=digest(p)
    monkeypatch.setattr(host,'setup',lambda:(_ for _ in ()).throw(AssertionError('host touched')))
    q=host.root/'mismatch.request.claimed';q.write_text(json.dumps(request));host.run(q)
    assert json.loads((host.root/'mismatch.result.json').read_text())['error']=='synthetic_operation_plan_mismatch'
