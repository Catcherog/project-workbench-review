"""Exercise patched original queue classes against temporary SQLite.

All model/provider behavior is synthetic. Native R4 business-count SQL is
observed without invoking its trainer, metadata service, or machine probes.
"""
from argparse import ArgumentParser
from dataclasses import asdict
import hashlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--host-source", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    args = parser.parse_args()
    source, overlay = args.host_source.resolve(), args.overlay.resolve()
    package_root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(package_root), str(source)]
    import fs_agent, am_harness
    relative = Path("FS-AGENT-GROK-POC-20261017-01_R1_Studio/src")
    fs_agent.__path__.insert(0, str(overlay / relative / "fs_agent"))
    am_harness.__path__.insert(0, str(overlay / relative / "am_harness"))
    from fs_agent.config import BoundaryError
    from fs_agent.model_coordinator import ModelCoordinator
    from fs_agent.provider import Result
    from fs_agent.store import Store
    from am_harness.config import HarnessConfig
    from am_harness.runtime import TaskRuntime
    from am_harness.store import DurableStore, Scope
    from am_training_window.host import ExistingCoordinatorHost, StoreMaintenanceFence
    from am_training_window.window import HostBinding, HostObservation, Journal, ModelIdentity, TrainingWindow

    class Provider:
        calls = 0
        def complete(self, *args, **kwargs):
            self.calls += 1
            return Result("synthetic", "test-only", 0.0)

    class MustNotStart:
        calls = 0
        def run(self, run):
            self.calls += 1
            # This reproduces the historical poison path if a claim gets past
            # the guard: TaskRuntime would quarantine MODEL_PAUSED as unknown.
            raise BoundaryError("MODEL_PAUSED")

    class Lifecycle:
        calls = []
        def suspend(self, binding): self.calls.append("suspend")
        def restore(self, binding): self.calls.append("restore")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = Store(root / "gateway.sqlite3")
        try:
            provider = Provider()
            coordinator = ModelCoordinator(provider, store, root / "state")
            queue = DurableStore(root / "gateway.sqlite3")
            scope = Scope("test-tenant", "test-app", "test-user", "test-chat")
            clock = time.time()
            run = queue.submit(scope, "test-event", "synthetic input", deadline=clock+120, expires_at=clock+600)
            event = {"tenant":scope.tenant_id,"app":scope.app_id,"user":scope.actor_id,"chat":scope.chat_id,
                     "chat_type":"p2p","kind":"text","event_id":"legacy-test-event","message_id":"legacy-message",
                     "body":"synthetic", "source_time":clock}
            assert store.put(event)
            task = store.enqueue(store.pending_inbox()[0], "doc", acknowledgement=False)
            fence = StoreMaintenanceFence(store)
            owner = str(uuid.uuid4())
            fence.claim(owner)
            assert not store.meta("provider_pause")
            assert store.claim(1) is None
            runner = MustNotStart()
            runtime = TaskRuntime(queue, runner, authorize=lambda scope, op: None,
                                  config=HarnessConfig(enabled=True, durable_queue_enabled=True))
            result = runtime.run_once("test-worker")
            assert result.status == "idle" and runner.calls == 0
            assert queue.get(scope, run.id).state == "queued" and queue.lane_status()["state"] == "idle"
            legacy = store.rows("SELECT state,attempts FROM tasks WHERE id=?", (task,))[0]
            assert legacy == {"state":"queued", "attempts":0}
            # Exact R4 queries still see the new pending work. No fake terminal
            # transition was used to clear the resource eligibility counter.
            count = store.rows("SELECT count(*) AS n FROM am_harness_runs WHERE state IN ('queued','running')")[0]["n"]
            count += store.rows("SELECT count(*) AS n FROM tasks WHERE state='queued'")[0]["n"]
            assert count == 2
            fence.release(owner)

            model = ModelIdentity("qwen3.8:27b-bartowski-q8_0", "a"*64)
            binding = HostBinding("synthetic-original-instance", "b"*64, model, "llamacpp")
            lifecycle = Lifecycle()
            def observe():
                return HostObservation(binding,1,True,True,0,2,(model,),None)
            host = ExistingCoordinatorHost(coordinator=coordinator,store=store,
                read_observation=observe,lifecycle=lifecycle,drain_timeout_seconds=0)
            from contextlib import nullcontext
            window = TrainingWindow(host,binding,nullcontext,lambda:{},Journal.create(root/"busy.json","diagnostic",binding))
            busy = window.diagnostic()
            assert busy["status"] == "failed_restored" and not busy["trainer_invoked"]
            assert lifecycle.calls == [] and not store.meta("provider_pause")
            assert not store.meta("resource_window_owner")
            assert queue.get(scope,run.id).state == "queued"

            # Already-running multi-step work remains able to call its original
            # coordinator while owner-only admission is being drained.
            lease = queue.claim("existing-worker",lease_seconds=30)
            assert lease is not None and lease.run.id == run.id
            owner = str(uuid.uuid4());fence.claim(owner)
            assert coordinator.chat([]) == "synthetic" and provider.calls == 1
            assert queue.finish(lease,result={"synthetic":True})
            assert queue.get(scope,run.id).state == "succeeded"
            fence.release(owner)
            # Authenticated cancellation remains available while new model
            # claims are blocked, and is never reinterpreted as inference.
            next_run = queue.submit(scope,"cancel-test","synthetic",deadline=clock+120,expires_at=clock+600)
            owner=str(uuid.uuid4());fence.claim(owner)
            assert queue.cancel(scope,"cancel-event",next_run.id).state == "cancelled"
            fence.release(owner)
        finally:
            store.conn.close()
    paths = {"Store":Path(inspect.getfile(Store)), "DurableStore":Path(inspect.getfile(DurableStore)),
             "TaskRuntime":Path(inspect.getfile(TaskRuntime))}
    print(json.dumps({"status":"passed", "source_sha256":{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in paths.items()},
        "scenarios":["original legacy task remains queued with attempts=0", "original durable task remains queued and lane idle",
                     "historical MODEL_PAUSED quarantine path is never entered", "original R4 pending queries retain both jobs",
                     "busy window has no model unload or provider pause", "already-running multi-step task completes during drain",
                     "authenticated cancellation still changes only its intended task"],
        "native_model_calls":0,"trainer_attempts":0,"synthetic_provider_calls":1,
        "original_service_modified":False,"scope":"temporary database and original patched classes only"},indent=2))


if __name__ == "__main__":
    main()
