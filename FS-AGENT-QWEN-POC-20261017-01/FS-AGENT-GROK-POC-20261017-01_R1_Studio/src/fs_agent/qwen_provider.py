from __future__ import annotations

import json
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

from .config import BoundaryError, Config
from .local_api import LocalQwenClient
from .provider import ProcessRunner, Result, atomic_json


def api_request_unknown(directory: Path) -> bool:
    path = directory / "api-state.json"
    if not path.exists():
        return False  # The worker records in_flight before it can send the request.
    try:
        return json.loads(path.read_text()).get("state") not in ("response_complete", "not_dispatched")
    except (OSError, ValueError, AttributeError):
        return True


def discard_payload(directory: Path):
    # Keep only body-free process/request markers when the server's completion is unknown.
    for name in ("request.json", "stdout.tmp", "stderr.tmp"):
        (directory / name).unlink(missing_ok=True)


class LocalQwenProvider:
    def __init__(self, config: Config):
        self.config = config
        self.client = LocalQwenClient(config.api_base_url, config.api_model, config.api_model_digest)
        self.runner = ProcessRunner()

    def fingerprint(self):
        self.config.check_service()
        return self.client.fingerprint()

    def pin(self):
        path = self.config.root / "state" / "provider-pin.json"
        if not path.exists():
            raise BoundaryError("P1_REQUIRED")
        pin = json.loads(path.read_text())
        current = self.fingerprint()
        if not pin.get("real_p1_success") or any(pin.get(k) != v for k, v in current.items()):
            raise BoundaryError("LOCAL_PROVIDER_PIN_CHANGED")
        return pin

    def complete(self, prompt, *, run_id, timeout=120, on_start=None, discover=False):
        started = time.monotonic()
        self.config.check_service()
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise BoundaryError("INVALID_RUN_ID")
        if self.config.concurrency != 1:
            raise BoundaryError("QWEN_SINGLE_LANE_REQUIRED")
        self.fingerprint() if discover else self.pin()
        remaining = min(120, timeout) - (time.monotonic() - started)
        if remaining <= 0:
            raise BoundaryError("CONTENT_EXPIRED")
        directory = self.config.root / "tasks" / run_id
        directory.mkdir(mode=0o700)
        for name in ("home", "work", "tmp"):
            (directory / name).mkdir(mode=0o700)
        atomic_json(directory / "request.json", {
            "base_url": self.config.api_base_url, "model": self.config.api_model,
            "model_digest": self.config.api_model_digest, "max_tokens": self.config.api_max_tokens,
            "prompt": prompt, "timeout": remaining,
        })
        env = {"PATH": "/usr/bin:/bin", "HOME": str(directory / "home"),
               "TMPDIR": str(directory / "tmp"), "LANG": "en_US.UTF-8"}
        try:
            code, out, _ = self.runner.run(
                [sys.executable, "-I", "-m", "fs_agent.api_worker", str(directory / "request.json")],
                cwd=directory / "work", env=env, directory=directory, timeout=remaining, on_start=on_start)
            if api_request_unknown(directory):
                raise BoundaryError("STOP_UNKNOWN")
            data = json.loads(out)
            if code:
                error = data.get("error", "LOCAL_API_WORKER_FAILED")
                if not re.fullmatch(r"[A-Z_]{1,80}", error):
                    error = "LOCAL_API_WORKER_FAILED"
                raise BoundaryError(error)
            if data.get("model") != self.config.api_model or not isinstance(data.get("text"), str):
                raise BoundaryError("API_OUTPUT_SCHEMA_UNVERIFIED")
            return Result(data["text"], data["model"], time.monotonic() - started)
        finally:
            journal = directory / "process.json"
            if journal.exists() and json.loads(journal.read_text()).get("state") != "stopped":
                raise BoundaryError("STOP_UNKNOWN")
            if api_request_unknown(directory):
                discard_payload(directory)
                # A killed HTTP client is not proof that shared-server inference has ended.
                raise BoundaryError("STOP_UNKNOWN")
            shutil.rmtree(directory)

    def p1(self):
        fingerprint = self.fingerprint()
        path = self.config.root / "state" / "provider-pin.json"
        if path.exists():
            self.pin()
        run_id = uuid.uuid4().hex
        result = self.complete("合成验证：2+3 等于多少？只回复数字 5，不使用工具。", run_id=run_id,
                               discover=not path.exists())
        if result.text != "5":
            raise BoundaryError("P1_SYNTHETIC_ASSERTION_FAILED")
        receipt = dict(fingerprint, run_id=run_id, elapsed=result.elapsed,
                       real_p1_success=True, completed_at=time.time())
        atomic_json(path, receipt)
        return receipt
