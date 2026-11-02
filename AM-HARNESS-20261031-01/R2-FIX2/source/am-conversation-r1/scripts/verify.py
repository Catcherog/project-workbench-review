#!/usr/bin/env python3
"""Run the complete local test suite and write reproducible verification evidence.

This entry point uses only the Python standard library. External integrations in
these tests use fixtures/test doubles; passing does not establish live Qwen,
Feishu delivery, production deployment, or human business acceptance.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import py_compile
import sys
import tempfile
import time
import traceback
import unittest
import xml.etree.ElementTree as ET


CODE_DIRS = ("src", "tests", "scripts")
EXCLUDED_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def code_snapshot(root: Path) -> dict:
    """Hash exactly the current source/test/script files, excluding caches."""
    files = {}
    for directory in CODE_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(root)
            if (not path.is_file() or path.is_symlink()
                    or any(part in EXCLUDED_DIRS for part in relative.parts)
                    or path.suffix in {".pyc", ".pyo"}):
                continue
            content = path.read_bytes()
            files[relative.as_posix()] = {
                "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"files": files, "code_fingerprint": hashlib.sha256(encoded).hexdigest()}


def write_json(path: Path, value: dict) -> bytes:
    content = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return content


class RecordingResult(unittest.TextTestResult):
    """Capture JUnit outcomes, including subtest and class-fixture failures."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self._records = {}
        self._active = None

    def _case(self, test):
        ident = id(test)
        if ident in self._records:
            return self._records[ident]
        # unittest reports subtests without startTest(). Attach their outcomes
        # to the executing test method, preserving the subtest id in messages.
        parent = getattr(test, "test_case", None)
        if parent is not None and id(parent) in self._records:
            return self._records[id(parent)]
        case = {"id": test.id(), "started": time.perf_counter(), "seconds": 0.0,
                "outcomes": []}
        self.cases.append(case)
        self._records[ident] = case
        return case

    def startTest(self, test):
        self._active = self._case(test)
        super().startTest(test)

    def stopTest(self, test):
        case = self._case(test)
        case["seconds"] = max(0.0, time.perf_counter() - case["started"])
        super().stopTest(test)
        self._active = None

    def _outcome(self, test, kind, message, detail="", error_type=""):
        self._case(test)["outcomes"].append({"kind": kind, "message": message,
                                               "detail": detail, "type": error_type})

    def addFailure(self, test, err):
        self._outcome(test, "failure", str(err[1]), self._exc_info_to_string(err, test), err[0].__name__)
        super().addFailure(test, err)

    def addError(self, test, err):
        self._outcome(test, "error", str(err[1]), self._exc_info_to_string(err, test), err[0].__name__)
        super().addError(test, err)

    def addSkip(self, test, reason):
        self._outcome(test, "skipped", str(reason))
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self._outcome(test, "skipped", "expected failure", self._exc_info_to_string(err, test), err[0].__name__)
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self._outcome(test, "failure", "Test marked expectedFailure unexpectedly passed", error_type="UnexpectedSuccess")
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            kind = "failure" if issubclass(err[0], test.failureException) else "error"
            self._outcome(test, kind, subtest.id() + ": " + str(err[1]),
                          self._exc_info_to_string(err, subtest), err[0].__name__)
        super().addSubTest(test, subtest, err)


def write_junit(path: Path, result: RecordingResult | None, elapsed: float,
                started: str, infrastructure_errors: list[str], compile_errors: list[dict]) -> None:
    cases = list(result.cases) if result is not None else []
    for error in infrastructure_errors:
        cases.append({"id": "verification.infrastructure", "seconds": 0,
                      "outcomes": [{"kind": "error", "message": "Verification infrastructure error",
                                    "detail": error, "type": "VerificationError"}]})
    for error in compile_errors:
        cases.append({"id": "syntax." + error["path"], "seconds": 0,
                      "outcomes": [{"kind": "error", "message": "Python syntax check failed",
                                    "detail": error["error"], "type": "PyCompileError"}]})
    def has(case, kind):
        return any(outcome["kind"] == kind for outcome in case["outcomes"])
    suite = ET.Element("testsuite", {
        "name": "AM conversation R1 local verification", "tests": str(len(cases)),
        "failures": str(sum(has(case, "failure") for case in cases)),
        "errors": str(sum(has(case, "error") for case in cases)),
        "skipped": str(sum(has(case, "skipped") for case in cases)),
        "time": f"{elapsed:.6f}", "timestamp": started})
    properties = ET.SubElement(suite, "properties")
    for name, value in {
        "python_version": platform.python_version(),
        "unittest_tests_run": str(result.testsRun if result is not None else 0),
        "integration_mode": "mock-only",
        "live_qwen": "false", "live_feishu": "false",
    }.items():
        ET.SubElement(properties, "property", {"name": name, "value": value})
    for case in cases:
        class_name, _, name = case["id"].rpartition(".")
        node = ET.SubElement(suite, "testcase", {
            "classname": class_name or "verification", "name": name or case["id"],
            "time": f"{case['seconds']:.6f}"})
        for outcome in case["outcomes"]:
            attributes = {"message": outcome["message"]}
            if outcome["type"]:
                attributes["type"] = outcome["type"]
            child = ET.SubElement(node, outcome["kind"], attributes)
            child.text = outcome["detail"]
    ET.SubElement(suite, "system-out").text = (
        "Complete runner output: unit-tests.txt. Local unit/fixture results only; "
        "no live Qwen, Feishu, deployment, or human business acceptance is claimed.")
    ET.indent(suite, space="  ")
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="Evidence directory; default is this project's evidence/.")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    output = (args.output_dir or root / "evidence").resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "src"))
    sys.path.insert(1, str(root))
    started_at = utc_now()
    started = time.perf_counter()
    before = code_snapshot(root)
    infrastructure_errors = []
    compile_errors = []
    compiled_count = 0
    result_holder = {}
    def result_factory(*runner_args, **runner_kwargs):
        result = RecordingResult(*runner_args, **runner_kwargs)
        result_holder["result"] = result
        return result

    log_path = output / "unit-tests.txt"
    with log_path.open("w", encoding="utf-8") as log:
        log.write("AM conversation R1 — local unit/fixture verification\n")
        log.write(f"UTC start: {started_at}\nPython: {platform.python_version()}\n")
        log.write("External integration boundary: mock-only; no live Qwen or Feishu validation.\n\n")
        with redirect_stdout(log), redirect_stderr(log):
            try:
                with tempfile.TemporaryDirectory(prefix="am-conversation-pycompile-") as cache:
                    for relative in before["files"]:
                        if not relative.endswith(".py"):
                            continue
                        compiled_count += 1
                        target = Path(cache) / (hashlib.sha256(relative.encode()).hexdigest() + ".pyc")
                        try:
                            py_compile.compile(str(root / relative), cfile=str(target), doraise=True)
                        except py_compile.PyCompileError as exc:
                            compile_errors.append({"path": relative, "error": str(exc)})
                            print(str(exc))
                print(f"Syntax check: {compiled_count} Python files, {len(compile_errors)} errors.\n")
                suite = unittest.TestLoader().discover(str(root / "tests"), pattern="test*.py")
                unittest.TextTestRunner(stream=log, verbosity=2, resultclass=result_factory).run(suite)
            except BaseException:
                detail = traceback.format_exc()
                infrastructure_errors.append(detail)
                print(detail)
    result = result_holder.get("result")
    after = code_snapshot(root)
    stable = before["code_fingerprint"] == after["code_fingerprint"]
    if not stable:
        infrastructure_errors.append("Source/test/script bytes changed during verification. Rerun on a stable tree.")
    if result is not None and result.testsRun == 0:
        infrastructure_errors.append("No tests were executed; an empty suite is not a passing verification.")
    elapsed = time.perf_counter() - started
    completed_at = utc_now()
    passed = bool(result is not None and result.wasSuccessful() and result.testsRun > 0
                  and not infrastructure_errors and not compile_errors and stable)
    manifest = {"manifest_version": 1, "generated_at_utc": completed_at,
                "algorithm": "sha256", "scope": [directory + "/" for directory in CODE_DIRS],
                "excluded": sorted(EXCLUDED_DIRS) + ["*.pyc", "*.pyo", "symbolic links"], **after}
    manifest_path = output / "code-sha256.json"
    manifest_bytes = write_json(manifest_path, manifest)
    validation = {
        "status": "passed" if passed else "failed",
        "started_at_utc": started_at, "completed_at_utc": completed_at,
        "duration_seconds": round(elapsed, 6), "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "tests_run": result.testsRun if result is not None else 0,
        "failures": len(result.failures) if result is not None else 0,
        "errors": len(result.errors) if result is not None else 0,
        "skipped": len(result.skipped) if result is not None else 0,
        "expected_failures": len(result.expectedFailures) if result is not None else 0,
        "unexpected_successes": len(result.unexpectedSuccesses) if result is not None else 0,
        "syntax": {"python_files_checked": compiled_count, "errors": compile_errors},
        "infrastructure_errors": infrastructure_errors,
        "source_stable_during_run": stable,
        "code_manifest": {"path": manifest_path.name, "files": len(after["files"]),
                          "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                          "code_fingerprint": after["code_fingerprint"]},
        "evidence": {"runner_output": "unit-tests.txt", "junit": "unit-tests.xml"},
        "verification_boundary": {
            "scope": "local unit tests and synthetic fixtures; SQLite code runs locally",
            "external_integrations": "mock-only", "live_qwen": False,
            "live_feishu": False, "production_deployed": False,
            "human_business_acceptance": False,
            "meaning": "Passing this suite verifies local behaviors only, not model intelligence or real business delivery.",
        },
    }
    write_junit(output / "unit-tests.xml", result, elapsed, started_at,
                infrastructure_errors, compile_errors)
    write_json(output / "validation.json", validation)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\nUTC finish: {completed_at}\nSource stable: {stable}\n")
        for error in infrastructure_errors:
            log.write("Verification error: " + error + "\n")
        log.write("Overall local verification: " + validation["status"] + "\n")
    print(f"{validation['status'].upper()}: {validation['tests_run']} tests, "
          f"{validation['failures']} failures, {validation['errors']} errors, "
          f"{validation['skipped']} skipped. Evidence: {output}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
