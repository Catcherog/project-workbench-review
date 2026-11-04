#!/usr/bin/env python3
"""Run the existing synthetic suites against an explicit source snapshot.

Does not install dependencies, apply patches, load a service, or call a model.
Connections are limited to ephemeral loopback listeners created by the test
process itself; existing model or platform services are not allowed. Use the native environment's pinned
dependencies; --deps is only for an isolated dependency directory when needed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import socket
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--deps", type=Path)
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    root = args.source.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    import_dirs = [
        root / "FS-AGENT-GROK-POC-20261017-01_R1_Studio/src",
        root / "local-qwen3.8/feishu-bridge",
        root / "am-conversation-r1/src",
        root / "am-integrated-r6",
        root / "am-style-r5/src",
        root / "FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests",
    ]
    # The legacy UX suites deliberately write evidence under AM-SELF-*/.
    # Track all runtime/config/test files in the five delivered code roots;
    # generated evidence is an output, not an edited execution source.
    source_roots = {p.relative_to(root).parts[0] for p in import_dirs}
    if args.deps:
        import_dirs.insert(0, args.deps.resolve(strict=True))
    sys.path[:0] = [str(p) for p in import_dirs]
    os.environ['PYTHONPATH'] = os.pathsep.join([str(p) for p in import_dirs] +
        ([os.environ['PYTHONPATH']] if os.environ.get('PYTHONPATH') else []))
    os.environ['AM_R7_TEST_PYTHON'] = sys.executable
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.chdir(root)
    import pytest

    def snapshot_files():
        files = {}
        for path in sorted(root.rglob("*")):
            if (path.relative_to(root).parts[0] not in source_roots or not path.is_file()) or any(p.startswith(".") or p == "__pycache__"
                                         for p in path.relative_to(root).parts):
                continue
            files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return files
    source_files = snapshot_files()
    denied_connections = []
    fixture_listeners = []
    fixture_connections = []

    def network_fence(event, values):
        if event == 'socket.bind':
            sock,address=values
            if (isinstance(address,tuple) and len(address)>=2 and address[0] in ('127.0.0.1','::1','localhost')
                    and address[1]==0 and sock.family in (socket.AF_INET,socket.AF_INET6)):
                fixture_listeners.append(sock)
        if event in ("socket.connect", "socket.sendto"):
            address=values[-1]
            if isinstance(address,tuple) and len(address)>=2 and address[0] in ('127.0.0.1','::1','localhost'):
                for listener in fixture_listeners:
                    try:
                        if listener.getsockname()[1]==address[1] and address[1]!=0:
                            fixture_connections.append(event)
                            return
                    except OSError:
                        pass
            # Do not persist addresses or payloads in a distributable report.
            denied_connections.append(event)
            raise PermissionError("OFFLINE_VERIFICATION_NETWORK_DENIED")

    sys.addaudithook(network_fence)
    records = []
    collection_errors = []

    class Results:
        def pytest_runtest_logreport(self, report):
            item = {"nodeid": report.nodeid, "phase": report.when,
                    "outcome": report.outcome, "seconds": report.duration}
            if report.failed:
                crash = getattr(report.longrepr, "reprcrash", None)
                item["message"] = (crash.message if crash else str(report.longrepr)).replace(str(root), "<source>")
            if report.skipped:
                item["reason"] = str(report.longrepr).replace(str(root), "<source>")
            records.append(item)

        def pytest_collectreport(self, report):
            if report.failed:
                collection_errors.append({"nodeid": report.nodeid,
                    "message": str(report.longrepr).replace(str(root), "<source>")})

    tests = args.tests or [str(p.relative_to(root)) for p in sorted(root.rglob("test_*.py"))]
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    command = ["-q", "--tb=short", "--rootdir=" + str(root), "-p", "no:cacheprovider",
               "--junitxml=" + str(output / "junit.xml"), *tests]
    code = int(pytest.main(command, plugins=[Results()]))
    final_source_files = snapshot_files()
    counts = Counter(r["outcome"] for r in records if r["phase"] == "call")
    failures = [r for r in records if r["outcome"] == "failed"]
    dependencies = {}
    for name in ("pytest", "lark-oapi", "pycryptodome", "pypdf", "python-docx", "websockets", "requests", "httpx"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    result = {"schema": "am-offline-verification/1", "started_utc": started,
        "duration_seconds": time.monotonic() - t0, "exit_code": code,
        "source_root": str(root), "python": platform.python_version(),
        "platform": platform.platform(), "dependencies": dependencies,
        "pytest_arguments": command, "counts": dict(counts),
        "failures": failures, "collection_errors": collection_errors,
        "denied_network_calls": len(denied_connections),
        "synthetic_fixture_connections": len(fixture_connections),
        "source_unchanged_during_run": final_source_files == source_files,
        "source_scope_roots": sorted(source_roots),
        "changed_during_run": sorted(k for k in set(source_files) | set(final_source_files)
            if source_files.get(k) != final_source_files.get(k)),
        "records": records, "source_sha256": source_files}
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("exit_code", "counts", "denied_network_calls", "duration_seconds")}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
