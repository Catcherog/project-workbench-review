#!/usr/bin/env python3
"""Build a pending review pack or import explicitly supplied human feedback."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from am_style.data import digest, read_json, strict_loads, write_json, write_jsonl
from am_style.review import build_review_batch, feedback_template, import_feedback, markdown_review


def fresh_output_directory(path):
    """Create an unused directory only after all inputs have been validated."""
    resolved = path.resolve()
    # Catch ordinary paths and aliases, including an existing dangling symlink.
    if path.exists() or path.is_symlink() or resolved.exists():
        raise FileExistsError("review output already exists; choose a new directory: " + str(resolved))
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--input-dir", type=Path, default=Path("data/r3"))
    build.add_argument("--out-dir", type=Path, default=Path("data/r4-review"))
    ingest = sub.add_parser("import")
    ingest.add_argument("--batch", type=Path, required=True)
    ingest.add_argument("--feedback", type=Path, required=True)
    ingest.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        paths = {name: args.input_dir / name for name in
                 ("comparison.json", "frozen-comparison.json", "sft.train.jsonl", "sft.dev.jsonl")}
        source_files = {name: {"sha256": digest(path.read_bytes()), "relative_path": "data/r3/" + name}
                        for name, path in paths.items()}
        gold = [strict_loads(line) for name in ("sft.train.jsonl", "sft.dev.jsonl")
                for line in paths[name].read_text(encoding="utf-8").splitlines() if line.strip()]
        batch = build_review_batch(read_json(paths["frozen-comparison.json"]),
            read_json(paths["comparison.json"]), gold, source_files=source_files)
        feedback = feedback_template(batch)
        review = markdown_review(batch)
        destination = fresh_output_directory(args.out_dir)
        write_json(destination / "batch.json", batch)
        write_json(destination / "feedback.pending.json", feedback)
        (destination / "review.md").write_text(review, encoding="utf-8")
        print(json.dumps({"batch_sha256": batch["batch_sha256"], **batch["counts"]}, ensure_ascii=False))
    else:
        result = import_feedback(read_json(args.batch), read_json(args.feedback))
        destination = fresh_output_directory(args.out_dir)
        write_json(destination / "import.json", result)
        counts = {}
        for name, rows in result["exports"]["outputs"].items():
            write_jsonl(destination / (name + ".jsonl"), rows)
            counts[name] = len(rows)
        print(json.dumps({"new_exports": counts, "pending": len(result["pending_ids"]),
                          "repair": len(result["repair_queue"]), "existing_r3_gold_untouched": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
