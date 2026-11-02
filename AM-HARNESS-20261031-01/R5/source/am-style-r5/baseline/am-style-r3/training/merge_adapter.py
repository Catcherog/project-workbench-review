"""Merge a verified LoRA adapter into the exact non-quantized local base.

This prepares a separate artifact. It never changes or restarts AM/Ollama and
never downloads, creates an Ollama model, quantizes, uploads, or deploys.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from training.common import (TrainingInputError, file_hash, local_child, object_hash, read_json,
                             require_sha, validate_environment, validate_model_manifest, write_json)
from training.runtime import validate_loaded_text_model, validate_model_architecture


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--adapter", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args(argv)
    manifest = read_json(args.manifest)
    validate_model_manifest(manifest, verify_weights=args.execute)
    architecture = validate_model_architecture(manifest)
    adapter = Path(args.adapter)
    record = read_json(adapter / "training_record.json")
    if record.get("stage") not in {"sft", "dpo"} or record.get("training_completed") is not True:
        raise TrainingInputError("Adapter lacks a completed training record")
    if record.get("model_manifest_sha256") != object_hash(manifest):
        raise TrainingInputError("Adapter/base/tokenizer manifest mismatch")
    hashes = record.get("adapter_files_sha256", {})
    if not {"adapter_config.json", "adapter_model.safetensors"}.issubset(hashes):
        raise TrainingInputError("Incomplete adapter hashes")
    for name, sha in hashes.items():
        if file_hash(local_child(adapter, name)) != require_sha(sha, name):
            raise TrainingInputError(f"Adapter content changed: {name}")
    base_config = read_json(Path(manifest["local_model_path"]) / "config.json")
    if base_config.get("quantization_config"):
        raise TrainingInputError("Merge requires exact original non-quantized weights, not a dequantized GGUF substitute")
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise TrainingInputError("Use a new/empty merged output directory")
    if not args.execute:
        print("Text-only merge preflight passed; no model loaded. Full VLM preservation and Ollama import remain unverified.")
        return 0
    validate_environment(manifest)
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM
    from training.runtime import load_tokenizer
    base, loading_info = AutoModelForCausalLM.from_pretrained(
        manifest["local_model_path"], local_files_only=True, trust_remote_code=False,
        use_safetensors=True, torch_dtype=torch.bfloat16, device_map={"": "cpu"},
        output_loading_info=True,
    )
    validate_loaded_text_model(base, loading_info)
    model = PeftModel.from_pretrained(base, str(adapter), local_files_only=True)
    merged = model.merge_and_unload(safe_merge=True)
    merged.save_pretrained(output, safe_serialization=True, max_shard_size="4GB")
    load_tokenizer(manifest).save_pretrained(output)
    write_json(output / "merge_record.json", {
        "schema": "am-style-merge/1", "model_manifest_sha256": object_hash(manifest),
        "training_record_sha256": object_hash(record), "merged": True,
        "architecture": architecture, "output_model_type": merged.config.model_type,
        "text_only": True, "full_vlm_preserved": False,
        "deployment": "not_executed", "ollama_import_compatibility": "must_test_exact_version_and_architecture",
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainingInputError as exc:
        raise SystemExit(f"Merge preflight blocked: {exc}")
