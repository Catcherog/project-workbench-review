"""Exercise the original Store/ModelCoordinator with a synthetic provider.

All state is temporary. No actual model, existing database, or service is used.
"""
from argparse import ArgumentParser
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import uuid


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--host-source", type=Path, required=True)
    args = parser.parse_args()
    source = args.host_source.resolve()
    names = ("fs_agent/store.py", "fs_agent/model_coordinator.py", "fs_agent/provider.py", "fs_agent/config.py")
    if not source.is_absolute() or not all((source / name).is_file() for name in names):
        parser.error("provide the existing source parent containing fs_agent")
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fs_agent.config import BoundaryError
    from fs_agent.model_coordinator import ModelCoordinator
    from fs_agent.provider import Result
    from fs_agent.store import Store
    from am_training_window.host import StoreMaintenanceFence

    class SyntheticProvider:
        def __init__(self):
            self.calls = 0
        def complete(self, *args, **kwargs):
            self.calls += 1
            return Result("synthetic", "test-only", 0.0)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = Store(root / "temporary.sqlite3")
        try:
            provider = SyntheticProvider()
            coordinator = ModelCoordinator(provider, store, root / "state")
            fence = StoreMaintenanceFence(store)
            assert coordinator.chat([]) == "synthetic"
            owner = str(uuid.uuid4())
            fence.claim(owner)
            fence.seal(owner)
            blocked = 0
            for invoke in (lambda: coordinator.complete("synthetic", run_id=uuid.uuid4().hex), lambda: coordinator.chat([])):
                try:
                    invoke()
                except BoundaryError as exc:
                    assert str(exc) == "MODEL_PAUSED"
                    blocked += 1
                else:
                    raise AssertionError("original coordinator bypassed maintenance fence")
            assert provider.calls == 1 and blocked == 2
            fence.release(owner)
            assert coordinator.chat([]) == "synthetic" and provider.calls == 2
        finally:
            store.conn.close()
    print(json.dumps({"status": "passed", "scenario": "existing Store + ModelCoordinator admission fence",
                      "source_sha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names},
                      "native_models_called": 0, "synthetic_provider_calls": 2,
                      "native_coordinator_blocked_calls": 2,
                      "state": "temporary_sqlite_and_lock_only",
                      "original_service_modified": False}, indent=2))


if __name__ == "__main__":
    main()
