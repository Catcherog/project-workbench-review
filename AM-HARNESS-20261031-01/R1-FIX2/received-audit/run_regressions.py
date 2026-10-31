#!/usr/bin/env python3
"""Run six isolated behavioral checks against the user's existing AM source.

This runner neither installs dependencies nor starts production services. Use the
project's existing Python environment. Tests import the original synthetic host
fixtures and deliberately assert correct behavior, so unfixed code must fail.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def fingerprints(source: Path) -> dict[str, str]:
    roots = (
        source / "FS-AGENT-GROK-POC-20261017-01_R1_Studio/src",
        source / "FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests",
        source / "am-conversation-r1/src",
        source / "local-qwen3.8/feishu-bridge",
    )
    result = {}
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" not in path.parts:
                result[path.relative_to(source).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source_root.resolve(), args.output.resolve()
    package = Path(__file__).resolve().parent
    if output.is_relative_to(source):
        parser.error("--output must be outside the source tree")
    studio = source / "FS-AGENT-GROK-POC-20261017-01_R1_Studio"
    paths = [studio / "src", studio / "tests", source / "am-conversation-r1/src", source / "local-qwen3.8/feishu-bridge"]
    for path in paths:
        if not path.is_dir():
            parser.error("Missing required source directory: " + str(path))
    if not (studio / "tests/test_harness_host.py").is_file():
        parser.error("The current source must contain the original synthetic host fixtures")
    output.mkdir(parents=True, exist_ok=True)
    before = fingerprints(source)
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join([*(str(path) for path in paths), environment.get("PYTHONPATH", "")])
    command = [sys.executable, "-m", "pytest", str(package / "tests"), "-q", "-s", "-p", "no:cacheprovider", "--junitxml=" + str(output / "regressions.xml")]
    started = time.time()
    timed_out = False
    with (output / "regressions.txt").open("w", encoding="utf-8") as log:
        try:
            code = subprocess.run(command, cwd=source, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180).returncode
        except subprocess.TimeoutExpired:
            code, timed_out = 2, True
    after = fingerprints(source)
    cases = []
    if (output / "regressions.xml").exists():
        for case in ET.parse(output / "regressions.xml").iter("testcase"):
            status = next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None), "passed")
            cases.append({"name": case.attrib["name"], "classname": case.attrib.get("classname", ""), "status": status})
    summary = {
        "task": "AM-HARNESS-20261031-01/R1-FIX2",
        "reviewed_audit_commit": "cd35c28d4524284b52e77763784ac4c2d15cd3e4",
        "reviewed_source_commit": "d3e40b0d27517d75e850613c4eaecec107efa0ea",
        "source_root": str(source), "python": platform.python_version(),
        "duration_seconds": round(time.time() - started, 3),
        "returncode": code, "timed_out": timed_out, "tests": len(cases),
        "passed": sum(c["status"] == "passed" for c in cases),
        "failures": sum(c["status"] == "failure" for c in cases),
        "errors": sum(c["status"] == "error" for c in cases),
        "skipped": sum(c["status"] == "skipped" for c in cases),
        "cases": cases, "source_stable_during_run": before == after,
        "source_python_files": len(before),
        "boundary": {"synthetic_only": True, "production_services_started": False, "real_qwen": False, "real_feishu": False, "human_acceptance": False},
    }
    (output / "source_sha256.json").write_text(json.dumps(before, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return code if before == after else 2


if __name__ == "__main__":
    raise SystemExit(main())
