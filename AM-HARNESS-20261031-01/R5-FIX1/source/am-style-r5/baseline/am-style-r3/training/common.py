"""Fail-closed validation shared by optional SFT and DPO entry points.

Only standard-library imports here. No downloads, model calls, or auto installs.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
import sys
from pathlib import Path
from typing import Any

TRL_VERSION = "1.17.1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")


class TrainingInputError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def object_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: str | Path) -> dict:
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise TrainingInputError(f"Expected JSON object: {path}")
    return result


def write_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def required_text(obj: dict, key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip() or "REPLACE" in value or "<" in value:
        raise TrainingInputError(f"Missing concrete {key}")
    return value


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise TrainingInputError(f"Invalid {label}: need exact SHA-256")
    return value


def local_child(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise TrainingInputError(f"Missing/out-of-root local file: {relative}")
    return path


def validate_model_manifest(manifest: dict, *, verify_weights: bool = False) -> dict:
    """Validate metadata by default. Full weight hashing only on explicit training.

    Hashes identify a snapshot, not its origin. `runtime_mapping_evidence` is the
    required record of how the operator traced the original Ollama tag to it.
    """
    if manifest.get("schema") != "am-style-model/1":
        raise TrainingInputError("Model schema must be am-style-model/1")
    for key in ("runtime_model", "base_model_id", "tokenizer_model_id", "runtime_mapping_evidence"):
        required_text(manifest, key)
    for key in ("base_revision", "tokenizer_revision"):
        if not REVISION.fullmatch(str(manifest.get(key, ""))):
            raise TrainingInputError(f"{key} must be a full immutable 40-character commit")
    root = Path(required_text(manifest, "local_model_path"))
    if not root.is_absolute() or not root.is_dir():
        raise TrainingInputError("local_model_path must be an existing absolute local directory")
    if manifest.get("trust_remote_code") is not False:
        raise TrainingInputError("This entry point supports trust_remote_code=false only")
    hashes = manifest.get("metadata_sha256")
    if not isinstance(hashes, dict) or not {"config.json", "tokenizer_config.json"}.issubset(hashes):
        raise TrainingInputError("Pin config.json and tokenizer_config.json hashes")
    if not any(name in hashes for name in ("tokenizer.json", "tokenizer.model")):
        raise TrainingInputError("Pin tokenizer.json or tokenizer.model")
    for name in ("generation_config.json", "special_tokens_map.json", "added_tokens.json", "model.safetensors.index.json"):
        if (root / name).is_file() and name not in hashes:
            raise TrainingInputError(f"Also pin the existing model metadata file: {name}")
    for relative, expected in hashes.items():
        require_sha(expected, relative)
        if file_hash(local_child(root, relative)) != expected:
            raise TrainingInputError(f"Metadata mismatch: {relative}")
    config = read_json(root / "config.json")
    tokenizer_config = read_json(root / "tokenizer_config.json")
    template_file = root / "chat_template.jinja"
    template = template_file.read_text(encoding="utf-8") if template_file.is_file() else tokenizer_config.get("chat_template")
    if not isinstance(template, str) or not template.strip():
        raise TrainingInputError("An explicit single chat template is required; no default-template fallback")
    expected_template = require_sha(manifest.get("chat_template_sha256"), "chat_template_sha256")
    if hashlib.sha256(template.encode()).hexdigest() != expected_template:
        raise TrainingInputError("Chat template hash mismatch")
    if manifest.get("model_type") != config.get("model_type") or not manifest.get("model_type"):
        raise TrainingInputError("model_type must match local config.json")
    weights = manifest.get("weight_files_sha256")
    if not isinstance(weights, dict) or not weights:
        raise TrainingInputError("Exact local Safetensors weight snapshot is required")
    actual_weights = {p.name for p in root.glob("*.safetensors")}
    if actual_weights != set(weights):
        raise TrainingInputError("Declared weight file set differs from local Safetensors files")
    for relative, expected in weights.items():
        require_sha(expected, relative)
        path = local_child(root, relative)
        if verify_weights and file_hash(path) != expected:
            raise TrainingInputError(f"Weight mismatch: {relative}")
    return {"model_type": config["model_type"], "metadata_verified": True,
            "weights_verified": verify_weights, "manifest_sha256": object_hash(manifest)}


def validate_messages(value: Any, label: str, *, completion: bool = False) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise TrainingInputError(f"{label} must be non-empty conversational messages")
    for message in value:
        if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant"}:
            raise TrainingInputError(f"Unsupported role in {label}")
        if not isinstance(message.get("content"), str) or not message["content"].strip():
            raise TrainingInputError(f"Empty content in {label}")
    if completion and (len(value) != 1 or value[0]["role"] != "assistant"):
        raise TrainingInputError(f"{label} must contain exactly one assistant completion")
    if completion:
        try:
            output = json.loads(value[0]["content"])
        except json.JSONDecodeError as exc:
            raise TrainingInputError(f"{label} must match the runtime JSON output contract") from exc
        if not isinstance(output, dict) or set(output) != {"text"} or not isinstance(output["text"], str) or not output["text"].strip():
            raise TrainingInputError(f"{label} must be exactly a JSON object with non-empty text")
    if not completion and value[-1]["role"] != "user":
        raise TrainingInputError("Expression prompt must end with the canonical user input")
    return value


def validate_rows(rows: list[dict], *, split: str, mode: str, quality_tier: str = "gold",
                  experimental_only: bool = False, anchor_sha: str | None = None,
                  policy_sha: str | None = None) -> None:
    if split not in {"train", "dev"} or mode not in {"sft", "dpo"}:
        raise TrainingInputError("Only explicit train/dev sft/dpo records are trainable")
    if not rows:
        raise TrainingInputError(f"No approved {mode} {split} rows")
    if quality_tier not in {"gold", "experimental_silver"}:
        raise TrainingInputError("Unknown training quality_tier")
    if quality_tier == "experimental_silver":
        if mode != "sft" or experimental_only is not True:
            raise TrainingInputError("Silver is allowed only in an explicit experimental SFT run; DPO remains gold")
        from am_style.silver import validate_silver_sft_row
        if len({row.get("id") for row in rows}) != len(rows):
            raise TrainingInputError("Duplicate silver record ID")
        for row in rows:
            try:
                validate_silver_sft_row(row, split=split, anchor_sha=anchor_sha, policy_sha=policy_sha)
            except (ValueError, KeyError, TypeError) as exc:
                raise TrainingInputError(str(exc)) from exc
        return
    seen_ids: set[str] = set()
    for row in rows:
        rid = required_text(row, "id")
        if rid in seen_ids:
            raise TrainingInputError(f"Duplicate record id: {rid}")
        seen_ids.add(rid)
        prompt = validate_messages(row.get("prompt"), f"{rid}.prompt")
        p = row.get("provenance", {})
        if p.get("schema") != "am-style-data/1" or p.get("split") != split:
            raise TrainingInputError(f"Wrong provenance/split: {rid}")
        if p.get("source_kind") not in {"human_reviewed_synthetic", "human_reviewed_observation"}:
            raise TrainingInputError(f"Unreviewed/calibration source is not trainable: {rid}")
        for key in ("group_id", "style_policy_version", "reviewer", "reviewed_at"):
            required_text(p, key)
        if p.get("runtime_alignment") != "aligned":
            raise TrainingInputError(f"Runtime/production prompt alignment is missing: {rid}")
        required_text(p, "host_contract_version")
        for key in ("facts_pass", "style_pass", "acceptable", "human_approved"):
            if p.get(key) is not True:
                raise TrainingInputError(f"{rid}: explicit human {key}=true is required")
        require_sha(p.get("source_sha256"), "source_sha256")
        if p.get("prompt_sha256") != object_hash(prompt):
            raise TrainingInputError(f"Prompt content changed after review: {rid}")
        fields = ("completion",) if mode == "sft" else ("chosen", "rejected")
        for field in fields:
            response = validate_messages(row.get(field), f"{rid}.{field}", completion=True)
            hash_key = "candidate_sha256" if field == "completion" else f"{field}_sha256"
            if p.get(hash_key) != object_hash(response):
                raise TrainingInputError(f"Response content changed after review: {rid}.{field}")
        if mode == "dpo":
            if row["chosen"] == row["rejected"]:
                raise TrainingInputError(f"DPO pair has identical alternatives: {rid}")
            if p.get("preference_source") != "human" or p.get("rejected_facts_pass") is not True:
                raise TrainingInputError(f"Style DPO needs human preference and fact-correct rejected text: {rid}")


def load_training_data(config: dict, mode: str, *, quality_tier: str | None = None) -> tuple[list[dict], list[dict]]:
    tier = config.get("quality_tier", "gold") if quality_tier is None else quality_tier
    if tier != config.get("quality_tier", "gold"):
        raise TrainingInputError("Entry point and config quality tiers differ")
    def load(split: str) -> list[dict]:
        path = Path(required_text(config, f"{split}_file"))
        if file_hash(path) != require_sha(config.get(f"{split}_sha256"), f"{split}_sha256"):
            raise TrainingInputError(f"Dataset file hash mismatch: {split}")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        validate_rows(rows, split=split, mode=mode, quality_tier=tier,
                      experimental_only=config.get("experimental_only", False),
                      anchor_sha=config.get("gold_anchor_sha256"), policy_sha=config.get("style_policy_sha256"))
        return rows
    train, dev = load("train"), load("dev")
    train_groups = {r["provenance"]["group_id"] for r in train}
    dev_groups = {r["provenance"]["group_id"] for r in dev}
    if train_groups & dev_groups:
        raise TrainingInputError("Related scenario groups leaked across train/dev")
    if {r["id"] for r in train} & {r["id"] for r in dev}:
        raise TrainingInputError("Record ids leaked across train/dev")
    train_prompts = {r["provenance"]["prompt_sha256"] for r in train}
    if train_prompts & {r["provenance"]["prompt_sha256"] for r in dev}:
        raise TrainingInputError("Identical prompt leaked across train/dev")
    policy_versions = {r["provenance"]["style_policy_version"] for r in train + dev}
    if policy_versions != {required_text(config, "style_policy_version")}:
        raise TrainingInputError("Mixed or stale style policy versions")
    host_versions = {r["provenance"]["host_contract_version"] for r in train + dev}
    if host_versions != {required_text(config, "host_contract_version")}:
        raise TrainingInputError("Mixed or stale host contract versions")
    return train, dev


def package_inventory() -> dict:
    packages = {}
    for name in ("torch", "trl", "transformers", "peft", "datasets", "accelerate", "bitsandbytes", "mlx", "mlx-lm"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": sys.version.split()[0], "system": platform.system(),
            "machine": platform.machine(), "packages": packages}


def validate_environment(manifest: dict) -> dict:
    observed = package_inventory()
    expected = manifest.get("package_versions")
    mandatory = {"torch", "trl", "transformers", "peft", "datasets", "accelerate"}
    if not isinstance(expected, dict) or not mandatory.issubset(expected):
        raise TrainingInputError("Record exact installed training dependency versions after compatibility check")
    if expected["trl"] != TRL_VERSION:
        raise TrainingInputError(f"These entry points target TRL {TRL_VERSION}; re-audit API before upgrading")
    for name, value in expected.items():
        if not isinstance(value, str) or observed["packages"].get(name) != value:
            raise TrainingInputError(f"Installed dependency differs from manifest: {name}")
    # Current TRL can silently fall back to base reference with older PEFT for
    # target_parameters. Require the release range that supports reference copies.
    peft_version = tuple(int(x) for x in re.findall(r"\d+", expected["peft"])[:2])
    if peft_version < (0, 20):
        raise TrainingInputError("PEFT >= 0.20 is required; do not fall back to a base-model reference")
    return observed


def validate_sft_checkpoint(manifest: dict, sft_record: dict, adapter_path: Path) -> None:
    if sft_record.get("stage") != "sft" or sft_record.get("training_completed") is not True:
        raise TrainingInputError("DPO requires an actually completed SFT checkpoint")
    if sft_record.get("model_manifest_sha256") != object_hash(manifest):
        raise TrainingInputError("SFT checkpoint belongs to a different base/tokenizer/template snapshot")
    hashes = sft_record.get("adapter_files_sha256", {})
    if not hashes or "adapter_config.json" not in hashes or "adapter_model.safetensors" not in hashes:
        raise TrainingInputError("SFT adapter evidence is incomplete")
    for name, expected in hashes.items():
        if file_hash(local_child(adapter_path, name)) != require_sha(expected, name):
            raise TrainingInputError(f"SFT checkpoint changed: {name}")
    peft_config = read_json(adapter_path / "adapter_config.json")
    if peft_config.get("peft_type") != "LORA" or peft_config.get("modules_to_save"):
        raise TrainingInputError("This DPO route supports LoRA-only SFT adapters without modules_to_save")


def strip_provenance(rows: list[dict], mode: str) -> list[dict]:
    fields = ("prompt", "completion") if mode == "sft" else ("prompt", "chosen", "rejected")
    return [{field: row[field] for field in fields} for row in rows]


def validate_tokenization(tokenizer: Any, rows: list[dict], max_length: int, mode: str) -> dict:
    """Reject overlength or template discontinuity instead of silently truncating facts."""
    lengths = []
    for row in rows:
        prompt_ids = tokenizer.apply_chat_template(row["prompt"], tokenize=True, add_generation_prompt=True)
        for field in (("completion",) if mode == "sft" else ("chosen", "rejected")):
            full_ids = tokenizer.apply_chat_template(row["prompt"] + row[field], tokenize=True, add_generation_prompt=False)
            if full_ids[:len(prompt_ids)] != prompt_ids:
                raise TrainingInputError(f"Chat template is not prefix-compatible for {row['id']}; inspect loss mask")
            if len(full_ids) <= len(prompt_ids) or len(full_ids) > max_length:
                raise TrainingInputError(f"Empty or overlength completion: {row['id']}; never truncate facts silently")
            lengths.append(len(full_ids))
    return {"rows": len(rows), "max_tokens": max(lengths), "silent_truncation": False}
