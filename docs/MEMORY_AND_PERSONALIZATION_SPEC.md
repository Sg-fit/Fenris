# Fenris — Gap #3: Long-term memory, personalization, and making the model yours

Two parts. **Part A (build now):** give Fenris durable, cross-session memory of each
person — distilled facts plus semantic recall — injected into context so it
remembers you, not just the last transcript. **Part B (scaffold now, run later):**
a LoRA fine-tuning pipeline so the local model takes on a consistent personality.

Part A is the required, testable build. Part B is a scaffold with clear TODOs; it
depends on having usage data and a GPU, so it is not part of Part A's acceptance.

---

## Current state (what exists)

- `backend/memory/store.py` `MemoryStore`: SQLite at `data/fenris_memory.sqlite3`,
  one `messages` table `(owner, role, content, session_id, created_at)`. Methods:
  `add`, `history(owner, query, limit)` (LIKE search), `last_session`, `clear`.
- `backend/main.py` `/chat`: after streaming, for non-guests it calls
  `memory.add(...)` for the user and assistant turns. **Nothing from memory is
  injected back into the model's context** — that's the core gap.
- Both providers (`backend/brain/claude.py`, `local.py`) take `SYSTEM_PROMPT`
  internally in `stream_reply` and do not accept any extra per-request context.
- Roles: `guest` / `user` / `admin`. Guests are never persisted. There is an
  `AuditLog` (`backend/audit.py`) and admin-only memory endpoints.

---

## Part A — Semantic long-term memory + user profile

### A1. New module `backend/memory/semantic.py` (`SemanticMemory`)

Owns durable facts and vector recall, in the **same** SQLite DB as `MemoryStore`
(pass the same `database_path`; create tables if absent, same migration style):

```
mem_facts(id, owner, text, source_session, created_at, UNIQUE(owner, text))
mem_embeddings(id, owner, kind, ref_id, text, vector BLOB, created_at)
```
- `kind` is `'message'` or `'fact'`; `ref_id` links back to the source row.
- Store vectors as `float32` bytes (`numpy.ndarray.tobytes()`); `numpy` is already
  a dependency.

Embeddings via an **OpenAI-compatible embeddings endpoint** (reuse the `openai`
client). Default to Ollama's `nomic-embed-text`. Methods:

- `embed(texts: list[str]) -> list[np.ndarray]` — one `client.embeddings.create`
  call; returns unit-normalized vectors. **Fail-soft**: if the endpoint is
  unreachable, log once and return `None`/empty so callers degrade to "no
  semantic memory" rather than erroring.
- `index_message(owner, ref_id, text)` / `index_fact(owner, ref_id, text)` — embed
  and upsert into `mem_embeddings`.
- `remember_fact(owner, text, source_session) -> bool` — insert into `mem_facts`
  (ignore on UNIQUE conflict); also index it. Return whether it was new.
- `retrieve(owner, query, k, min_score) -> list[dict]` — embed `query`, load that
  owner's vectors, cosine-rank, return top-`k` above `min_score` as
  `{text, kind, score}`. Brute-force numpy cosine is fine at personal scale — do
  **not** pull in a vector DB. If there are zero vectors or embedding failed,
  return `[]`.
- `facts(owner, limit)` — recent distilled facts for the profile block.
- `clear(owner)` — delete this owner's rows from **both** new tables.

Isolation is strict per `owner`. Guests are never indexed and never retrieved.

### A2. New module `backend/memory/extractor.py` (`extract_facts`)

After a real exchange, distill any **durable** facts about the person (preferences,
names, relationships, projects, recurring context) — not transient chit-chat.

- Signature: `extract_facts(complete, user_text, assistant_text) -> list[str]`
  where `complete(system, user) -> str` is a single-shot model call (see A4).
- Use a tight extraction prompt: "Extract only durable facts worth remembering
  long-term about the user, as short standalone statements. If nothing is worth
  keeping, return an empty list." Parse a simple line- or JSON-list response
  defensively.
- **Never raise** into the request path — on any error return `[]`.
- Keep it cheap: cap output tokens, run at most once per turn.

### A3. Wire into `backend/main.py` `/chat`

- **Before** constructing the conversation, for non-guest actors, assemble a
  `memory_context` string:
  - a profile block from `semantic.facts(owner, cap)` ("What you know about
    <name>: ..."), plus
  - `semantic.retrieve(owner, latest_user_message, k, min_score)` snippets
    ("Relevant things from past conversations: ...").
  - Guests → `memory_context = None`. If both are empty → `None`.
- Pass `memory_context` into `provider.stream_reply(...)` (see A4).
- **After** the stream completes, inside the existing `if actor_role != "guest":`
  block (where `memory.add` already runs): also
  `semantic.index_message(...)` the new user and assistant texts, and run
  `extract_facts(...)` → `semantic.remember_fact(...)` for each. All best-effort;
  wrap so a failure never breaks the response or the existing `memory.add`.
- Extend the `DELETE /memory/{owner}` handler to also call `semantic.clear(owner)`
  so "forget me" wipes facts and vectors too. Keep the existing audit record.

### A4. Provider changes (both `claude.py` and `local.py`)

- `stream_reply(self, conversation, on_event, resume_answer=None, memory_context=None)`.
  When `memory_context` is set, append it to the system prompt:
  - Claude: `system=SYSTEM_PROMPT + "\n\n" + memory_context`.
  - Local: the leading `{"role":"system", ...}` content becomes
    `SYSTEM_PROMPT + "\n\n" + memory_context`.
  Behaviour with `memory_context=None` must be byte-for-byte what it is today.
- Add a small single-shot helper used by the extractor, no tools, low `max_tokens`:
  - Claude: `complete(self, system, user) -> str` via `messages.create`.
  - Local: `complete(self, system, user) -> str` via `chat.completions.create`.
  `main.py` passes `provider.complete` into `extract_facts`.

### A5. Settings (`backend/settings.py`) — add

```python
SEMANTIC_MEMORY   = os.getenv("FENRIS_SEMANTIC_MEMORY", "true").lower() in {"1","true","yes","on"}
EMBED_BASE_URL    = os.getenv("FENRIS_EMBED_BASE_URL", LOCAL_BASE_URL)  # reuse local by default
EMBED_MODEL       = os.getenv("FENRIS_EMBED_MODEL", "nomic-embed-text")
EMBED_API_KEY     = os.getenv("FENRIS_EMBED_API_KEY", LOCAL_API_KEY)
MEMORY_TOPK       = int(os.getenv("FENRIS_MEMORY_TOPK", "6"))
MEMORY_MIN_SCORE  = float(os.getenv("FENRIS_MEMORY_MIN_SCORE", "0.35"))
MEMORY_FACT_CAP   = int(os.getenv("FENRIS_MEMORY_FACT_CAP", "40"))
```
When `SEMANTIC_MEMORY` is false, `/chat` skips all of the above and behaves exactly
as today. Mirror the new vars in `.env.example`, and add a "Long-term memory"
section to `README.md`: what it does, that it needs an embeddings endpoint (Ollama
`ollama pull nomic-embed-text` is the easy path), that it's per-person and
guest-excluded, and that `DELETE /memory/{owner}` now clears facts + vectors too.

### A6. Requirements

`numpy` and `openai` are already present — no new deps expected. If you reach for
anything else, justify it; prefer stdlib + numpy.

### A7. Tests (`tests/`)

- `retrieve` ranking with an **injected deterministic embedder** (no live server):
  closest text ranks first; `min_score` filters; empty store → `[]`.
- `remember_fact` dedups on `(owner, text)`; `clear(owner)` empties both new tables.
- `extract_facts` with a fake `complete`: returns parsed facts on good output,
  `[]` on malformed output, and never raises.
- `memory_context` assembly: guest → `None`; a user with facts+hits → a non-empty
  block containing them.
- Both providers append `memory_context` to the system prompt (fake clients);
  with `memory_context=None`, the outgoing system content equals today's.
- Fail-soft: with the embed endpoint unreachable, `/chat`'s memory calls no-op and
  the turn still returns a normal result (simulate by pointing embed at a dead URL
  or injecting a raising embedder).

### A8. Acceptance criteria (Part A)

- With `FENRIS_SEMANTIC_MEMORY=false`, behaviour is identical to today.
- With it on and an embeddings endpoint up: facts stated in one session surface in
  a later session's context; semantically related past messages are retrieved even
  without keyword overlap; guests get nothing stored or recalled;
  `DELETE /memory/{owner}` wipes messages, facts, and vectors.
- Embeddings endpoint down → chat still works, just without memory (logged once).
- New tests pass; existing tests still pass.

---

## Part B — LoRA fine-tuning pipeline (scaffold now, run later)

Goal: make the **local** model consistently sound like Fenris. Scaffold under a new
`training/` dir with working scripts and a README; actually running it needs
collected data + a GPU, so this is not gated by Part A's acceptance.

Honest limitation to note in the README: `MemoryStore` stores only final message
text, not tool-call traces — so this dataset teaches **voice and style**, not tool
use. Tool reliability is improved separately (more/better examples of tool calls
would need to be logged first; out of scope here).

1. `training/export_dataset.py` — read `data/fenris_memory.sqlite3`, group by
   `(owner, session_id)`, emit chat-format JSONL (`{"messages":[{system},{user},
   {assistant},...]}`) using the shared `SYSTEM_PROMPT`. Flags: `--owner`,
   `--min-turns`, `--out`. Basic quality filtering (drop empty/degenerate turns).
2. `training/train_lora.py` — QLoRA on the base model (default Qwen2.5-7B/14B) with
   Unsloth or PEFT+TRL `SFTTrainer`. Config surface: base model, rank, epochs, lr,
   output dir. Emits a LoRA adapter. Include a `requirements-train.txt` (kept
   separate from the app's `requirements.txt`).
3. `training/merge_and_export.py` — merge adapter into the base, export GGUF, write
   an Ollama `Modelfile` (`FROM ./fenris-merged.gguf`), and print the
   `ollama create fenris-local -f Modelfile` command. Then the user sets
   `FENRIS_LOCAL_MODEL=fenris-local` — no provider code changes (that's the payoff
   of having done the local provider first).
4. `training/README.md` — the end-to-end runbook: export → train → merge → register
   → point Fenris at it, plus the "collect real usage first, tune on real
   weaknesses" guidance and the tool-use limitation above.

Acceptance for Part B is just that the scripts exist, import cleanly, and
`export_dataset.py` runs against the real SQLite DB producing valid JSONL (a
`--dry-run`/tiny-sample smoke test is enough). Training/merging are run by the user
on a GPU later.
