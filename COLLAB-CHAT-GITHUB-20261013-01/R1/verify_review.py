#!/usr/bin/env python3
"""Verify the exported cloud bytes and reversible diff. Does not invoke the skill."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "versions-and-readback.json").read_text())
    expected = manifest["persisted"]
    actual_files = {str(p.relative_to(root / "skill")) for p in (root / "skill").rglob("*") if p.is_file()}
    assert actual_files == set(expected), "Export file set differs from official download"
    for name, sha in expected.items():
        assert digest(root / "skill" / name) == sha, name
    patch = root / "changes.patch"
    for line in patch.read_text().splitlines():
        if line.startswith(("--- ", "+++ ")):
            name = line.split(" ", 1)[1]
            assert name[2:] in {"skill/" + f for f in expected}, name
    with tempfile.TemporaryDirectory(prefix="coordinate-review-") as temporary:
        workspace = Path(temporary)
        shutil.copytree(root / "skill", workspace / "skill")
        subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=workspace, check=True)
        subprocess.run(["git", "apply", "--reverse", str(patch)], cwd=workspace, check=True)
        for name, sha in manifest["before"].items():
            assert digest(workspace / "skill" / name) == sha, "Baseline reconstruction: " + name
    print(json.dumps({"exported_cloud_files": len(expected), "hashes": "PASS", "reverse_patch": "PASS", "reconstructed_baseline_files": len(manifest["before"]), "runtime_behavior_test": False}))


if __name__ == "__main__":
    main()
