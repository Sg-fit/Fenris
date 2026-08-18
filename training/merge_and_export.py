#!/usr/bin/env python
"""Merge a trained LoRA adapter into its base model, export GGUF, and write
an Ollama Modelfile so the tuned model can be registered and used by Fenris
via FENRIS_LOCAL_MODEL — no provider code changes needed, that's the payoff
of having built the local provider first.

GGUF conversion shells out to llama.cpp's convert script rather than
reimplementing it — point --llama-cpp-convert at your llama.cpp checkout's
convert_hf_to_gguf.py. Without it, this still merges and saves the full HF
model, just skips the GGUF/Ollama step.

Example:
    python training/merge_and_export.py --base-model Qwen/Qwen2.5-14B-Instruct \\
        --adapter training/output/fenris-lora \\
        --llama-cpp-convert ~/llama.cpp/convert_hf_to_gguf.py
"""
import argparse
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-model", type=str, required=True)
    parser.add_argument("--adapter", type=Path, required=True, help="LoRA adapter dir from train_lora.py")
    parser.add_argument("--merged-dir", type=Path, default=Path("training") / "output" / "fenris-merged")
    parser.add_argument("--gguf-out", type=Path, default=Path("training") / "output" / "fenris-merged.gguf")
    parser.add_argument(
        "--llama-cpp-convert",
        type=Path,
        default=None,
        help="Path to llama.cpp's convert_hf_to_gguf.py; GGUF/Ollama step is skipped if omitted",
    )
    parser.add_argument("--quantize", type=str, default="q4_k_m", help="GGUF quantization level")
    parser.add_argument("--ollama-model-name", type=str, default="fenris-local")
    args = parser.parse_args()

    if not args.adapter.exists():
        raise SystemExit(f"Adapter not found: {args.adapter}. Run train_lora.py first.")

    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as error:
        raise SystemExit(
            "Missing training dependencies. Run: pip install -r training/requirements-train.txt\n"
            f"({error})"
        ) from error

    print(f"Loading base model {args.base_model}...")
    base = AutoModelForCausalLM.from_pretrained(args.base_model, torch_dtype=torch.bfloat16, device_map="auto")
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)

    print(f"Merging adapter {args.adapter}...")
    merged = PeftModel.from_pretrained(base, str(args.adapter))
    merged = merged.merge_and_unload()

    args.merged_dir.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(args.merged_dir))
    tokenizer.save_pretrained(str(args.merged_dir))
    print(f"Merged model saved to {args.merged_dir}")

    if not args.llama_cpp_convert:
        print(
            "Skipped GGUF export (--llama-cpp-convert not given). "
            "The merged Hugging Face model above is still usable directly if your server supports it."
        )
        return

    if not args.llama_cpp_convert.exists():
        raise SystemExit(f"llama.cpp convert script not found: {args.llama_cpp_convert}")

    args.gguf_out.parent.mkdir(parents=True, exist_ok=True)
    print("Converting to GGUF...")
    subprocess.run(
        [
            "python",
            str(args.llama_cpp_convert),
            str(args.merged_dir),
            "--outfile",
            str(args.gguf_out),
            "--outtype",
            args.quantize,
        ],
        check=True,
    )
    print(f"GGUF written to {args.gguf_out}")

    modelfile_path = args.gguf_out.parent / "Modelfile"
    modelfile_path.write_text(f"FROM {args.gguf_out.name}\n", encoding="utf-8")
    print(f"Wrote {modelfile_path}")
    print()
    print("Next, register it with Ollama:")
    print(f"  cd {args.gguf_out.parent}")
    print(f"  ollama create {args.ollama_model_name} -f Modelfile")
    print()
    print(f"Then in .env: FENRIS_LOCAL_MODEL={args.ollama_model_name}")


if __name__ == "__main__":
    main()
