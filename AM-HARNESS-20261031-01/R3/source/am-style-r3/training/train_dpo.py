"""DPO starts from an SFT LoRA checkpoint; its fixed reference is the same SFT.

API target: TRL 1.17.1. Never silently disable the adapter to use plain base.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from training.common import (TrainingInputError, load_training_data, object_hash, read_json,
                             strip_provenance, validate_environment, validate_model_manifest,
                             validate_sft_checkpoint, validate_tokenization, write_json)
from training.runtime import validate_model_architecture


def validate_beta(config):
    try:
        value = config.get("beta", 0.1)
        if isinstance(value, bool):
            raise ValueError("boolean is not a beta")
        beta = float(value)
    except (TypeError, ValueError) as exc:
        raise TrainingInputError("DPO beta must be a finite positive number") from exc
    if not math.isfinite(beta) or beta <= 0:
        raise TrainingInputError("DPO beta must be a finite positive number")
    return beta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--sft-adapter", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    manifest, config = read_json(args.manifest), read_json(args.config)
    beta = validate_beta(config)
    adapter = Path(args.sft_adapter)
    sft_record = read_json(adapter / "training_record.json")
    validate_model_manifest(manifest, verify_weights=args.execute)
    architecture = validate_model_architecture(manifest)
    validate_sft_checkpoint(manifest, sft_record, adapter)
    train, dev = load_training_data(config, "dpo")
    print(json.dumps({"stage": "dpo", "train": len(train), "dev": len(dev),
                      "reference": "fixed SFT adapter copy", "execute": args.execute,
                      "architecture": architecture}))
    if not args.execute:
        return 0
    environment = validate_environment(manifest)
    from datasets import Dataset
    from peft import PeftModel
    from trl import DPOConfig, DPOTrainer
    from training.runtime import (load_base, load_tokenizer, reference_callback, reference_digest,
                                  training_kwargs, verify_reference_copy, write_completion)
    tokenizer = load_tokenizer(manifest)
    token_report = validate_tokenization(tokenizer, train + dev, int(config.get("max_length", 2048)), "dpo")
    output = Path(config["output_dir"])
    if output.exists() and any(output.iterdir()):
        raise TrainingInputError("output_dir must be new/empty")
    base = load_base(manifest, config)
    model = PeftModel.from_pretrained(base, str(adapter), adapter_name="default", is_trainable=True,
                                     local_files_only=True)
    if model.peft_config["default"].modules_to_save:
        raise TrainingInputError("modules_to_save need a separately validated reference strategy")
    trainer = DPOTrainer(
        model=model, ref_model=None, processing_class=tokenizer,
        args=DPOConfig(**training_kwargs(config, output), beta=beta,
                       loss_type="sigmoid", sync_ref_model=False, precompute_ref_log_probs=False),
        train_dataset=Dataset.from_list(strip_provenance(train, "dpo")),
        eval_dataset=Dataset.from_list(strip_provenance(dev, "dpo")),
    )
    # TRL clones the preloaded 'default' adapter to 'ref'. If this does not happen,
    # abort, because using ref_model=None otherwise falls back to the plain base.
    names = verify_reference_copy(trainer.model)
    initial_reference = reference_digest(trainer.model, names)
    trainer.add_callback(reference_callback(trainer.model, names, initial_reference))
    write_json(output / "preflight.json", {
        "environment": environment, "architecture": architecture, "tokens": token_report, "reference": "fixed SFT",
        "sft_record_sha256": object_hash(sft_record), "reference_sha256": initial_reference,
        "reference_parameter_count": len(names),
    })
    result = trainer.train()
    metrics = {**result.metrics, **trainer.evaluate()}
    if reference_digest(trainer.model, names) != initial_reference:
        raise TrainingInputError("Reference changed; checkpoint not marked completed")
    # Only the optimized policy adapter is the deployable artifact. The ref copy
    # is verification context; it must not accidentally become the served adapter.
    trainer.model.set_adapter("default")
    trainer.model.save_pretrained(output, selected_adapters=["default"], safe_serialization=True)
    tokenizer.save_pretrained(output)
    trainer.save_state()
    write_completion(output, "dpo", manifest, config, metrics,
                     reference_sha256=initial_reference, sft_record_sha256=object_hash(sft_record),
                     reference_strategy="fixed_sft_adapter_copy")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainingInputError as exc:
        raise SystemExit(f"DPO preflight blocked: {exc}")
