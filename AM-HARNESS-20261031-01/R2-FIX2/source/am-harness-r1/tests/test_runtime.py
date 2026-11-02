from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

from am_harness.config import HarnessConfig
from am_harness.controls import IngressController
from am_harness.runtime import TaskRuntime
from am_harness.store import DurableStore, Scope


class FunctionRunner:
    def __init__(self, callback):
        self.callback = callback
    def run(self, run):
        return self.callback(run)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DurableStore(Path(self.tmp.name) / "runs.sqlite")
        self.scope = Scope("t", "a", "u", "c")
        self.config = HarnessConfig(enabled=True, durable_queue_enabled=True, control_enabled=True,
                                    lease_seconds=5, heartbeat_seconds=.1)
        self.auth = lambda scope, operation: None

    def tearDown(self):
        self.tmp.cleanup()

    def runtime(self, fn, **kwargs):
        return TaskRuntime(self.store, FunctionRunner(fn), authorize=self.auth, config=self.config, **kwargs)

    def submit(self, runtime, text="input"):
        return runtime.submit(self.scope, "event", text, source_expires_at=time.time()+600)

    def test_cancel_during_blocked_runner_prevents_publish(self):
        entered, release = threading.Event(), threading.Event()
        def blocking(run):
            entered.set()
            self.assertTrue(release.wait(3))
            self.store.guard(run.fence)
            return {"text": "old result"}
        published, results = [], []
        runtime = self.runtime(blocking, publish=lambda c, r, o: published.append(o))
        run = self.submit(runtime)
        worker = threading.Thread(target=lambda: results.append(runtime.run_once("worker")))
        worker.start()
        self.assertTrue(entered.wait(3))
        control = IngressController(self.store, authorize=self.auth)
        begin = time.monotonic()
        control.handle(self.scope, "cancel", "停止当前任务")
        self.assertLess(time.monotonic()-begin, 1)
        self.assertEqual(self.store.lane_status()["state"], "active")
        release.set(); worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].status, "stale")
        self.assertFalse(published)
        self.assertEqual(self.store.get(self.scope, run.id).state, "cancelled")
        self.assertEqual(self.store.lane_status()["state"], "idle")

    def test_correction_releases_old_worker_then_runs_new_revision(self):
        entered, release = threading.Event(), threading.Event()
        texts = []
        def work(run):
            texts.append(run.input_text)
            if run.revision == 1:
                entered.set(); self.assertTrue(release.wait(3))
            self.store.guard(run.fence)
            return {"revision": run.revision}
        runtime = self.runtime(work)
        run = self.submit(runtime)
        result=[]
        worker=threading.Thread(target=lambda:result.append(runtime.run_once("one")))
        worker.start(); self.assertTrue(entered.wait(3))
        IngressController(self.store, authorize=self.auth).handle(self.scope,"revise","更正当前任务：new input")
        self.assertEqual(runtime.run_once("two").status,"idle")
        release.set(); worker.join(3)
        self.assertEqual(result[0].status,"stale")
        self.assertEqual(runtime.run_once("two").status,"completed")
        self.assertEqual(texts,["input","new input"])
        self.assertEqual(self.store.get(self.scope,run.id).result,{"revision":2})

    def test_worker_exception_quarantines_no_automatic_replay(self):
        def fail(run):
            raise RuntimeError("provider with sensitive arbitrary text")
        runtime=self.runtime(fail)
        run=self.submit(runtime)
        result=runtime.run_once("one")
        self.assertEqual((result.status,result.error),("unknown","RUNNER_FAILED"))
        self.assertEqual(self.store.lane_status()["state"],"quarantined")
        self.assertEqual(runtime.run_once("two").status,"idle")
        self.assertNotIn("sensitive",str(self.store.audit()))
        self.assertEqual(self.store.get(self.scope,run.id).state,"unknown")

    def test_busy_refusal_is_terminal_no_replay(self):
        def busy(run): raise RuntimeError("MODEL_BUSY")
        runtime=self.runtime(busy); run=self.submit(runtime)
        self.assertEqual(runtime.run_once("one").status,"failed")
        self.assertEqual(self.store.lane_status()["state"],"idle")
        self.assertEqual(runtime.run_once("two").status,"idle")
        self.assertEqual(self.store.get(self.scope,run.id).error,"MODEL_BUSY")

    def test_publish_failure_rolls_back_and_marks_known_returned_runner_failed(self):
        with sqlite3.connect(self.store.path) as conn: conn.execute("CREATE TABLE demo_effect(value TEXT)")
        def publish(conn, run, result):
            conn.execute("INSERT INTO demo_effect VALUES('must rollback')")
            raise RuntimeError("PUBLISH_FAILED")
        runtime=self.runtime(lambda run:{"text":"done"},publish=publish)
        run=self.submit(runtime)
        self.assertEqual(runtime.run_once("one").status,"failed")
        with sqlite3.connect(self.store.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM demo_effect").fetchone()[0],0)
        self.assertEqual(self.store.get(self.scope,run.id).error,"PUBLISH_FAILED")
        self.assertEqual(self.store.lane_status()["state"],"idle")

    def test_disabled_and_revoked_runtime_cannot_execute(self):
        disabled=TaskRuntime(self.store,FunctionRunner(lambda r:{}),authorize=self.auth)
        with self.assertRaisesRegex(RuntimeError,"HARNESS_QUEUE_DISABLED"):
            disabled.submit(self.scope,"off","text",source_expires_at=time.time()+100)
        called=[]
        runtime=self.runtime(lambda r:called.append(r) or {})
        self.submit(runtime)
        runtime.authorize=lambda s,op: (_ for _ in ()).throw(RuntimeError("AUTHORIZATION_DENIED"))
        self.assertEqual(runtime.run_once("one").status,"failed")
        self.assertFalse(called)
