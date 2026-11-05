"""Explicit synthetic experimental workers, derived from the audited R4 numerics.
Original gold validation and runtime files remain unchanged.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from training.common import TrainingInputError, file_hash, object_hash, read_json
from training.mlx_r4_contracts import (BASE_REVISION, LORA, compare_teacher, encode_row,
                                      require_finite_update, validate_base,
                                      validate_environment)
from training.mlx_synthetic_contracts import validate_plan
from training.mlx_r4_resources import OriginalLease


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def code_hashes():
    from training.mlx_r4_runtime import code_hashes as original_hashes
    root=Path(__file__).resolve().parent
    return {**original_hashes(), **{f'training/{name}':file_hash(root/name) for name in
        ('mlx_synthetic.py','mlx_synthetic_runtime.py','mlx_synthetic_contracts.py')}}


def _load(manifest, rows, config):
    import mlx.core as mx
    from mlx_lm import load
    mx.set_memory_limit(22 * 2**30)
    mx.set_cache_limit(128 * 2**20)
    mx.random.seed(config["seed"])
    model, tokenizer = load(manifest["local_model_path"], tokenizer_config={"trust_remote_code": False})
    if model.model_type != "qwen3_5" or len(model.layers) != 64:
        raise TrainingInputError("Actual loaded model is not the sealed Qwen3.5 64-layer text branch")
    template = getattr(tokenizer, "chat_template", None)
    if not isinstance(template, str) or hashlib.sha256(template.encode()).hexdigest() != manifest["files"]["chat_template.jinja"]["sha256"]:
        raise TrainingInputError("Loaded tokenizer chat template differs from the sealed MLX snapshot")
    encoded = [encode_row(tokenizer, row, config["max_length"]) for row in rows]
    return model, tokenizer, encoded


def _completion_logits(model, encoded, mx):
    ids, positions = encoded["input_ids"], encoded["loss_positions"]
    hidden = model.model(mx.array([ids[:-1]], dtype=mx.int32))
    selected = mx.take(hidden, mx.array(positions), axis=1)[0]
    # Exact reviewed untied-head architecture. Avoid allocating vocabulary
    # logits for every prompt token; still backpropagate through full context.
    return model.language_model.lm_head(selected).astype(mx.float32)


def _teacher(model, encoded_rows, lease):
    import mlx.core as mx
    result = {}
    model.eval()
    for row in encoded_rows:
        lease.check()
        logits = _completion_logits(model, row, mx)
        targets = [row["input_ids"][index + 1] for index in row["loss_positions"]]
        lps = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
        target_lps = mx.take_along_axis(lps, mx.array(targets)[:, None], axis=-1)[:, 0]
        token_positions = sorted({0, len(targets) // 2, len(targets) - 1})
        vocab_ids = sorted(set(targets) | set(range(min(16, logits.shape[-1]))))
        coords = [[p, v] for p in token_positions for v in vocab_ids]
        probe = mx.stack([logits[p, v] for p, v in coords])
        mx.eval(target_lps, probe)
        if not bool(mx.all(mx.isfinite(target_lps))) or not bool(mx.all(mx.isfinite(probe))):
            raise TrainingInputError("Non-finite teacher-forced outputs")
        result[row["id"]] = {"split": row["split"], "token_ids_sha256": row["token_ids_sha256"], "target_ids": targets,
                             "target_logprobs": target_lps.tolist(), "probe_coordinates": coords,
                             "probe_logits": probe.tolist(), "probe_scope": "first/middle/last completion positions; target token vocabulary plus ids 0..15"}
    return result


def _gradient_stats(grads, expected_keys, mx, *, require_nonzero=True):
    from mlx.utils import tree_flatten
    flat = dict(tree_flatten(grads))
    if set(flat) != set(expected_keys):
        raise TrainingInputError("Gradient leaf set differs from the exact LoRA trainable set")
    mx.eval(grads)
    finite = all(bool(mx.all(mx.isfinite(value))) for value in flat.values())
    norm_squared = sum(float(mx.sum(value.astype(mx.float32) ** 2)) for value in flat.values())
    norm = math.sqrt(norm_squared) if norm_squared >= 0 else float("nan")
    if not finite or not math.isfinite(norm) or (require_nonzero and norm <= 0):
        raise TrainingInputError("Non-finite or zero task gradients; do not call the optimizer")
    return {"all_finite": finite, "l2_norm": norm, "tensors": len(flat)}


def _delta_stats(before, after, mx):
    if set(before) != set(after):
        raise TrainingInputError("Adapter key set changed during optimization")
    changed, changed_b, max_abs, norm_sq, finite = 0, 0, 0.0, 0.0, True
    for key in before:
        if before[key].shape != after[key].shape or before[key].dtype != after[key].dtype:
            raise TrainingInputError("Adapter shape/dtype changed during optimization")
        delta = after[key].astype(mx.float32) - before[key].astype(mx.float32)
        mx.eval(delta)
        finite = finite and bool(mx.all(mx.isfinite(delta)))
        peak = float(mx.max(mx.abs(delta)))
        max_abs = max(max_abs, peak)
        norm_sq += float(mx.sum(delta * delta))
        changed += int(peak > 0)
        changed_b += int(peak > 0 and key.endswith("lora_b"))
    return {"all_finite": finite, "max_abs": max_abs, "l2_norm": math.sqrt(norm_sq),
            "changed_tensors": changed, "changed_lora_b": changed_b}


def _assert_adapter_equal(saved, actual, mx):
    if not saved or set(saved) != set(actual):
        raise TrainingInputError("Adapter is incomplete; upstream strict=False is not sufficient")
    mx.eval(saved, actual)
    if any(saved[key].shape != actual[key].shape or saved[key].dtype != actual[key].dtype
           or not bool(mx.array_equal(saved[key], actual[key])) for key in saved):
        raise TrainingInputError("Adapter tensor equality check failed")


def fit(request, output):
    manifest, config = request["manifest"], request["config"]
    train, dev = validate_plan(config)
    environment = validate_environment(manifest)
    base = validate_base(manifest, hash_weights=True)
    with OriginalLease(manifest, config["worker_timeout_seconds"]) as lease:
        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim
        from mlx.utils import tree_flatten, tree_map
        from mlx_lm.tuner.utils import linear_to_lora_layers
        from mlx_lm.tuner.trainer import grad_checkpoint
        from training.mlx_r4_kernels.chunk_gated_delta import validate_numerics, patched_training_kernel
        mx.set_memory_limit(22 * 2**30); mx.set_cache_limit(128 * 2**20)
        model_config = read_json(Path(manifest["local_model_path"]) / "config.json")
        numerical = validate_numerics(model_config.get("text_config", model_config))
        numerical["environment"] = environment
        numerical["code_sha256"] = request["code_sha256"]
        atomic_json(output / "kernel-validation.json", numerical)
        lease.check(before_load=True)
        model, tokenizer, all_encoded = _load(manifest, train + dev, config)
        train_encoded, dev_encoded = all_encoded[:len(train)], all_encoded[len(train):]
        atomic_json(output / "tokenized.json", all_encoded)
        # All dev rows plus one train example: teacher-forced diagnostics are
        # explicitly exposed diagnostics, never a new sealed effectiveness test.
        diagnostic_rows = [train_encoded[0], *dev_encoded]
        baseline_teacher = _teacher(model, diagnostic_rows, lease)
        atomic_json(output / "teacher-base.json", baseline_teacher)
        model.freeze()
        linear_to_lora_layers(model, 2, LORA)
        initial = dict(tree_flatten(model.trainable_parameters()))
        if not initial or not all(key.endswith(("lora_a", "lora_b")) for key in initial) or sum(value.size for value in initial.values()) != 713472:
            raise TrainingInputError("Actual trainable parameters differ from the reviewed 713472-parameter LoRA scope")
        mx.eval(initial)
        mx.save_safetensors(str(output / "adapter-initial.safetensors"), initial)
        initial = mx.load(str(output / "adapter-initial.safetensors"))
        initial_teacher = _teacher(model, diagnostic_rows, lease)
        compare_teacher(baseline_teacher, initial_teacher, reload_check=True)
        # Upstream grad_checkpoint changes the decoder-layer CLASS, not only
        # layer zero. The worker process is the isolation boundary for this patch.
        grad_checkpoint(model.layers[0])
        optimizer = optim.AdamW(learning_rate=config["learning_rate"], weight_decay=config["weight_decay"],
                               bias_correction=config["optimizer_bias_correction"], betas=config["optimizer_betas"], eps=config["optimizer_eps"])
        order = list(train_encoded); random.Random(config["seed"]).shuffle(order)
        accumulation = config["gradient_accumulation"]
        steps, consumed_ids = [], []
        fit_started = time.monotonic()

        def loss(m, row):
            logits = _completion_logits(m, row, mx)
            targets = mx.array([row["input_ids"][p + 1] for p in row["loss_positions"]])
            return nn.losses.cross_entropy(logits, targets, reduction="mean")

        with patched_training_kernel():
            for offset in range(0, len(order), accumulation):
                batch = order[offset:offset + accumulation]
                lease.check()
                model.train()
                for layer in model.layers[:-2]:
                    layer.eval()
                before_step = dict(tree_flatten(model.trainable_parameters()))
                total_tokens = sum(row["completion_tokens"] for row in batch)
                grads, batch_loss = None, 0.0
                example_losses = []
                for row in batch:
                    lease.check()
                    value, g = nn.value_and_grad(model, loss)(model, row)
                    mx.eval(value, g)
                    if not bool(mx.isfinite(value)):
                        raise TrainingInputError("Training loss is non-finite")
                    _gradient_stats(g, initial, mx, require_nonzero=False)
                    example_losses.append({"id":row["id"],"completion_tokens":row["completion_tokens"],"mean_token_cross_entropy":float(value)})
                    weight = row["completion_tokens"] / total_tokens
                    g = tree_map(lambda x: x * weight, g)
                    grads = g if grads is None else tree_map(lambda a, b: a + b, grads, g)
                    batch_loss += float(value) * weight
                gradient = _gradient_stats(grads, initial, mx)
                clip_scale = min(1.0, config["clip_grad_norm"] / gradient["l2_norm"])
                grads = tree_map(lambda x: x * clip_scale, grads)
                optimizer.update(model, grads)
                mx.eval(model.trainable_parameters(), optimizer.state)
                after_step = dict(tree_flatten(model.trainable_parameters()))
                delta = _delta_stats(before_step, after_step, mx)
                require_finite_update(gradient, delta)
                consumed_ids.extend(row["id"] for row in batch)
                steps.append({"optimizer_step": len(steps) + 1, "ids": [row["id"] for row in batch],
                              "completion_tokens": total_tokens, "loss": batch_loss,
                              "per_example_losses":example_losses, "elapsed_training_seconds":time.monotonic()-fit_started,
                              "gradient": gradient, "gradient_clip_scale": clip_scale, "parameter_delta": delta})
                atomic_json(output / "steps.json", steps)
        if len(consumed_ids) != len(set(consumed_ids)) or set(consumed_ids) != {row["id"] for row in train_encoded}:
            raise TrainingInputError("The pilot did not consume each distinct training row exactly once")
        actual = dict(tree_flatten(model.trainable_parameters()))
        final_delta = _delta_stats(initial, actual, mx)
        require_finite_update(steps[-1]["gradient"], final_delta)
        mx.save_safetensors(str(output / "adapters.safetensors"), actual)
        _assert_adapter_equal(mx.load(str(output / "adapters.safetensors")), actual, mx)
        atomic_json(output / "adapter_config.json", {"fine_tune_type": "lora", "num_layers": 2, "lora_parameters": LORA})
        after_teacher = _teacher(model, diagnostic_rows, lease)
        atomic_json(output / "teacher-sft.json", after_teacher)
        teacher_change = compare_teacher(baseline_teacher, after_teacher)
        record = {"schema": "am-synthetic-mlx-fit/1", "stage": "synthetic_pilot", "quality_tier":"experimental_synthetic", "human_approved":False,
                  "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                  "request_sha256": object_hash(request), "base": base, "base_revision": BASE_REVISION,
                  "environment": environment, "kernel_validation_sha256": file_hash(output / "kernel-validation.json"),
                  "training_completed": True, "optimizer_steps": len(steps), "epochs": 1,
                  "consumed_train_ids": consumed_ids, "train_examples": len(train), "dev_examples": len(dev),
                  "trainable_parameters": 713472, "parameter_delta": final_delta,
                  "tokenized_sha256": file_hash(output / "tokenized.json"),
                  "initial_adapter_sha256": file_hash(output / "adapter-initial.safetensors"),
                  "adapter_sha256": file_hash(output / "adapters.safetensors"),
                  "adapter_config_sha256": file_hash(output / "adapter_config.json"),
                  "adapter_tensor_roundtrip_verified": True, "fresh_load_verified": False,
                  "teacher_sft_sha256": file_hash(output / "teacher-sft.json"),
                  "teacher_change": teacher_change, "peak_memory_bytes": mx.get_peak_memory(),
                  "resource_checks": lease.history, "scope": "independent_official_HF_text_branch",
                  "production_changed": False, "business_acceptance": False, "quality_conclusion": "not_established"}
        atomic_json(output / "fit.json", record)
        return record


def reload_diagnostic(request, output):
    manifest, config = request["manifest"], request["config"]
    train, dev = validate_plan(config)
    environment = validate_environment(manifest)
    validate_base(manifest, hash_weights=True)
    fit_record = read_json(output / "fit.json")
    if not fit_record.get("training_completed") or fit_record.get("request_sha256") != object_hash(request):
        raise TrainingInputError("Fresh load requires the completed fit record for this exact request")
    for name, key in (("adapters.safetensors", "adapter_sha256"), ("adapter_config.json", "adapter_config_sha256"),
                      ("teacher-sft.json", "teacher_sft_sha256"), ("tokenized.json", "tokenized_sha256")):
        if file_hash(output / name) != fit_record.get(key):
            raise TrainingInputError(f"Fit artifact changed before fresh load: {name}")
    with OriginalLease(manifest, config["worker_timeout_seconds"]) as lease:
        import mlx.core as mx
        from mlx_lm.tuner.utils import load_adapters
        from mlx.utils import tree_flatten
        model, tokenizer, encoded = _load(manifest, train + dev, config)
        if encoded != read_json_list(output / "tokenized.json"):
            raise TrainingInputError("Tokenization changed in the new interpreter")
        model.freeze()
        model = load_adapters(model, str(output))
        expected = mx.load(str(output / "adapters.safetensors"))
        actual = {key: value for key, value in tree_flatten(model.parameters()) if key.endswith(("lora_a", "lora_b"))}
        _assert_adapter_equal(expected, actual, mx)
        teacher = _teacher(model, [encoded[0], *encoded[len(train):]], lease)
        report = compare_teacher(read_json(output / "teacher-sft.json"), teacher, reload_check=True)
        record = {"schema": "am-synthetic-mlx-reload/1", "request_sha256": object_hash(request),
                  "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                  "fit_record_sha256": file_hash(output / "fit.json"), "adapter_sha256": fit_record["adapter_sha256"],
                  "fresh_interpreter_pid": os.getpid(), "adapter_complete_keyset_verified": True,
                  "adapter_tensor_equality_verified": True, "fresh_load_verified": True,
                  "teacher_reload_comparison": report, "environment": environment,
                  "peak_memory_bytes": mx.get_peak_memory(), "resource_checks": lease.history,
                  "production_changed": False, "business_acceptance": False, "quality_conclusion": "not_established"}
        atomic_json(output / "reload.json", record)
        return record


def read_json_list(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise TrainingInputError("Expected a tokenized row list")
    return value


def evaluate(request, output):
    manifest,config=request['manifest'],request['config']
    validate_plan(config);validate_environment(manifest);validate_base(manifest,hash_weights=True)
    with OriginalLease(manifest,config['worker_timeout_seconds']) as lease:
        import mlx.core as mx
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler
        from mlx_lm.tuner.utils import load_adapters
        from mlx.utils import tree_flatten
        model,tokenizer,_=_load(manifest,[],config)
        if config['arm']=='sft':
            model=load_adapters(model,str(Path(config['adapter']['path']).parent))
            expected=mx.load(config['adapter']['path'])
            actual={k:v for k,v in tree_flatten(model.parameters()) if k.endswith(('lora_a','lora_b'))}
            _assert_adapter_equal(expected,actual,mx)
        cases=json.loads(Path(config['reserved_evaluation']['path']).read_text())['cases']
        records=[]
        for c in cases:
            lease.check();mx.random.seed(config['seed'])
            messages=[{'role':'system','content':config['system_prompt']},{'role':'user','content':c['question']}]
            prompt=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False,preserve_thinking=False)
            started=time.monotonic()
            text=generate(model,tokenizer,prompt=prompt,max_tokens=config['generation']['max_tokens'],sampler=make_sampler(temp=0.0),verbose=False)
            elapsed=time.monotonic()-started
            record={'case_id':c['case_id'],'arm':config['arm'],'messages':messages,'prompt_sha256':object_hash(messages),
                    'output':text,'generation_seconds':elapsed,'max_tokens':config['generation']['max_tokens'],
                    'independent_human_acceptance':False}
            records.append(record)
            atomic_json(output/'evaluation-progress.json',records)
            lease.check()
        report={'schema':'am-synthetic-mlx-evaluation/1','request_sha256':object_hash(request),'arm':config['arm'],
                'cases':records,'completed':len(records),'reserved_cases_sha256':config['reserved_evaluation']['sha256'],
                'peak_memory_bytes':mx.get_peak_memory(),'resource_checks':lease.history,
                'adapter_loaded':config['arm']=='sft','business_acceptance':False,'production_eligible':False}
        atomic_json(output/'evaluation.json',report)
        return report


def run_worker(kind, request_path):
    request_path = Path(request_path).resolve()
    output = request_path.parent
    request = read_json(request_path)
    if request.get("code_sha256") != code_hashes():
        raise TrainingInputError("Worker source changed after the request was sealed")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        result = evaluate(request, output) if kind == "eval" else fit(request, output) if kind == "fit" else reload_diagnostic(request, output)
        print(json.dumps({"worker": kind, "status": "completed", "record_sha256": object_hash(result)}))
        return 0
    except Exception as exc:
        atomic_json(output / f"{kind}-failure.json", {"status": "blocked_or_failed", "worker": kind,
            "error_type": type(exc).__name__, "reason": str(exc), "time": datetime.now(timezone.utc).isoformat(),
            "production_changed": False, "business_acceptance": False,
            "retry": "not_automatic; inspect saved evidence and create a new explicit run"})
        raise
