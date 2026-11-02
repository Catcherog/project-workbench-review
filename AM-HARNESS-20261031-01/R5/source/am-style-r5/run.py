#!/usr/bin/env python3
"""Portable R5 CLI. Defaults to the pinned, isolated R4 source snapshot."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
paths = [ROOT / "src",
         Path(os.environ.get("AM_R5_HOST_SRC", str(ROOT / "baseline/am-conversation-r1/src"))),
         Path(os.environ.get("AM_R5_TRAINING_ROOT", str(ROOT / "baseline/am-style-r3")))]
for path in paths:
    if not path.is_absolute() or not path.is_dir():
        raise SystemExit("R5 requires an existing absolute source root: " + str(path))
sys.path[:0] = [str(p) for p in paths]
# Fresh generation workers must inherit the same explicit import roots.
os.environ["PYTHONPATH"] = os.pathsep.join(str(p) for p in paths)

from am_style_r5.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
