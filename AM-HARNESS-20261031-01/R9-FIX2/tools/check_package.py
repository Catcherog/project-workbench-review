#!/usr/bin/env python3
"""Read-only package and target-file preflight. This tool never applies code."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(root, relative):
    rel = PurePosixPath(relative)
    if (rel.is_absolute() or not rel.parts or "\\" in relative
            or any(p in ("", ".", "..") for p in rel.parts)):
        raise ValueError("unsafe relative path")
    path = root.joinpath(*rel.parts)
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink requires manual review")
    if not path.resolve().is_relative_to(root):
        raise ValueError("path escapes target root")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path,
        default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--root", type=Path, required=True,
        help="Actual source root containing the named project subdirectories")
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    root = args.root.resolve(strict=True)
    manifest = json.loads((package / "manifest.json").read_text())
    if manifest.get("schema") != "am-incremental-code-package/1":
        raise ValueError("unsupported manifest")
    patch = safe_path(package, "changes.patch")
    if not patch.is_file() or sha256(patch) != manifest["patch_sha256"]:
        raise ValueError("package patch hash mismatch")
    items = manifest.get("files")
    if not isinstance(items, list) or not items:
        raise ValueError("empty manifest")
    if len({item["path"] for item in items}) != len(items):
        raise ValueError("duplicate manifest path")
    results = []
    for item in items:
        result = {"path": item["path"]}
        try:
            payload = safe_path(package / "files", item["path"])
            if not payload.is_file() or sha256(payload) != item["after_sha256"]:
                raise ValueError("package payload hash mismatch")
            before = item.get("before_sha256")
            if before is not None:
                original = safe_path(package / "before", item["path"])
                if not original.is_file() or sha256(original) != before:
                    raise ValueError("package preimage hash mismatch")
            target = safe_path(root, item["path"])
            current = sha256(target) if target.is_file() else None
            result["current_sha256"] = current
            if current == item["after_sha256"]:
                result["status"] = "already_applied"
            elif current == before and (before is not None or not target.exists()):
                result["status"] = "ready"
            else:
                result["status"] = "conflict"
                result["reason"] = "preserve current file and merge against the packaged preimage"
        except (OSError, ValueError, KeyError) as exc:
            result.update(status="invalid", reason=str(exc))
        results.append(result)
    conflict = any(r["status"] in ("conflict", "invalid") for r in results)
    all_applied = all(r["status"] == "already_applied" for r in results)
    all_ready = all(r["status"] == "ready" for r in results)
    report = {"task": manifest["task"], "read_only": True,
        "target_root": str(root), "baseline_source_commit": manifest["baseline_source_commit"],
        "baseline_audit_commit": manifest["baseline_audit_commit"],
        "status": "blocked" if conflict else "already_applied" if all_applied else
                  "ready" if all_ready else "partially_applied",
        "files": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # A partial application needs an intentional remaining-file merge; do not
    # imply that applying the complete patch again is safe.
    return 1 if conflict else 2 if not (all_ready or all_applied) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "invalid", "read_only": True, "error": str(exc)}))
        raise SystemExit(1)
