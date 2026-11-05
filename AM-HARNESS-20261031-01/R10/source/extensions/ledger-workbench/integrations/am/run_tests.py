"""Run only offline web adapter checks against an explicit AM source snapshot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--am-source-root", required=True, type=Path)
    parser.add_argument("--dependencies", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.am_source_root.resolve()
    here = Path(__file__).resolve().parent
    paths = [root / "FS-AGENT-GROK-POC-20261017-01_R1_Studio/src",
             root / "FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests",
             root / "am-conversation-r1/src", root / "local-qwen3.8/feishu-bridge",
             root / "am-style-r5/src", root / "am-integrated-r6"]
    if not all(p.is_dir() for p in paths):
        raise SystemExit("AM_SOURCE_SNAPSHOT_INCOMPLETE")
    if args.dependencies:
        paths.insert(0, args.dependencies.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str, paths)), PYTHONDONTWRITEBYTECODE="1",
               LEDGER_AM_SOURCE_ROOT=str(root))
    env.pop("AM_WORKBENCH_KEY_FILE", None)
    env.pop("AM_WORKBENCH_WORKSPACE_ID", None)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        str(here / "tests/test_native_web.py"), "--junitxml=" + str(args.output / "native-web.xml")],
        env=env, text=True, capture_output=True)
    (args.output / "native-web.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    source_files = [root / "local-qwen3.8/feishu-bridge" / name for name in
                    ("am_followup_host.py", "am_workbench_adapter.py")]
    report = {"exitCode": result.returncode, "sourceRoot": str(root),
        "loadedHost": str(source_files[0]),
        "sourceSha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
        "platform": "synthetic existing AM test ports", "realExternalSends": 0,
        "realMachineAccess": False, "newConsumer": False}
    xml = args.output / "native-web.xml"
    if xml.exists():
        suites = ET.parse(xml).getroot().iter("testsuite")
        for suite in suites:
            for key in ("tests", "failures", "errors", "skipped"):
                report[key] = report.get(key, 0) + int(suite.get(key, "0"))
    (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
