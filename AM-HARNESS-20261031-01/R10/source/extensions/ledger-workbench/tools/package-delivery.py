"""Package the completed, verified candidate without local credentials or QA images."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def include(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if not path.is_file() or path.is_symlink():
        return False
    if any(part in {"node_modules", "dist", "screenshots", "__pycache__", ".pytest_cache", ".git", "processing-gap"} for part in rel.parts):
        return False
    if path.name in {"FILE_MANIFEST.json", "native-web-results.xml"}:
        return False
    if path.suffix in {".pyc", ".key", ".sqlite", ".png", ".jpg", ".webp"}:
        return False
    if any(token in path.name for token in (".request.json", ".result.json", ".sqlite-")):
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = args.output_dir.resolve()
    if output == root or root in output.parents:
        raise SystemExit("OUTPUT_MUST_BE_OUTSIDE_SOURCE_TREE")
    checks = read_json(root / "verification/checks.json")
    native = read_json(root / "integrations/am/verification/summary.json")
    browser = read_json(root / "verification/browser-report.json")
    if any(item["exitCode"] for item in checks["checks"]) or native["exitCode"] or not browser.get("passed"):
        raise SystemExit("UNRESOLVED_VERIFICATION_FAILURE")
    if any(not item.get("passed") for item in browser["checks"]):
        raise SystemExit("UNRESOLVED_BROWSER_CHECK")
    now = datetime.now(timezone.utc).isoformat()
    verification = {
        "taskId": "AM-HARNESS-20261031-01", "round": "R10", "requirementVersion": "ledger-v1.0-confirmed",
        "packagedAt": now, "nodeVersion": subprocess.check_output(["node", "--version"], text=True).strip(),
        "candidateDevelopmentVerified": True, "productionInstalled": False, "realMachineAccess": False,
        "realExternalSends": 0, "humanThirtySecondAcceptance": "pending_original_machine",
        "sourceBasis": {
            "workbenchReviewCommit": "78407b22c18dbb17c0bd79f1c8486d896bf5ebe2",
            "amReviewCommit": "777921b15c7a2ad19d2bec8591ffad29d4daa9d2",
            "amReportedSourceCommit": "4e46d18c45951a02f27ae47acc107fbf34f8cbec",
            "currentMachineHeadVerified": False,
        },
        "automatedChecks": checks["checks"],
        "finalTypecheck": checks.get("finalTypecheckAfterDependencyLock"),
        "nativeAM": {key: native[key] for key in ("exitCode", "tests", "failures", "errors", "skipped", "platform", "newConsumer")},
        "nonBrowserUniqueTestCount": sum(item.get("tests", 0) for item in checks["checks"]) + native["tests"],
        "browser": {
            "passed": browser["passed"], "version": browser["browserVersion"],
            "checks": len(browser["checks"]), "metrics": browser.get("metrics", {}),
            "realFeishuSending": False, "report": "browser-report.json",
            "runtime": browser.get("browserRuntime"),
        },
        "remainingAcceptance": [
            "Merge into the actual current WB and AM source, preserving newer changes.",
            "Verify the current host theme and actual source/identity bindings on the original machine.",
            "Verify real AM/Qwen/Feishu behavior separately from synthetic platform tests.",
            "Use an explicitly approved concrete preview for any real external follow-up.",
            "Measure lookup, loading, reading and correct human understanding within thirty seconds.",
        ],
        "qaScreenshots": "Internal only; intentionally excluded from delivery.",
    }
    write_json(root / "verification/verification.json", verification)
    files = sorted((path for path in root.rglob("*") if include(path, root)), key=lambda path: path.relative_to(root).as_posix())
    manifest = {"taskId": verification["taskId"], "round": "R10", "generatedAt": now, "files": [
        {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files
    ]}
    manifest_path = root / "FILE_MANIFEST.json"
    write_json(manifest_path, manifest)
    files.append(manifest_path)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "R10_单页台账开发包.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            bundle.write(path, "ledger-workbench/" + path.relative_to(root).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise SystemExit("DELIVERY_ARCHIVE_INTEGRITY_FAILURE")
        for item in manifest["files"]:
            data = bundle.read("ledger-workbench/" + item["path"])
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise SystemExit("DELIVERY_FILE_HASH_MISMATCH")
    architecture = output / "单页台账架构与接入设计.md"
    shutil.copyfile(root / "docs/单页台账架构与接入设计.md", architecture)
    result = {"files": [str(archive), str(architecture)], "archiveFiles": len(files),
              "archiveBytes": archive.stat().st_size,
              "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
              "nonBrowserUniqueTests": verification["nonBrowserUniqueTestCount"],
              "browserChecks": verification["browser"]["checks"]}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
