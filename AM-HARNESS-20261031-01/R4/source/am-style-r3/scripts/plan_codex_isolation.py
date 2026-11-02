#!/usr/bin/env python3
"""Create a diagnosis plan from the installed CLI schema; never execute Codex."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from am_style.codex_isolation import propose_isolation

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--schema", required=True, help="Schema read from the actual installed CLI build")
    p.add_argument("--previous-observation", required=True)
    p.add_argument("--cli-version", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    target = Path(args.output)
    if target.exists():
        raise ValueError("use a new output path")
    result = propose_isolation(cli_version=args.cli_version, model=args.model,
        schema=json.loads(Path(args.schema).read_text()),
        previous_observation=json.loads(Path(args.previous_observation).read_text()))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"sufficient_for_generation": False,
                      "candidate_switches_may_be_probed": result["candidate_switches_may_be_probed"]}))

if __name__ == "__main__":
    main()
