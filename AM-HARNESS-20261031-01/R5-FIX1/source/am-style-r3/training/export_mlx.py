"""Prepare a reviewed SFT dataset for official MLX-LM; does not run training.

Current MLX model support and exact package versions must be checked on Studio.
This is not a DPO backend and does not convert HF/Qwen weights automatically.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.common import TrainingInputError, load_training_data, read_json, validate_model_manifest, write_json


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    manifest, config = read_json(args.manifest), read_json(args.config)
    validate_model_manifest(manifest)
    quality_tier = config.get("quality_tier", "gold")
    train, dev = load_training_data(config, "sft", quality_tier=quality_tier)
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise TrainingInputError("Use a fresh MLX export directory")
    output.mkdir(parents=True, exist_ok=True)
    for filename, rows in (("train.jsonl", train), ("valid.jsonl", dev)):
        text = "".join(json.dumps({"messages": row["prompt"] + row["completion"]}, ensure_ascii=False) + "\n" for row in rows)
        (output / filename).write_text(text, encoding="utf-8")
    command = ["mlx_lm.lora", "--model", manifest["local_model_path"], "--train", "--data", str(output.resolve()),
               "--mask-prompt", "--batch-size", "1", "--grad-accumulation-steps", "16", "--grad-checkpoint",
               "--iters", "100", "--adapter-path", str((output / "adapters").resolve())]
    plan = {"execution": "not_run", "candidate_command": command,
            "quality_tier": quality_tier, "experimental_only": config.get("experimental_only", False),
            "architecture_verified": False, "model_loading": False,
            "requires": ["MLX load/tokenizer compatibility", "exact installed dependency lock", "token length and prompt-mask smoke check", "measured peak unified memory", "fresh adapter output and original service isolation"],
            "dpo": "not implemented by this MLX exporter; use validated TRL CUDA path"}
    write_json(output / "mlx_run_plan.json", plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainingInputError as exc:
        raise SystemExit(f"MLX export blocked: {exc}")
