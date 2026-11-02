#!/usr/bin/env python3
"""Run offline: python scripts/build_data.py [--pairs PRIVATE_PAIRS.json]."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from am_style.data import (analyze_ratings, canonical, digest, export_training,
                           read_json, strict_loads, write_json, write_jsonl)
from am_style.synthetic import generate_seeds, generate_projected_seeds, semantic_challenges
from am_style.silver import export_silver_sft


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ratings", type=Path, default=ROOT / "data/input/ratings.json")
    parser.add_argument("--index", type=Path, default=ROOT / "data/input/pair-index.json")
    parser.add_argument("--pairs", type=Path, help="exact private R2-FIX1 blind-private/pairs.json")
    parser.add_argument("--key", type=Path, help="optional private blind-key.json")
    parser.add_argument("--key-metadata", type=Path)
    parser.add_argument("--review-records", type=Path, help="reviewed JSONL using am-style-review/1")
    parser.add_argument("--align-host-prompt", action="store_true", default=True, help="use the actual host free-expression prompt (default)")
    parser.add_argument("--raw-draft-prompt", dest="align_host_prompt", action="store_false", help="retain preliminary unaligned prompts for debugging only")
    parser.add_argument("--output", type=Path, default=ROOT / "data/generated")
    args = parser.parse_args()
    report = analyze_ratings(read_json(args.ratings), read_json(args.index),
        read_json(args.pairs) if args.pairs else None,
        read_json(args.key) if args.key else None,
        read_json(args.key_metadata) if args.key_metadata else None)
    report["rating_file_sha256"] = digest(args.ratings.read_bytes())
    write_json(args.output / "annotation-analysis.json", report)
    seeds = generate_projected_seeds() if args.align_host_prompt else generate_seeds()
    write_jsonl(args.output / "synthetic-review-seeds.jsonl", seeds)
    write_jsonl(args.output / "semantic-challenges.jsonl", semantic_challenges())
    records = [strict_loads(line) for line in args.review_records.read_text(encoding="utf-8").splitlines() if line.strip()] if args.review_records else seeds
    result = export_training(records)
    manifest = {"schema": "am-style-training-manifest/1", "files": {},
        "total_records": len(records), "split_counts": dict(Counter(r["split"] for r in records)),
        "input_records_sha256": digest(canonical(records)), "training_run_performed": False,
        "private_blind_join_verified": report["private_pairs_verified"],
        "calibration_dataset_sha256": report["dataset_sha256"],
        "runtime_prompt_alignment": "aligned" if records and all(r.get("runtime_prompt_alignment") == "aligned" for r in records) else "mixed_or_unaligned",
        "test_status": "reserved_visible_drafts_not_independently_sealed",
        "note": "Empty exports are intentional until bound human reviews are supplied."}
    for name, rows in result["outputs"].items():
        filename = name + ".jsonl"
        manifest["files"][filename] = {"sha256": write_jsonl(args.output / filename, rows), "rows": len(rows)}
    write_json(args.output / "training-manifest.json", manifest)
    write_json(args.output / "export-skipped.json", result["skipped"])
    # Current seeds have no real judges or gold anchors. This records zero weak
    # labels explicitly; it never invokes models or fabricates a passing review.
    silver = export_silver_sft(seeds, experimental_only=True)
    silver_files = {}
    for name, rows in silver["outputs"].items():
        filename = "silver." + name + ".jsonl"
        silver_files[filename] = {"sha256": write_jsonl(args.output / filename, rows), "rows": len(rows)}
    write_json(args.output / "silver-manifest.json", {
        "quality_tier": "experimental_silver", "experimental_only": True,
        "human_approved": False, "files": silver_files, "dpo_enabled": False,
        "gold_anchor_status": "not_yet_provided", "real_judge_calls": 0,
        "skipped": silver["skipped"], "training_run_performed": False})
    print(canonical({"annotation_entries": report["entries"], "rated": report["rated"],
        "relative_preferences": len(report["queues"]["relative_preference"]),
        "both_bad": len(report["queues"]["repair"]), "unrated": len(report["queues"]["unrated"]),
        "synthetic_drafts": len(seeds), "training_rows": {k: len(v) for k, v in result["outputs"].items()},
        "silver_sft_rows": {k: len(v) for k, v in silver["outputs"].items()},
        "private_blind_join_verified": report["private_pairs_verified"]}))


if __name__ == "__main__":
    main()
