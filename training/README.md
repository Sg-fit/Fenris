# Fine-tuning Fenris

Goal: make the local model consistently sound like Fenris — the tone rules in
`backend/brain/prompt.py` reinforced by example, not just instruction. This is
a scaffold: the scripts here work end-to-end, but actually training something
worth using needs real usage data and a GPU. **Use Fenris on the local model
for a while first, on real conversations, then come back here and tune on the
specific weaknesses you actually hit** — not before you have any.

## What this dataset can and can't teach

`MemoryStore` (`data/fenris_memory.sqlite3`) stores only final message
text — the user's words and Fenris's spoken reply — not the tool-call trace
that produced that reply. So `export_dataset.py` produces a dataset that
teaches **voice and conversational style**: how Fenris should sound, how it
should phrase things, what a good answer looks like. It does **not** teach
**tool-use reliability** — when to call `browser_actions` vs. `read_page`,
how to recover from a bad selector, when to ask vs. proceed. Improving that
would need tool-call traces logged first (a separate change, out of scope
here), then training on those. Don't expect this pipeline to fix tool-calling
mistakes; it's for personality and tone.

## Pipeline

```
export_dataset.py  →  train_lora.py  →  merge_and_export.py  →  ollama create
   (SQLite → JSONL)      (QLoRA adapter)      (merge + GGUF)      (register + use)
```

### 1. Export a dataset

```powershell
python training/export_dataset.py --min-turns 3 --out training/dataset.jsonl
```

- `--owner NAME` — only that person's conversations, if you want to tune on
  one person's style specifically rather than everyone Fenris has talked to.
- `--min-turns N` — drop short/thin sessions; quality and consistency beat
  quantity here. A few hundred strong examples beats thousands of noisy ones.
- `--dry-run` — print how many sessions/examples would be produced without
  writing anything, useful to sanity-check before committing to a run.

Each line of the output is one training example:
`{"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}, ...]}`,
using the exact same `SYSTEM_PROMPT` Fenris runs with today.

### 2. Train a LoRA adapter

Needs a GPU and `pip install -r training/requirements-train.txt` (kept
separate from the app's `requirements.txt` — these are heavy, training-only,
and not needed on whatever machine actually runs Fenris day to day).

```bash
python training/train_lora.py \
    --dataset training/dataset.jsonl \
    --base-model Qwen/Qwen2.5-14B-Instruct \
    --output-dir training/output/fenris-lora
```

QLoRA via PEFT + TRL's `SFTTrainer`, 4-bit base weights — fits a 24 GB card
for 7–14B models. [Unsloth](https://github.com/unslothai/unsloth) is a faster
drop-in alternative if you have it set up; swap the model/trainer
construction in `train_lora.py` if so. Key flags: `--rank`, `--alpha`,
`--epochs`, `--lr`, `--batch-size` / `--grad-accum` (raise grad-accum if you
have to drop batch size for VRAM). Output is a LoRA adapter directory, not a
full model.

No local GPU? Rent one by the hour (A100/H100) and run the same script there.

### 3. Merge and export for Ollama

```bash
python training/merge_and_export.py \
    --base-model Qwen/Qwen2.5-14B-Instruct \
    --adapter training/output/fenris-lora \
    --llama-cpp-convert ~/llama.cpp/convert_hf_to_gguf.py
```

Merges the adapter into the base model, converts to GGUF via
[llama.cpp](https://github.com/ggml-org/llama.cpp)'s convert script (clone it
separately; point `--llama-cpp-convert` at `convert_hf_to_gguf.py` inside
it), and writes an Ollama `Modelfile`. Omit `--llama-cpp-convert` to stop
after the merge and get a plain Hugging Face model directory instead.

### 4. Register and point Fenris at it

The script prints the exact command, but it's:

```bash
cd training/output
ollama create fenris-local -f Modelfile
```

Then in `.env`:

```ini
FENRIS_LOCAL_MODEL=fenris-local
```

Restart the backend. **No provider code changes** — that's the entire point
of having built the local provider (`backend/brain/local.py`) against a
plain model name in the first place.
