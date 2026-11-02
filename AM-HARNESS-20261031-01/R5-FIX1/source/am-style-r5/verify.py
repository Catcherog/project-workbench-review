#!/usr/bin/env python3
"""Verify the delivery's pinned sources and offline contracts. Never run models."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_child(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Missing or escaped delivery file: " + name)
    return path


def check_sources():
    provenance = json.loads((ROOT / "baseline/PROVENANCE.json").read_text())
    errors, checked = [], []
    for entry in provenance["files"]:
        path = safe_child(ROOT / "baseline", entry["local"])
        actual = digest(path)
        if actual != entry["sha256"]:
            errors.append("Baseline differs: " + entry["local"])
        checked.append({"path": "baseline/" + entry["local"], "sha256": actual})
    package_count = None
    manifest_path = ROOT / "PACKAGE_MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        package_count = len(manifest["files"])
        for name, expected in manifest["files"].items():
            path = safe_child(ROOT, name)
            if digest(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
                errors.append("Delivery differs: " + name)
    return checked, package_count, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New output directory; never overwrites")
    parser.add_argument("--integrity-only", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.output).resolve()
    if out.exists():
        parser.error("output already exists")
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    baseline, package_count, errors = check_sources()
    source_paths = [ROOT / "run.py", ROOT / "verify.py", *sorted((ROOT / "src").rglob("*.py")),
                    *sorted((ROOT / "tests").rglob("*.py"))]
    sources_before = {str(p.relative_to(ROOT)): digest(p) for p in source_paths}
    # This test harness checks the delivery baseline, not an undiscovered live host.
    roots = [ROOT / "src", ROOT / "baseline/am-conversation-r1/src", ROOT / "baseline/am-style-r3"]
    sys.path[:0] = [str(p) for p in roots]
    os.environ["AM_R5_HOST_SRC"] = str(roots[1])
    os.environ["AM_R5_TRAINING_ROOT"] = str(roots[2])
    os.environ["PYTHONPATH"] = os.pathsep.join(str(p) for p in roots)
    log = io.StringIO()
    result = None
    if not errors and not args.integrity_only:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
        result = unittest.TextTestRunner(stream=log, verbosity=2, buffer=True).run(suite)
    sources_after = {str(p.relative_to(ROOT)): digest(p) for p in source_paths}
    if sources_before != sources_after:
        errors.append("Source changed during verification")
    mlx_imported = any(name == "mlx" or name.startswith("mlx.") for name in sys.modules)
    if mlx_imported:
        errors.append("Unexpected MLX import in offline verification process")
    successful = not errors and (args.integrity_only or (result is not None and result.wasSuccessful()))
    summary = {
        "schema": "am-r5-offline-verification/1", "passed": successful,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "source_mode": "pinned_delivery_baseline", "integrity_only": args.integrity_only,
        "baseline_files_checked": len(baseline), "package_files_checked": package_count,
        "tests_run": result.testsRun if result else 0,
        "failures": len(result.failures) if result else 0,
        "errors": len(result.errors) if result else 0,
        "skipped": len(result.skipped) if result else 0,
        "integrity_errors": errors, "source_sha256": sources_before,
        "mlx_imported": mlx_imported,
        "actual_model_calls": 0, "actual_training_runs": 0,
        "new_real_human_labels": 0, "production_changed": False,
        "scope": "Offline contracts and explicit temporary fixtures; no live host, model quality or business acceptance proof",
    }
    (out / "tests.log").write_text(log.getvalue(), encoding="utf-8")
    (out / "baseline-check.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "source_sha256"}, ensure_ascii=False, indent=2))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
