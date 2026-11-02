"""Metadata-only machine/model inspection; no requests to Ollama or model hubs."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from pathlib import Path

from training.common import (TrainingInputError, file_hash, package_inventory, read_json,
                             validate_model_manifest, write_json)
from training.runtime import validate_model_architecture


def hardware_inventory():
    result = package_inventory()
    result["cpu_count"] = os.cpu_count()
    if platform.system() == "Darwin":
        command = ["sysctl", "-n", "hw.memsize"]
        try:
            result["memory_bytes"] = int(subprocess.run(command, capture_output=True, text=True, check=True, timeout=5).stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            result["memory_bytes"] = None
    else:
        try:
            result["memory_bytes"] = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (OSError, ValueError):
            result["memory_bytes"] = None
    result["gpu"] = "not probed; no torch import or model loading"
    result["suggested_route"] = "mlx_sft_candidate" if platform.system() == "Darwin" and platform.machine() == "arm64" else "cuda_trl_candidate"
    return result


def inspect_local(path: Path, hash_weights: bool = False):
    if not path.is_dir():
        raise TrainingInputError("Local model directory does not exist")
    names = ("config.json", "tokenizer_config.json", "tokenizer.json", "tokenizer.model",
             "generation_config.json", "special_tokens_map.json", "added_tokens.json", "model.safetensors.index.json")
    metadata = {name: file_hash(path / name) for name in names if (path / name).is_file()}
    weights = {p.name: {"bytes": p.stat().st_size, "sha256": file_hash(p) if hash_weights else None}
               for p in sorted(path.glob("*.safetensors"))}
    config = read_json(path / "config.json") if (path / "config.json").is_file() else {}
    tokenizer_config = read_json(path / "tokenizer_config.json") if (path / "tokenizer_config.json").is_file() else {}
    template = (path / "chat_template.jinja").read_text(encoding="utf-8") if (path / "chat_template.jinja").is_file() else tokenizer_config.get("chat_template")
    import hashlib
    return {"local_model_path": str(path.resolve()), "model_type": config.get("model_type"),
            "metadata_sha256": metadata, "weight_files": weights,
            "chat_template_sha256": hashlib.sha256(template.encode()).hexdigest() if isinstance(template, str) else None,
            "origin_verified": False, "note": "Hashes do not identify the original Ollama/HF relationship; record that evidence separately."}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest")
    p.add_argument("--inspect-local-model")
    p.add_argument("--hash-weights", action="store_true", help="Explicit full local weight read; no downloads")
    p.add_argument("--output")
    args = p.parse_args(argv)
    result = {"inventory": hardware_inventory(), "model_loading": False, "network_requests": 0}
    if args.inspect_local_model:
        result["model"] = inspect_local(Path(args.inspect_local_model), args.hash_weights)
    if args.manifest:
        manifest = read_json(args.manifest)
        result["manifest_check"] = validate_model_manifest(manifest, verify_weights=args.hash_weights)
        result["architecture_check"] = validate_model_architecture(manifest)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainingInputError as exc:
        raise SystemExit(f"Preflight blocked: {exc}")
