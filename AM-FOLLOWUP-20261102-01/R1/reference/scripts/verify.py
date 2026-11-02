"""Reproduce isolated tests/demo and retain exact result with source hashes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    output = root / "verification"
    output.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    started = datetime.now(timezone.utc).isoformat()
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    tests = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
    log = tests.stdout + tests.stderr
    (output / "test_output.txt").write_text(log, encoding="utf-8")
    demo_command = [sys.executable, "examples/demo.py"]
    demo = subprocess.run(demo_command, cwd=root, env=env, capture_output=True, text=True)
    (output / "demo_output.json").write_text(demo.stdout, encoding="utf-8")
    (output / "demo_stderr.txt").write_text(demo.stderr, encoding="utf-8")
    manifest = {}
    for folder in ("src", "tests", "examples", "scripts"):
        for path in sorted((root / folder).rglob("*.py")):
            manifest[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
    (output / "source_manifest.json").write_text(manifest_text + "\n", encoding="utf-8")
    count = re.search(r"Ran (\d+) tests?", log)
    result = {
        "task": "AM-FOLLOWUP-20261102-01", "round": "R1",
        "validation_kind": "synthetic_unit_concurrency_and_cross_module_only",
        "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "test_command": command,
        "test_count": int(count.group(1)) if count else None,
        "test_exit_code": tests.returncode, "demo_command": demo_command,
        "demo_exit_code": demo.returncode,
        "source_manifest_sha256": hashlib.sha256((manifest_text + "\n").encode()).hexdigest(),
        "real_qwen_tested": False, "real_feishu_messages_sent": 0,
        "original_am_integrated": False, "production_deployed": False,
        "user_business_acceptance": "pending",
    }
    (output / "test_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return tests.returncode or demo.returncode


if __name__ == "__main__":
    raise SystemExit(main())

