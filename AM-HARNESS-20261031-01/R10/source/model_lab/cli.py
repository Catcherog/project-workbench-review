"""Command line for private comparison experiments; no activation command."""
import argparse
import json
from pathlib import Path

from .core import LabError, freeze_manifest, read_json, read_jsonl, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze", help="Freeze exact cases, identities, routes and denominator")
    p.add_argument("spec"); p.add_argument("output")
    p = sub.add_parser("fixture", help="Create a frozen public fixture manifest; no model calls")
    p.add_argument("output")
    p = sub.add_parser("prepare-real", help="Import existing R5 regression plan and exact native artifact pins")
    p.add_argument("--source-root", required=True); p.add_argument("--r5-plan", required=True)
    p.add_argument("--output", required=True); p.add_argument("--queue-config"); p.add_argument("--pilot-plan")
    p.add_argument("--host-config"); p.add_argument("--python"); p.add_argument("--codex-binary")
    p.add_argument("--codex-proof"); p.add_argument("--codex-profile"); p.add_argument("--repeats", type=int, default=1)
    p = sub.add_parser("preflight", help="Read-only runtime identity/capability checks")
    p.add_argument("manifest"); p.add_argument("--output")
    p = sub.add_parser("run", help="Execute fixture or explicitly enabled real comparison")
    p.add_argument("manifest"); p.add_argument("output"); p.add_argument("--execute", action="store_true")
    p = sub.add_parser("report", help="Recompute report from exact immutable denominator")
    p.add_argument("manifest"); p.add_argument("results"); p.add_argument("output")
    p.add_argument("--reviews")
    p = sub.add_parser("blind-export", help="Export anonymous empty human review form")
    p.add_argument("manifest"); p.add_argument("results"); p.add_argument("output")
    p = sub.add_parser("blind-import", help="Validate independently filled human ratings")
    p.add_argument("manifest"); p.add_argument("packet"); p.add_argument("mapping")
    p.add_argument("reviews"); p.add_argument("output")
    p = sub.add_parser("select", help="Create a report-bound proposal; never changes production")
    p.add_argument("manifest"); p.add_argument("report"); p.add_argument("arm"); p.add_argument("output")
    p.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "fixture":
            from .fixtures import fixture_spec
            result = freeze_manifest(fixture_spec(), args.output)
            result = {"manifest_sha256": result["sha256"], "planned": result["expected_results"], "mode": "fixture"}
        elif args.command == "prepare-real":
            from .prepare import prepare_real_spec
            keys = ("source_root", "r5_plan", "queue_config", "pilot_plan", "host_config", "python", "codex_binary", "codex_proof", "codex_profile", "repeats")
            spec = prepare_real_spec(**{k: getattr(args, k) for k in keys})
            result = freeze_manifest(spec, args.output)
            result = {"manifest_sha256": result["sha256"], "planned": result["expected_results"], "mode": "real", "status": "prepared_not_executed"}
        elif args.command == "freeze":
            result = freeze_manifest(read_json(args.spec), args.output)
            result = {"manifest_sha256": result["sha256"], "planned": result["expected_results"]}
        elif args.command == "preflight":
            from .providers import preflight_manifest
            result = preflight_manifest(read_json(args.manifest))
            if args.output: write_json(args.output, result)
        elif args.command == "run":
            from .runner import run_manifest
            result = run_manifest(read_json(args.manifest), args.output, execute=args.execute)
        elif args.command == "report":
            from .report import build_report, render_report
            manifest, records = read_json(args.manifest), read_jsonl(args.results)
            result = build_report(manifest, records,
                                  read_json(args.reviews) if args.reviews else None)
            write_json(args.output, result)
            path = Path(args.output).with_suffix(".md")
            if path.exists(): raise LabError("readable_report_already_exists")
            path.write_text(render_report(manifest, records, result), encoding="utf-8")
            path.chmod(0o600)
        elif args.command == "blind-export":
            from .blind import export_blind
            result = export_blind(read_json(args.manifest), read_jsonl(args.results), args.output)
        elif args.command == "blind-import":
            from .blind import import_blind
            result = import_blind(read_json(args.manifest), read_json(args.packet),
                                  read_json(args.mapping), args.reviews)
            write_json(args.output, result)
        elif args.command == "select":
            from .report import propose_selection
            result = propose_selection(read_json(args.manifest), read_json(args.report), args.arm, args.reason)
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (LabError, OSError, KeyError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 2
