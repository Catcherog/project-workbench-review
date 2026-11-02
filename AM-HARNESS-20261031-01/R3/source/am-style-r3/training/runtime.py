"""Optional CUDA/TRL runtime, loaded only after input validation."""
from __future__ import annotations

import hashlib
import ast
import importlib.metadata
import importlib.util
import json
import os
import re
import struct
from pathlib import Path

from training.common import (TrainingInputError, file_hash, local_child, object_hash,
                             read_json, required_text, write_json)


# Audited upstream source, not an invented release number or a floating main.
# Git blob IDs let preflight check installed source without importing torch or
# constructing a model. A different build requires a new compatibility review.
TRANSFORMERS_ARCHITECTURE_COMMIT = "e2e6cc93810bf705ac2ea0eefde4451ea032df42"
TRANSFORMERS_ARCHITECTURE_BLOBS = {
    "models/auto/modeling_auto.py": "4eef9b10bb3d58cb60dcdba74ba67ad7f905c43e",
    "models/auto/auto_factory.py": "a079325fd63558ea9d6104bb12004f7d9dd8a853",
    "models/qwen3_5/configuration_qwen3_5.py": "5eaa42d0b22e3e97c835d974b0f33193b2613216",
    "models/qwen3_5/modeling_qwen3_5.py": "8921ae84fda0eeae4da31b5b96a56c2c9631c914",
    "conversion_mapping.py": "e048e9da50a475b5afd3670ddebb209de9b3d2ab",
    "core_model_loading.py": "6f49b0e0fb421b35cf78d33fd8379782361c23cb",
    "modeling_utils.py": "f85d1b01a32cebe8626a6b6d997b1f46601daabf",
    "utils/loading_report.py": "8d7e71944fa9edc98d94a0601783b3390cd39cde",
}


def _installed_transformers_sources(expected_version):
    if not isinstance(expected_version, str) or not expected_version:
        raise TrainingInputError("Record the exact installed Transformers version before architecture preflight")
    try:
        observed = importlib.metadata.version("transformers")
        spec = importlib.util.find_spec("transformers")
    except (importlib.metadata.PackageNotFoundError, ImportError, ValueError) as exc:
        raise TrainingInputError("Transformers is not installed; architecture compatibility is unverified") from exc
    if observed != expected_version:
        raise TrainingInputError("Installed Transformers version differs from architecture manifest")
    locations = list(spec.submodule_search_locations or []) if spec else []
    if len(locations) != 1:
        raise TrainingInputError("Cannot identify one local Transformers source directory")
    root = Path(locations[0]).resolve()
    sources = {}
    for relative, expected_blob in TRANSFORMERS_ARCHITECTURE_BLOBS.items():
        path = local_child(root, relative)
        raw = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        if blob != expected_blob:
            raise TrainingInputError(f"Unaudited Transformers architecture source: {relative}; re-audit before loading")
        sources[relative] = raw.decode("utf-8")
    return sources


def _causal_registry(source):
    """Read the installed static registry with stdlib AST, without importing it."""
    try:
        for node in ast.parse(source).body:
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "MODEL_FOR_CAUSAL_LM_MAPPING_NAMES" for t in node.targets)
                    and isinstance(node.value, ast.Call) and len(node.value.args) == 1):
                return dict(ast.literal_eval(node.value.args[0]))
    except (SyntaxError, ValueError, TypeError) as exc:
        raise TrainingInputError("Cannot inspect installed AutoModelForCausalLM registry") from exc
    raise TrainingInputError("Installed AutoModelForCausalLM registry is unavailable")


def _checkpoint_tensor_names(root, manifest):
    """Read Safetensors headers only; no tensors, GPU imports or Hub requests."""
    declared = manifest.get("weight_files_sha256")
    if not isinstance(declared, dict) or not declared:
        raise TrainingInputError("Architecture preflight needs the declared local Safetensors snapshot")
    names = {}
    for relative in sorted(declared):
        path = local_child(root, relative)
        with path.open("rb") as stream:
            prefix = stream.read(8)
            if len(prefix) != 8:
                raise TrainingInputError("Invalid Safetensors metadata header")
            size = struct.unpack("<Q", prefix)[0]
            if size < 2 or size > 64 * 1024 * 1024 or size > path.stat().st_size - 8:
                raise TrainingInputError("Invalid or excessively large Safetensors metadata header")
            try:
                header = json.loads(stream.read(size))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise TrainingInputError("Invalid Safetensors metadata JSON") from exc
        if not isinstance(header, dict):
            raise TrainingInputError("Safetensors header must be an object")
        for name, descriptor in header.items():
            if name == "__metadata__":
                continue
            if name in names or not isinstance(descriptor, dict):
                raise TrainingInputError("Duplicate/invalid tensor in declared weight snapshot")
            names[name] = relative
    index = root / "model.safetensors.index.json"
    if index.is_file() and read_json(index).get("weight_map") != names:
        raise TrainingInputError("Safetensors index differs from actual local header keys")
    return names


def validate_model_architecture(manifest):
    """Fail before weights on an unknown route, source build, or checkpoint layout.

    This verifies an audited *candidate loading route*. It does not establish
    model quality, quantization support, GPU capacity or a successful short run.
    The native VLM processor/trainer path is deliberately not implemented here.
    """
    arch = manifest.get("training_architecture")
    if not isinstance(arch, dict):
        raise TrainingInputError("Missing explicit training_architecture route")
    routes = {"qwen3_5_text_compat": "qwen3_5", "qwen3_5_native_text": "qwen3_5_text"}
    route = arch.get("route")
    if route not in routes:
        raise TrainingInputError("Unsupported architecture route; use an audited text-only route, never a guessed class")
    if (arch.get("auto_class") != "AutoModelForCausalLM"
            or arch.get("expected_model_class") != "Qwen3_5ForCausalLM"
            or arch.get("expected_config_model_type") != "qwen3_5_text"
            or arch.get("text_only") is not True):
        raise TrainingInputError("Architecture route must explicitly select the audited Qwen3_5 text class/config")
    if arch.get("transformers_source_commit") != TRANSFORMERS_ARCHITECTURE_COMMIT:
        raise TrainingInputError("Architecture route requires the exact audited Transformers source commit")
    root = Path(required_text(manifest, "local_model_path"))
    if not root.is_absolute() or not root.is_dir():
        raise TrainingInputError("Architecture preflight needs an existing absolute local model directory")
    config_path = local_child(root, "config.json")
    if file_hash(config_path) != manifest.get("metadata_sha256", {}).get("config.json"):
        raise TrainingInputError("Architecture config differs from sealed metadata")
    config = read_json(config_path)
    model_type = config.get("model_type")
    if model_type != routes[route] or manifest.get("model_type") != model_type:
        raise TrainingInputError("Architecture route does not match the original config model_type")
    expected_checkpoint_class = "Qwen3_5ForConditionalGeneration" if model_type == "qwen3_5" else "Qwen3_5ForCausalLM"
    if config.get("architectures") != [expected_checkpoint_class]:
        raise TrainingInputError("Checkpoint architectures differ from the audited route")
    text_config = config.get("text_config") if model_type == "qwen3_5" else config
    if not isinstance(text_config, dict) or text_config.get("model_type") != "qwen3_5_text":
        raise TrainingInputError("Missing exact Qwen3_5 text sub-config; do not relabel or flatten config.json")
    if config.get("quantization_config") is not None or text_config.get("quantization_config") is not None:
        raise TrainingInputError("Use the exact unquantized training checkpoint; pre-quantized VLM config is not audited")
    layers = text_config.get("num_hidden_layers")
    if type(layers) is not int or layers < 1:
        raise TrainingInputError("Missing concrete text num_hidden_layers")
    sources = _installed_transformers_sources(manifest.get("package_versions", {}).get("transformers"))
    mapping = _causal_registry(sources["models/auto/modeling_auto.py"])
    if mapping.get(model_type) != "Qwen3_5ForCausalLM" or mapping.get("qwen3_5_text") != "Qwen3_5ForCausalLM":
        raise TrainingInputError("Installed AutoModelForCausalLM registry lacks the required Qwen3_5 compatibility")
    names = _checkpoint_tensor_names(root, manifest)
    prefix = "model.language_model." if model_type == "qwen3_5" else "model."
    required = {prefix + "embed_tokens.weight", prefix + "norm.weight"}
    if text_config.get("tie_word_embeddings", config.get("tie_word_embeddings", False)) is not True:
        required.add("lm_head.weight")
    if not required.issubset(names):
        raise TrainingInputError("Checkpoint is missing the audited language embedding/norm/head layout")
    layer_pattern = re.compile(re.escape(prefix) + r"layers\.(\d+)\.")
    actual_layers = {int(match.group(1)) for name in names if (match := layer_pattern.match(name))}
    if actual_layers != set(range(layers)):
        raise TrainingInputError("Checkpoint language layer set differs from text config")
    allowed_prefixes = (prefix + "layers.", prefix + "embed_tokens.", prefix + "norm.", "lm_head.", "mtp.")
    if model_type == "qwen3_5":
        allowed_prefixes += ("model.visual.",)
    if any(not name.startswith(allowed_prefixes) for name in names):
        raise TrainingInputError("Unexpected checkpoint namespace; audit weight conversion before loading")
    return {"route": route, "checkpoint_model_type": model_type,
            "loaded_model_class": "Qwen3_5ForCausalLM", "loaded_config_model_type": "qwen3_5_text",
            "transformers_source_commit": TRANSFORMERS_ARCHITECTURE_COMMIT,
            "source_registry_verified": True, "checkpoint_header_keys": len(names),
            "tensor_data_read": False, "model_loading": False, "training_compatibility_proven": False}


def validate_loaded_text_model(model, loading_info):
    """Never continue training after silently initialized language weights."""
    if type(model).__name__ != "Qwen3_5ForCausalLM" or getattr(model.config, "model_type", None) != "qwen3_5_text":
        raise TrainingInputError("Loaded model is not the explicitly selected text-only class/config")
    required = {"missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"}
    if not isinstance(loading_info, dict) or not required.issubset(loading_info):
        raise TrainingInputError("Model loader omitted weight-conversion diagnostics")
    if any(loading_info[key] for key in ("missing_keys", "mismatched_keys", "error_msgs")):
        raise TrainingInputError("Language weights were missing/mismatched or loading failed; training blocked")
    if any(not name.startswith(("model.visual.", "mtp.")) for name in loading_info["unexpected_keys"]):
        raise TrainingInputError("Unexpected language weight after conversion; training blocked")


def load_tokenizer(manifest):
    validate_model_architecture(manifest)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        manifest["local_model_path"], local_files_only=True, trust_remote_code=False
    )
    template = tokenizer.chat_template
    if not isinstance(template, str) or hashlib.sha256(template.encode()).hexdigest() != manifest["chat_template_sha256"]:
        raise TrainingInputError("Loaded tokenizer template differs from the sealed template")
    if tokenizer.eos_token is None:
        raise TrainingInputError("Model has no explicit EOS token")
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def load_base(manifest, config):
    validate_model_architecture(manifest)
    import torch
    from peft import prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig
    if int(os.environ.get("WORLD_SIZE", "1")) != 1:
        raise TrainingInputError("This starter runtime targets one CUDA GPU; validate distributed sharding separately")
    if config.get("device") != "cuda" or not torch.cuda.is_available():
        raise TrainingInputError("CUDA runtime unavailable; MPS must use the separate MLX SFT route")
    precision = config.get("precision", "bf16")
    if precision not in {"bf16", "fp16"}:
        raise TrainingInputError("precision must be bf16 or fp16")
    if precision == "bf16" and not torch.cuda.is_bf16_supported():
        raise TrainingInputError("Selected CUDA device does not support bf16; record an explicit fp16 experiment")
    dtype = torch.bfloat16 if precision == "bf16" else torch.float16
    kwargs = dict(local_files_only=True, trust_remote_code=False, use_safetensors=True,
                  torch_dtype=dtype, device_map={"": 0}, attn_implementation="eager")
    if config.get("qlora") is True:
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
        )
    # Use upstream composite->text config extraction and checkpoint conversion.
    # Do not edit the original config or silently swap to another Qwen model.
    base, loading_info = AutoModelForCausalLM.from_pretrained(
        manifest["local_model_path"], output_loading_info=True, **kwargs
    )
    validate_loaded_text_model(base, loading_info)
    base.config.use_cache = False
    if config.get("qlora") is True:
        base = prepare_model_for_kbit_training(base, use_gradient_checkpointing=True)
    return base


def training_kwargs(config, output):
    epochs = float(config.get("epochs", 1))
    lr = float(config["learning_rate"])
    max_length = int(config.get("max_length", 2048))
    if not (0 < epochs <= 3 and 0 < lr <= 1e-3 and 128 <= max_length <= 8192):
        raise TrainingInputError("Invalid starter hyperparameters")
    return dict(
        output_dir=str(output), per_device_train_batch_size=int(config.get("batch_size", 1)),
        per_device_eval_batch_size=1, gradient_accumulation_steps=int(config.get("gradient_accumulation_steps", 16)),
        learning_rate=lr, num_train_epochs=epochs, max_length=max_length,
        bf16=config.get("precision", "bf16") == "bf16", fp16=config.get("precision") == "fp16",
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        eval_strategy="epoch", save_strategy="epoch", logging_steps=5, save_total_limit=2,
        report_to="none", push_to_hub=False, seed=int(config.get("seed", 221)),
    )


def verify_reference_copy(model):
    """Assert the TRL 1.17.1 automatic reference is SFT, never plain base."""
    import torch
    if "default" not in model.peft_config or "ref" not in model.peft_config:
        raise TrainingInputError("TRL did not create the frozen SFT reference adapter")
    model.set_adapter("default")
    pairs = []
    for name, param in model.named_parameters():
        if ".default." not in name:
            continue
        ref_name = name.replace(".default.", ".ref.")
        try:
            reference = model.get_parameter(ref_name)
        except AttributeError as exc:
            raise TrainingInputError(f"Missing reference parameter: {ref_name}") from exc
        if param.data_ptr() == reference.data_ptr() or not torch.equal(param.detach(), reference.detach()):
            raise TrainingInputError("Reference is aliased or not an exact copy of the starting SFT adapter")
        reference.requires_grad_(False)
        if not param.requires_grad:
            raise TrainingInputError("DPO policy adapter is unexpectedly frozen")
        pairs.append(ref_name)
    if not pairs:
        raise TrainingInputError("No train/reference LoRA parameter pairs found")
    return pairs


def reference_digest(model, names):
    import torch
    h = hashlib.sha256()
    for name in sorted(names):
        value = model.get_parameter(name).detach().contiguous().cpu()
        h.update(name.encode())
        h.update(str((value.dtype, tuple(value.shape))).encode())
        h.update(value.view(torch.uint8).numpy().tobytes())
    return h.hexdigest()


def reference_callback(model, names, expected):
    from transformers import TrainerCallback

    class FixedReferenceCheck(TrainerCallback):
        def on_train_begin(self, args, state, control, optimizer=None, **kwargs):
            refs = {id(model.get_parameter(name)) for name in names}
            if optimizer is None or any(id(p) in refs for group in optimizer.param_groups for p in group["params"]):
                raise TrainingInputError("Reference parameters entered the optimizer")
            if reference_digest(model, names) != expected:
                raise TrainingInputError("Reference changed before optimization")

        def on_train_end(self, args, state, control, **kwargs):
            if reference_digest(model, names) != expected:
                raise TrainingInputError("SFT reference drifted during DPO")

    return FixedReferenceCheck()


def write_completion(output, stage, manifest, config, metrics, **extra):
    paths = sorted(Path(output).glob("*.safetensors")) + [Path(output) / "adapter_config.json"]
    hashes = {p.name: file_hash(p) for p in paths if p.is_file()}
    write_json(Path(output) / "training_record.json", {
        "schema": "am-style-training-run/1", "stage": stage, "training_completed": True,
        "business_acceptance": False, "model_manifest_sha256": object_hash(manifest),
        "config_sha256": object_hash(config), "adapter_files_sha256": hashes,
        "host_contract_version": config["host_contract_version"],
        "style_policy_version": config["style_policy_version"],
        "quality_tier": config.get("quality_tier", "gold"),
        "experimental_only": config.get("experimental_only", False),
        "metrics": metrics, **extra,
    })
