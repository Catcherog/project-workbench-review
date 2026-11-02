"""python -m training.train_sft --manifest ... --config ... [--execute]."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.common import (TrainingInputError, load_training_data, read_json, strip_provenance,
                             validate_environment, validate_model_manifest, validate_tokenization,
                             write_json)
from training.runtime import validate_model_architecture


def check_prepared_sft_loss(dataset, collator, tokenizer, source_rows):
    """Check TRL 1.17.1's prepared labels, not a removed completion_mask column.

    Official sft_trainer.py builds labels from completion_mask and then removes
    the mask column. Verified source blob: c44253301ed3ba30b8de1eeecf17c02fb8fa3553.
    This compares the actual trainer sequence and collated labels with the exact
    inference-compatible token prefix for every supplied row, without torch.
    """
    if len(dataset) != len(source_rows):
        raise TrainingInputError("SFT preprocessing changed the number of examples")
    supervised_tokens = 0
    for index, raw in enumerate(source_rows):
        prompt_ids = tokenizer.apply_chat_template(raw["prompt"], tokenize=True, add_generation_prompt=True)
        full_ids = tokenizer.apply_chat_template(raw["prompt"] + raw["completion"],
                                                 tokenize=True, add_generation_prompt=False)
        prompt_length = len(prompt_ids)
        if full_ids[:prompt_length] != prompt_ids or len(full_ids) <= prompt_length:
            raise TrainingInputError("SFT template boundary has no valid completion")
        sample = dataset[index]
        if list(sample.get("input_ids", [])) != full_ids:
            raise TrainingInputError("Trainer tokenization/truncation differs from the frozen prompt")
        expected = [-100] * prompt_length + full_ids[prompt_length:]
        if list(sample.get("labels", [])) != expected:
            raise TrainingInputError("Prepared labels train prompt tokens or mask completion tokens")
        batch = collator([sample])
        labels = batch.get("labels")
        if labels is None or len(labels) != 1:
            raise TrainingInputError("Trainer collator omitted the expected single-row labels")
        actual = labels[0].tolist() if hasattr(labels[0], "tolist") else list(labels[0])
        if actual[:len(expected)] != expected or any(label != -100 for label in actual[len(expected):]):
            raise TrainingInputError("Collated labels changed prompt/completion masking")
        supervised_tokens += len(full_ids) - prompt_length
    return {"rows": len(source_rows), "supervised_completion_tokens": supervised_tokens,
            "prompt_tokens_masked": True, "prepared_labels_checked": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--execute", action="store_true", help="Load local weights and train after preflight")
    args = parser.parse_args(argv)
    manifest, config = read_json(args.manifest), read_json(args.config)
    validate_model_manifest(manifest, verify_weights=args.execute)
    architecture = validate_model_architecture(manifest)
    quality_tier = config.get("quality_tier", "gold")
    train, dev = load_training_data(config, "sft", quality_tier=quality_tier)
    targets = manifest.get("lora_target_modules")
    if not isinstance(targets, list) or not targets or not all(isinstance(x, str) and x for x in targets):
        raise TrainingInputError("Inspect this exact architecture and record lora_target_modules first")
    print(json.dumps({"stage": "sft", "train": len(train), "dev": len(dev), "execute": args.execute,
                      "quality_tier": quality_tier, "experimental_only": config.get("experimental_only", False),
                      "architecture": architecture}))
    if not args.execute:
        return 0
    environment = validate_environment(manifest)
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from trl import SFTConfig, SFTTrainer
    from training.runtime import load_base, load_tokenizer, training_kwargs, write_completion
    tokenizer = load_tokenizer(manifest)
    token_report = validate_tokenization(tokenizer, train + dev, int(config.get("max_length", 2048)), "sft")
    output = Path(config["output_dir"])
    if output.exists() and any(output.iterdir()):
        raise TrainingInputError("output_dir must be new/empty; never overwrite an existing checkpoint")
    base = load_base(manifest, config)
    model = get_peft_model(base, LoraConfig(
        r=int(config.get("lora_r", 16)), lora_alpha=int(config.get("lora_alpha", 32)),
        lora_dropout=0.05, bias="none", task_type="CAUSAL_LM", target_modules=targets,
    ))
    trainer = SFTTrainer(
        model=model, processing_class=tokenizer,
        args=SFTConfig(**training_kwargs(config, output), completion_only_loss=True,
                       assistant_only_loss=False, packing=False),
        train_dataset=Dataset.from_list(strip_provenance(train, "sft")),
        eval_dataset=Dataset.from_list(strip_provenance(dev, "sft")),
    )
    # Preserve training/inference formatting. Some trainers patch chat templates.
    import hashlib
    if hashlib.sha256(tokenizer.chat_template.encode()).hexdigest() != manifest["chat_template_sha256"]:
        raise TrainingInputError("Trainer changed chat template; inspect masking and reseal an explicit recipe")
    mask_report = {
        "train": check_prepared_sft_loss(trainer.train_dataset, trainer.data_collator, tokenizer, train),
        "dev": check_prepared_sft_loss(trainer.eval_dataset, trainer.data_collator, tokenizer, dev),
    }
    write_json(output / "preflight.json", {"environment": environment, "architecture": architecture, "tokens": token_report,
                                          "loss_mask_check": mask_report})
    result = trainer.train()
    metrics = {**result.metrics, **trainer.evaluate()}
    trainer.model.save_pretrained(output, safe_serialization=True)
    tokenizer.save_pretrained(output)
    trainer.save_state()
    write_completion(output, "sft", manifest, config, metrics)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainingInputError as exc:
        raise SystemExit(f"SFT preflight blocked: {exc}")
