# Building Fenris's training data (style seed + corrected usage)

This is the cheap, high-quality way to build a fine-tuning dataset without paying
for a cloud model. Two sources, combined:

- **Route 3 — style seed:** a small set of hand-written ideal exchanges that
  establish Fenris's voice from day one. Free, fully under your control.
- **Route 1 — corrected real usage:** your actual conversations with the local
  model, where you fix the replies that came out wrong. This is the highest-signal
  data there is, because each example targets a real mistake in your own context.

Everything ends up as chat-format JSONL (`{"messages": [system, user, assistant, …]}`)
using the **same `SYSTEM_PROMPT`** the model uses at runtime, then gets merged into
one file your existing `train_lora.py` consumes.

Key rule: the training target must be *better* than what the model already produces.
So route 1 means your **corrected** replies — never the model's own unedited output
(it learns nothing from imitating itself).

---

## One-time: write your style seed

Edit `training/seed_pairs.json`. It ships with example entries showing the two
formats — replace them with your own (keep ~50–150 that capture the tone you want):

```json
[
  {"user": "what time is it", "assistant": "Just past nine. Anything you want lined up first?"},
  {"turns": [
    ["user", "remind me to call mom"],
    ["assistant", "When — tonight, or tomorrow?"],
    ["user", "tonight at 7"],
    ["assistant", "Done. I'll nudge you at seven."]
  ]}
]
```

- `{"user":..., "assistant":...}` = one input → one ideal reply.
- `{"turns": [[role, text], …]}` = a multi-turn conversation (must start with a
  user turn, alternate, and end with an assistant turn).
- Any entry with a `"_comment"` key is ignored — use it for notes to yourself.

Write the way you actually want Fenris to sound. This set defines the voice, so
quality matters far more than quantity.

## Ongoing: collect corrected real usage

1. Use Fenris day-to-day on the local model (free).
2. When a reply is off, fix it: edit that assistant turn's `content` in
   `data/fenris_memory.sqlite3` to what it *should* have said, so every assistant
   turn in the session is one you'd be happy to train on. (A HUD "correction mode"
   can make this a one-click step later; until then, edit the DB directly.)
3. Only keep exchanges whose corrected answer is genuinely good — curate, don't dump.

---

## The four commands (run from the project root)

```bash
# 1) Build the style seed  -> training/seed.jsonl
python training/build_seed.py

# 2) Export corrected usage -> training/real.jsonl
#    (skip if you don't have real conversations yet)
python training/export_dataset.py --min-turns 1 --out training/real.jsonl

# 3) Merge + shuffle both   -> training/dataset.jsonl
python training/combine_dataset.py

# 4) Train on the combined file
python training/train_lora.py --dataset training/dataset.jsonl \
    --base-model Qwen/Qwen2.5-7B-Instruct --output-dir training/output/fenris-lora
```

Then merge → GGUF → `ollama create` → set `FENRIS_LOCAL_MODEL` (see the top-level
`docs/MEMORY_AND_PERSONALIZATION_SPEC.md` and `merge_and_export.py`). No app code
changes — the local provider just uses the new model.

## Tips

- **Same base model** at train and serve time (tokenizer/chat template must match).
- **Start small**: a couple hundred total examples is plenty for a first pass.
  Retraining is cheap — add more corrections and run again.
- **Let route 1 grow to be the bulk.** The seed bootstraps the voice; your corrected
  real usage is what makes it genuinely yours.
- `combine_dataset.py` dedups and shuffles, and either input file can be missing —
  so you can train on just the seed on day one, then fold in real usage later.
- Heads-up (pre-existing): `train_lora.py` notes that TRL's `SFTTrainer` argument
  surface shifts between versions; if it errors on `dataset_text_field`/
  `max_seq_length`, that's the line to adjust for your installed `trl` version.
