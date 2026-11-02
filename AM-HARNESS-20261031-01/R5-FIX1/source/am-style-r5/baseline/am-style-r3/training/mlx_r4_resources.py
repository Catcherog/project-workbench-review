"""Original-coordinator lease and read-only shared-machine resource checks."""
from __future__ import annotations

import contextlib
import fcntl
import json
import sqlite3
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from training.common import TrainingInputError, file_hash, require_sha, required_text

PRODUCTION_MODEL = "qwen3.8:27b-bartowski-q8_0"
PRODUCTION_DIGEST = "52b6ea169d93070c185373f6ff9ec33a7a5e88cfe9c844fc225ed4214683baef"
TERMINAL = {"done", "completed", "expired", "timed_out", "failed", "cancelled", "canceled", "rejected"}


class ResourcePause(TrainingInputError):
    pass


def validate_service_paths(manifest):
    service = manifest.get("service", {})
    paths = {}
    for key in ("lease_file", "gateway_db", "chat_db"):
        path = Path(required_text(service, key))
        if not path.is_absolute() or not path.is_file():
            raise TrainingInputError(f"Existing original service path required: {key}")
        paths[key] = path.resolve()
    if paths["lease_file"].name != "model-coordinator.lock":
        raise TrainingInputError("Use the original model-coordinator lock, not a new experiment lock")
    protected = service.get("protected_config_files")
    if not isinstance(protected, dict) or not protected:
        raise TrainingInputError("Seal the original production config files before executing")
    for name, expected in protected.items():
        path = Path(name)
        if not path.is_absolute() or not path.is_file() or file_hash(path) != require_sha(expected, name):
            raise TrainingInputError("Protected production config differs from the sealed baseline")
    if service.get("expected_model") != PRODUCTION_MODEL or service.get("expected_digest") != PRODUCTION_DIGEST:
        raise TrainingInputError("Production identity must remain the recorded original Q8")
    return paths


def check_metrics(metrics, *, before_load, initial_swap_gib=None):
    if metrics["memory_pressure"] >= 4 or metrics["available_memory_GiB"] < (24 if before_load else 5):
        raise ResourcePause("Insufficient memory/critical pressure; no model unload or automatic retry")
    if metrics["pending_business"]:
        raise ResourcePause("New business work is pending; release the original lease")
    if initial_swap_gib is not None and metrics["swap_used_GiB"] - initial_swap_gib > 1:
        raise ResourcePause("Swap grew more than 1 GiB during this worker")
    for item in metrics["loaded_models"]:
        if item.get("name", item.get("model")) != PRODUCTION_MODEL or item.get("digest") != PRODUCTION_DIGEST:
            raise ResourcePause("Unexpected production model identity; do not replace/unload it")


class OriginalLease:
    def __init__(self, manifest, timeout_seconds):
        self.manifest = manifest
        self.paths = validate_service_paths(manifest)
        self.timeout = timeout_seconds
        self.started = None
        self.initial_swap = None
        self.stream = None
        self.history = []

    def __enter__(self):
        self.stream = self.paths["lease_file"].open("rb")
        try:
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.started = time.monotonic()
            self.check(before_load=True)
            return self
        except Exception:
            self.stream.close()
            raise

    def __exit__(self, *_):
        if self.stream:
            fcntl.flock(self.stream, fcntl.LOCK_UN)
            self.stream.close()

    def check(self, *, before_load=False):
        if time.monotonic() - self.started >= self.timeout - 10:
            raise ResourcePause("Worker resource window exhausted")
        validate_service_paths(self.manifest)
        import psutil  # existing local dependency; never auto-installed
        memory, swap = psutil.virtual_memory(), psutil.swap_memory()
        pressure = int(subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                       check=True, capture_output=True, text=True, timeout=3).stdout.strip())
        # Explicit no-proxy/no-redirect metadata request; never /api/generate/chat.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ResourcePause("Unexpected redirect from original local Ollama metadata endpoint")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open("http://127.0.0.1:11434/api/ps", timeout=2) as response:
            models = json.load(response)["models"]
        pending = 0
        with contextlib.closing(sqlite3.connect(self.paths["gateway_db"].as_uri() + "?mode=ro", uri=True, timeout=0.3)) as db:
            pending += db.execute("SELECT count(*) FROM am_harness_runs WHERE state IN ('queued','running')").fetchone()[0]
            pending += db.execute("SELECT count(*) FROM am_inbox WHERE state IN ('received','processing','harness_admitting') AND expires>strftime('%s','now')").fetchone()[0]
            pending += sum(count for state, count in db.execute("SELECT state,count(*) FROM tasks GROUP BY state") if state not in TERMINAL)
        with contextlib.closing(sqlite3.connect(self.paths["chat_db"].as_uri() + "?mode=ro", uri=True, timeout=0.3)) as db:
            pending += sum(count for state, count in db.execute("SELECT state,count(*) FROM inbox GROUP BY state") if state not in TERMINAL)
        metrics = {"available_memory_GiB": memory.available / 2**30, "memory_pressure": pressure,
                   "swap_used_GiB": swap.used / 2**30, "pending_business": pending,
                   "loaded_models": models, "elapsed_seconds": time.monotonic() - self.started,
                   "time_utc": datetime.now(timezone.utc).isoformat()}
        check_metrics(metrics, before_load=before_load, initial_swap_gib=self.initial_swap)
        if self.initial_swap is None:
            self.initial_swap = metrics["swap_used_GiB"]
        # Bounded in-memory audit history; errors abort rather than invoking a fallback model.
        self.history.append({key: value for key, value in metrics.items() if key != "loaded_models"})
        return metrics
