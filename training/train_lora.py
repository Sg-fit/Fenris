#!/usr/bin/env python
"""QLoRA fine-tuning for the Fenris local model.

Trains a LoRA adapter on the dataset produced by export_dataset.py. Needs a
GPU and the packages in training/requirements-train.txt (kept separate from
the app's requirements.txt — these are heavy and training-only). Unsloth is
a faster drop-in alternative to the PEFT+TRL path used here if you have it
set up; swap the model/trainer construction below if so.

Example:
    python training/train_lora.py --dataset training/dataset.jsonl \\
        --base-model Qwen/Qwen2.5-14B-Instruct --output-dir training/output/fenris-lora
"""
import argparse
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    examples = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True, help="JSONL from export_dataset.py")
    parser.add_argument("--base-model", type=str, default="Qwen/Qwen2.5-14B-Instruct")
    parser.add_argument("--output-dir", type=Path, default=Path("training") / "output" / "fenris-lora")
    parser.add_argument("--rank", type=int, default=16, help="LoRA rank")
    parser.add_argument("--alpha", type=int, default=32, help="LoRA alpha")
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--max-seq-length", type=int, default=4096)
    args = parser.parse_args()

    if not args.dataset.exists():
        raise SystemExit(f"Dataset not found: {args.dataset}. Run export_dataset.py first.")

    examples = load_jsonl(args.dataset)
    if not examples:
        raise SystemExit("Dataset is empty — nothing to train on.")
    print(f"Loaded {len(examples)} training examples from {args.dataset}")

    # Heavy imports deferred so --help and the checks above work without a
    # GPU or these packages installed — only main() actually needs them.
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
        from trl import SFTTrainer
    except ImportError as error:
        raise SystemExit(
            "Missing training dependencies. Run: pip install -r training/requirements-train.txt\n"
            f"({error})"
        ) from error

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        load_in_4bit=True,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )

    lora_config = LoraConfig(
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    def format_example(example: dict) -> dict:
        return {"text": tokenizer.apply_chat_template(example["messages"], tokenize=False)}

    dataset = Dataset.from_list(examples).map(format_example)

    # NOTE: TRL's SFTTrainer argument surface has moved around across
    # versions (some want dataset_text_field/max_seq_length here, newer ones
    # want them on an SFTConfig instead) — adjust for whatever version
    # requirements-train.txt resolves to if this errors.
    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        logging_steps=10,
        save_strategy="epoch",
        bf16=True,
        report_to=[],
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
    )
    trainer.train()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    trainer.model.save_pretrained(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))
    print(f"LoRA adapter saved to {args.output_dir}")
    print(f"Next: python training/merge_and_export.py --base-model {args.base_model} --adapter {args.output_dir}")


if __name__ == "__main__":
    main()
