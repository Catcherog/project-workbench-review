"""Stdlib contracts for the independent, local-only R4 MLX experiment.

No model library is imported here. A passing metadata check is not a successful
numerical check, a model load, a training run, or an effectiveness result.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import math
import platform
from pathlib import Path

from training.common import (TrainingInputError, file_hash, load_training_data,
                             local_child, object_hash, read_json, require_sha,
                             required_text)

BASE_REPO = "Qwen/Qwen3.8-27B"
BASE_REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
MLX_LM_COMMIT = "93e6d4a6447b3080861985947f0820e76fcb957d"
MLX_LM_BLOBS = {
    "models/qwen3_5.py": "83b51f826affdad30fc39599e4492d82222708e9",
    "models/gated_delta.py": "36391f09e472e1b03955cfacee4613aa81e05bea",
    "tuner/utils.py": "7bf947f8ebc0b89dff5b19fb614e86ce5dab9eb7",
    "tuner/trainer.py": "590bdb5abb1002da4bccbf3b0ee8e70e2549a58c",
    "generate.py": "8a348b25519e3e960d0032607f56a198fac0311b",
    "utils.py": "aff825e8092b0452ea6f97fc8feca4d414ab1d2b",
}
PACKAGE_VERSIONS = {"mlx": "0.32.4", "mlx-lm": "0.32.2", "transformers": "5.20.2", "tokenizers": "0.23.3"}
SOURCE_MANIFESTS = {
    "official_source_manifest": "5eaa9f8e2fe612a41b53131629a541aaae18c3b630028f8c2be4ba1e3555c16e",
    "quantized_source_manifest": "e05f01bf5874ab6a01f179d753df9d79f95f71ee2850a8b6ec634dec41741858",
}
R3_ROWS = {
    "train": ("R3-SEED-owner-and-relevant-progress-1", "owner-and-relevant-progress",
              "f68efb68ed87080ee2eb024fff2b782f77e97001e2aca648a6a08081a7b9b70f"),
    "dev": ("R3-SEED-empty-todo-complete-read-1", "empty-todo-complete-read",
            "151a8f426722d0298dcf785c1fac45fe287d3717be4d7ca0cdd21d27226a3009"),
}
LORA = {"rank": 8, "scale": 2.0, "dropout": 0.0,
        "keys": ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj", "self_attn.o_proj",
                 "linear_attn.in_proj_qkv", "linear_attn.in_proj_z", "linear_attn.in_proj_a",
                 "linear_attn.in_proj_b", "linear_attn.out_proj"]}


def inventory():
    packages = {}
    for name in (*PACKAGE_VERSIONS, "psutil"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"system": platform.system(), "machine": platform.machine(), "packages": packages,
            "model_loaded": False, "numerical_validation": "not_run"}


def validate_environment(manifest):
    observed = inventory()
    if observed["system"] != "Darwin" or observed["machine"] != "arm64":
        raise TrainingInputError("R4 MLX execution requires the reviewed Apple Silicon environment")
    if manifest.get("mlx_lm_source_commit") != MLX_LM_COMMIT:
        raise TrainingInputError("Re-audit the exact MLX-LM source before changing versions")
    declared = manifest.get("package_versions", {})
    for name, version in PACKAGE_VERSIONS.items():
        if declared.get(name) != version or observed["packages"].get(name) != version:
            raise TrainingInputError(f"Unreviewed/missing runtime dependency: {name}")
    if not isinstance(declared.get("psutil"), str) or observed["packages"]["psutil"] != declared["psutil"]:
        raise TrainingInputError("Record the existing psutil version; do not install it automatically")
    spec = importlib.util.find_spec("mlx_lm")
    locations = list(spec.submodule_search_locations or []) if spec else []
    if len(locations) != 1:
        raise TrainingInputError("Cannot identify one installed MLX-LM source directory")
    root, verified = Path(locations[0]).resolve(), {}
    for name, expected in MLX_LM_BLOBS.items():
        raw = local_child(root, name).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if actual != expected:
            raise TrainingInputError(f"Installed MLX-LM source differs from the reviewed tag: {name}")
        verified[name] = {"git_blob": actual, "sha256": hashlib.sha256(raw).hexdigest()}
    return {**observed, "mlx_lm_source_commit": MLX_LM_COMMIT, "verified_source": verified}


def validate_base(manifest, *, hash_weights=False):
    if manifest.get("schema") != "am-style-mlx-r4-base/1":
        raise TrainingInputError("Wrong R4 MLX base manifest schema")
    if (manifest.get("repo") != BASE_REPO or manifest.get("revision") != BASE_REVISION
            or manifest.get("scope") != "independent_official_HF_text_branch"
            or manifest.get("production_equivalence_verified") is not False):
        raise TrainingInputError("Only the approved independent baseline is in this experiment's scope")
    root = Path(required_text(manifest, "local_model_path"))
    if not root.is_absolute() or not root.is_dir():
        raise TrainingInputError("An existing absolute model directory is required; downloads are not supported")
    files = manifest.get("files")
    needed = {"config.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "model.safetensors.index.json"}
    if not isinstance(files, dict) or not needed.issubset(files):
        raise TrainingInputError("Seal model/tokenizer/template/index files and every local weight shard")
    actual_weights = {p.name for p in root.glob("*.safetensors")}
    if not actual_weights or actual_weights != {n for n in files if n.endswith(".safetensors")}:
        raise TrainingInputError("MLX weight shard set differs from the declared snapshot")
    for name, record in files.items():
        if not isinstance(record, dict):
            raise TrainingInputError("Each snapshot file requires bytes and sha256")
        require_sha(record.get("sha256"), name)
        path = local_child(root, name)
        if path.stat().st_size != record.get("bytes"):
            raise TrainingInputError(f"Snapshot size mismatch: {name}")
        if (hash_weights or not name.endswith(".safetensors")) and file_hash(path) != record["sha256"]:
            raise TrainingInputError(f"Snapshot hash mismatch: {name}")
    for key in ("official_source_manifest", "quantized_source_manifest"):
        evidence = manifest.get(key, {})
        if evidence.get("sha256") != SOURCE_MANIFESTS[key]:
            raise TrainingInputError("Only the source manifests sealed in R3 identify this approved independent baseline")
        source = Path(required_text(evidence, "path"))
        if not source.is_absolute() or not source.is_file() or file_hash(source) != require_sha(evidence.get("sha256"), key):
            raise TrainingInputError(f"Missing/changed local provenance record: {key}")
        meta = read_json(source)
        if meta.get("repo", meta.get("source_model")) != BASE_REPO or meta.get("revision", meta.get("source_revision")) != BASE_REVISION:
            raise TrainingInputError("Local snapshot provenance does not identify the approved independent revision")
        if key == "quantized_source_manifest":
            old = {item["file"]: item["sha256"] for item in meta.get("files", [])}
            if old != {name: entry["sha256"] for name, entry in files.items()}:
                raise TrainingInputError("4-bit snapshot differs from its original sealed provenance manifest")
    config = read_json(root / "config.json")
    text_config = config.get("text_config", config)
    quant = config.get("quantization", config.get("quantization_config", {}))
    if (config.get("model_type") != "qwen3_5" or text_config.get("num_hidden_layers") != 64
            or text_config.get("tie_word_embeddings", False) is not False or quant.get("bits") != 4):
        raise TrainingInputError("R4 runtime supports only the sealed 64-layer, untied-head 4-bit text branch")
    return {"manifest_sha256": object_hash(manifest), "metadata_verified": True,
            "weights_verified": hash_weights, "production_equivalence_verified": False,
            "base_revision": BASE_REVISION, "model_loaded": False}


def validate_native_prompt(row):
    from am_style.contracts import StylePolicy
    from am_style.prompt import build_messages, coordinator_messages
    prompt = row["prompt"]
    if len(prompt) != 1 or prompt[0].get("role") != "user":
        raise TrainingInputError("Use the real native_chat single-user envelope, not inner logical chat roles")
    try:
        envelope = json.loads(prompt[0]["content"])
        if set(envelope) != {"messages", "tools"} or envelope["tools"] != []:
            raise ValueError("tools/envelope")
        inner = envelope["messages"]
        if len(inner) != 2 or [x["role"] for x in inner] != ["system", "user"]:
            raise ValueError("logical roles")
        if not all(isinstance(x["content"], str) and x["content"] for x in inner):
            raise ValueError("logical contents")
        payload = json.loads(inner[1]["content"])
        expected_keys = {"prompt_version", "question", "family", "context", "obligations", "speech_units", "style", "deferred_gap_count"}
        if set(payload) != expected_keys:
            raise ValueError("host payload")
        policy = StylePolicy(**payload["style"])
        if policy.as_dict() != payload["style"] or policy.version != row["provenance"]["style_policy_version"]:
            raise ValueError("style profile")
        frame = {key: payload[key] for key in ("question", "family", "context", "obligations", "deferred_gap_count")}
        frame["units"] = [{"covers": unit["covers"], "variants": unit["sayings"]} for unit in payload["speech_units"]]
        if coordinator_messages(build_messages(frame, policy)) != prompt:
            raise ValueError("current host builder differs")
        canonical = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if canonical != prompt[0]["content"]:
            raise ValueError("noncanonical transport")
    except (ValueError, TypeError, KeyError) as exc:
        raise TrainingInputError("Invalid sealed native_chat transport") from exc


def validate_plan(config):
    if config.get("schema") != "am-style-mlx-r4-run/1" or config.get("stage") not in {"mechanics", "pilot"}:
        raise TrainingInputError("Choose an explicit R4 mechanics or pilot stage")
    if config.get("quality_tier") != "gold" or type(config.get("epochs")) is not int or config["epochs"] != 1:
        raise TrainingInputError("This experiment uses one pass over approved gold only; never repeat one row to fill steps")
    if config.get("adapted_layers") != 2 or config.get("lora") != LORA:
        raise TrainingInputError("Keep the reviewed last-two-layer LoRA configuration in this first R4 pilot")
    if (config.get("learning_rate") != 1e-5 or config.get("weight_decay") != 0.01
            or config.get("optimizer_bias_correction") is not False):
        raise TrainingInputError("Preserve R3's audited MLX AdamW defaults explicitly: lr=1e-5, weight_decay=0.01, bias_correction=false")
    if type(config.get("seed")) is not int or config["seed"] != 221:
        raise TrainingInputError("The first controlled R4 run keeps the recorded seed 221")
    if type(config.get("max_length")) is not int or not 128 <= config["max_length"] <= 1024:
        raise TrainingInputError("The first R4 experiment is limited to 1024 tokens without truncation")
    if type(config.get("worker_timeout_seconds")) is not int or not 30 <= config["worker_timeout_seconds"] <= 300:
        raise TrainingInputError("A worker must have an explicit 30–300 second wall limit")
    if type(config.get("gradient_accumulation")) is not int:
        raise TrainingInputError("gradient_accumulation must be an integer")
    if config.get("stage") == "mechanics" and config.get("gradient_accumulation") != 1:
        raise TrainingInputError("Mechanics performs exactly one update on the existing one train row")
    if config.get("stage") == "pilot" and config.get("gradient_accumulation") != 4:
        raise TrainingInputError("The first pilot uses four distinct examples per optimizer step")
    expected_builder = require_sha(config.get("runtime_prompt_builder_sha256"), "runtime_prompt_builder_sha256")
    from am_style import prompt as runtime_prompt
    actual_builder = Path(runtime_prompt.__file__).resolve()
    if file_hash(actual_builder) != expected_builder:
        raise TrainingInputError("Prompt builder changed since data alignment; re-align and re-review first")
    train, dev = load_training_data(config, "sft", quality_tier="gold")
    for row in train + dev:
        validate_native_prompt(row)
        known = {value[1]: split for split, value in R3_ROWS.items()}
        if row["provenance"]["group_id"] in known and known[row["provenance"]["group_id"]] != row["provenance"]["split"]:
            raise TrainingInputError("The original R3 gold scenario group split must not change")
    for rows in (train, dev):
        if len({r["provenance"]["prompt_sha256"] for r in rows}) != len(rows):
            raise TrainingInputError("Duplicate prompts cannot be used to manufacture more training steps")
    if config["stage"] == "mechanics":
        for split, rows in (("train", train), ("dev", dev)):
            rid, group, expected_sha = R3_ROWS[split]
            if len(rows) != 1 or rows[0]["id"] != rid or rows[0]["provenance"]["group_id"] != group or config[split + "_sha256"] != expected_sha:
                raise TrainingInputError("Mechanics must use the unchanged R3 1-train/1-dev files")
    else:
        if len(train) < 24 or len(dev) < 8 or len({r["provenance"]["group_id"] for r in train}) < 8 or len({r["provenance"]["group_id"] for r in dev}) < 4:
            raise TrainingInputError("Pilot requires >=24 train/8 dev gold rows across >=8/4 disjoint groups; collect data first")
        if len(train) > 48 or len(dev) > 16:
            raise TrainingInputError("This first pilot is capped at 48 train/16 dev; revise the resource plan before expanding")
        validate_mechanics_gate(config)
    return train, dev


def validate_mechanics_gate(config):
    """Bind the pilot to a complete real mechanics artifact graph, not a flag."""
    from training.mlx_r4_runtime import code_hashes
    proof = config.get("mechanics_result", {})
    path = Path(required_text(proof, "path"))
    if not path.is_absolute() or not path.is_file() or file_hash(path) != require_sha(proof.get("sha256"), "mechanics_result"):
        raise TrainingInputError("Pilot needs the sealed actual R4 mechanics result")
    result = read_json(path)
    if result.get("schema") != "am-style-mlx-r4-result/1" or result.get("mechanics_closed") is not True:
        raise TrainingInputError("Prior mechanics did not close the fresh-load loop")
    required = {"request.json", "fit.json", "reload.json", "kernel-validation.json", "steps.json", "adapters.safetensors", "adapter_config.json"}
    hashes = result.get("files_sha256", {})
    if not required.issubset(hashes):
        raise TrainingInputError("Mechanics artifact graph is incomplete")
    for name in required:
        if file_hash(local_child(path.parent, name)) != require_sha(hashes[name], name):
            raise TrainingInputError(f"Mechanics artifact changed: {name}")
    request = read_json(path.parent / "request.json")
    fit = read_json(path.parent / "fit.json")
    reload_record = read_json(path.parent / "reload.json")
    kernel = read_json(path.parent / "kernel-validation.json")
    if (request.get("config", {}).get("stage") != "mechanics" or request.get("code_sha256") != code_hashes()
            or request.get("manifest", {}).get("revision") != BASE_REVISION
            or result.get("request_sha256") != object_hash(request)
            or fit.get("request_sha256") != object_hash(request)
            or reload_record.get("request_sha256") != object_hash(request)):
        raise TrainingInputError("Mechanics belongs to another source/base/request")
    if (fit.get("training_completed") is not True or fit.get("optimizer_steps") != 1
            or (fit.get("train_examples"), fit.get("dev_examples")) != (1, 1)
            or reload_record.get("fresh_load_verified") is not True
            or reload_record.get("adapter_complete_keyset_verified") is not True
            or reload_record.get("adapter_tensor_equality_verified") is not True
            or reload_record.get("fit_record_sha256") != hashes["fit.json"]
            or fit.get("adapter_sha256") != hashes["adapters.safetensors"]
            or reload_record.get("adapter_sha256") != hashes["adapters.safetensors"]):
        raise TrainingInputError("Mechanics update/adapter/fresh-load evidence is inconsistent")
    if (kernel.get("status") != "passed_on_actual_mlx" or kernel.get("numerical_validation_executed") is not True
            or kernel.get("code_sha256") != request["code_sha256"]
            or fit.get("kernel_validation_sha256") != hashes["kernel-validation.json"]):
        raise TrainingInputError("Actual source-bound kernel validation is required before pilot")


def encode_row(tokenizer, row, max_length):
    opts = {"enable_thinking": False, "preserve_thinking": False, "return_dict": False}
    prompt = tokenizer.apply_chat_template(row["prompt"], tokenize=True, add_generation_prompt=True, **opts)
    full = tokenizer.apply_chat_template(row["prompt"] + row["completion"], tokenize=True, add_generation_prompt=False, **opts)
    rendered = tokenizer.apply_chat_template(row["prompt"], tokenize=False, add_generation_prompt=True, **opts)
    if list(tokenizer.encode(rendered, add_special_tokens=False)) != list(prompt):
        raise TrainingInputError("Rendered inference prompt token IDs differ from training token IDs")
    p = len(prompt)
    if p < 1 or len(full) <= p or len(full) > max_length or list(full[:p]) != list(prompt):
        raise TrainingInputError("Invalid completion boundary/length; never truncate or relabel prompt tokens")
    eos = getattr(tokenizer, "eos_token_ids", None) or getattr(tokenizer, "eos_token_id", None)
    eos = {eos} if isinstance(eos, int) else set(eos or [])
    ends = [i for i in range(p, len(full)) if full[i] in eos]
    if len(ends) != 1 or tokenizer.decode(full[ends[0] + 1:], skip_special_tokens=False).strip():
        raise TrainingInputError("Completion must include exactly one EOS/EOM followed only by template whitespace")
    labels = [-100] * p + list(full[p:])
    positions = [i for i, label in enumerate(labels[1:]) if label != -100]
    if positions != list(range(p - 1, len(full) - 1)):
        raise TrainingInputError("Shifted next-token loss includes prompt tokens or drops completion tokens")
    return {"id": row["id"], "split": row["provenance"]["split"], "input_ids": list(full),
            "labels": labels, "loss_positions": positions, "prompt_tokens": p,
            "completion_tokens": len(full) - p, "eos_position": ends[0], "token_ids_sha256": object_hash(list(full)),
            "prompt_ids_sha256": object_hash(list(prompt)), "prompt_sha256": row["provenance"]["prompt_sha256"]}


def require_finite_update(gradient, delta):
    if gradient.get("all_finite") is not True or not math.isfinite(gradient.get("l2_norm", float("nan"))) or gradient["l2_norm"] <= 0:
        raise TrainingInputError("Gradient must be finite and nonzero before an optimizer update")
    if (delta.get("all_finite") is not True or not math.isfinite(delta.get("max_abs", float("nan")))
            or delta["max_abs"] <= 0 or delta.get("changed_tensors", 0) < 1 or delta.get("changed_lora_b", 0) < 1):
        raise TrainingInputError("Adapter update must change real finite LoRA-B tensors; optimizer call count is insufficient")


def compare_teacher(before, after, *, reload_check=False, atol=5e-4):
    if set(before) != set(after) or not before:
        raise TrainingInputError("Teacher-forced diagnostic case set differs")
    rows, total_nll_before, total_nll_after, total_tokens = [], 0.0, 0.0, 0
    splits = {}
    for rid in before:
        a, b = before[rid], after[rid]
        if a["token_ids_sha256"] != b["token_ids_sha256"] or a["target_ids"] != b["target_ids"]:
            raise TrainingInputError("Teacher-forced inputs/targets differ between arms")
        split = a.get("split", "diagnostic")
        if split != b.get("split", "diagnostic"):
            raise TrainingInputError("Teacher-forced split changed between arms")
        if (not a["target_logprobs"] or len(a["target_logprobs"]) != len(a["target_ids"])
                or len(a["target_logprobs"]) != len(b["target_logprobs"])
                or not a["probe_logits"] or len(a["probe_logits"]) != len(b["probe_logits"])):
            raise TrainingInputError("Teacher-forced diagnostic vectors differ in length")
        if a["probe_coordinates"] != b["probe_coordinates"]:
            raise TrainingInputError("Logit probe coordinates changed between arms")
        values = a["target_logprobs"] + b["target_logprobs"] + a["probe_logits"] + b["probe_logits"]
        if not values or not all(math.isfinite(value) for value in values):
            raise TrainingInputError("Non-finite teacher-forced diagnostic")
        lp_delta = max(abs(x - y) for x, y in zip(a["target_logprobs"], b["target_logprobs"]))
        logit_delta = max(abs(x - y) for x, y in zip(a["probe_logits"], b["probe_logits"]))
        if reload_check and max(lp_delta, logit_delta) > atol:
            raise TrainingInputError("Fresh-loaded adapter does not reproduce the saved checkpoint diagnostics")
        count = len(a["target_logprobs"])
        na, nb = -sum(a["target_logprobs"]), -sum(b["target_logprobs"])
        total_nll_before += na; total_nll_after += nb; total_tokens += count
        totals = splits.setdefault(split, {"nll_before": 0.0, "nll_after": 0.0, "completion_tokens": 0})
        totals["nll_before"] += na; totals["nll_after"] += nb; totals["completion_tokens"] += count
        rows.append({"id": rid, "split": split, "completion_tokens": count, "nll_before": na / count, "nll_after": nb / count,
                     "max_target_logprob_abs_delta": lp_delta, "max_probe_logit_abs_delta": logit_delta})
    return {"rows": rows, "token_weighted_nll_before": total_nll_before / total_tokens,
            "token_weighted_nll_after": total_nll_after / total_tokens, "completion_tokens": total_tokens,
            "by_split": {split: {"token_weighted_nll_before": value["nll_before"] / value["completion_tokens"],
                                  "token_weighted_nll_after": value["nll_after"] / value["completion_tokens"],
                                  "completion_tokens": value["completion_tokens"]} for split, value in splits.items()},
            "reload_within_tolerance": True if reload_check else None,
            "quality_conclusion": "not_established; these are probability diagnostics, not human naturalness scores"}
