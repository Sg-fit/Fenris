# Fenris — Local / Open-Model Brain Provider (implementation brief)

## Goal

Right now Fenris's brain is the Anthropic cloud API (`backend/brain/claude.py`,
selected implicitly in `backend/main.py`). Add a **second provider** that talks
to a **locally-served open-weight model** over the **OpenAI-compatible chat API**,
selectable with an env var. This lets Fenris run with no cloud key on a model
we own and can later fine-tune (LoRA/QLoRA).

The same provider must work against **Ollama** (local, e.g. a 24 GB GPU) and
**vLLM** (rented cloud GPU) with no code change — only `FENRIS_LOCAL_BASE_URL`
differs. Both expose the OpenAI `/v1/chat/completions` schema.

Do **not** remove or break the existing `ClaudeProvider`. It stays the default.

## Non-goals

- No pretraining from scratch. Fine-tuning comes later (see last section).
- No new UI. The desktop client and HUD are untouched — this is backend-only.

## The interface the new provider must match

`backend/main.py` `/chat` uses the provider through exactly this surface, so the
new class must be a drop-in for `ClaudeProvider`:

1. `ProviderClass.build_conversation(messages: list[dict], images: list[dict]) -> list[dict]`
   - `messages`: `[{"role": "user"|"assistant", "content": str}, ...]`
   - `images`: `[{"media_type": "image/png|jpeg|gif|webp", "data": <base64>}, ...]`,
     attached to the **most recent user message**.
   - Returns the provider-native conversation list. For the local provider this
     is OpenAI-style message dicts. Do **not** put the system prompt in here —
     add it inside `stream_reply` (mirrors how Claude passes `system=` separately).

2. `ProviderClass(tool_runner=callable)` where
   `tool_runner(tool_name: str, tool_input: dict) -> dict`. When `tool_runner`
   is falsy, run with no tools.

3. `provider.stream_reply(conversation, on_event, resume_answer=None) -> (paused: bool, conversation: list[dict])`
   - Emits events via `on_event(dict)` as work happens. Event contract (unchanged
     from Claude, the client already speaks it):
     - `{"type": "progress", "text": str}` — mid-mission narration, spoken immediately.
     - `{"type": "question", "text": str}` — a blocking `ask_user`; return `paused=True`.
     - `{"type": "result", "text": str}` — terminal answer; return `paused=False`.
     - `{"type": "media", "source", "kind", "location", "caption"}` — emitted when a
       `show_media` tool call succeeds (see Claude provider for the exact shape).
   - **Always** emit at least one terminal `result` (or `question`) event, even if
     the model returns empty text — the client must never get zero events.
   - `paused=True` means the run stopped on a dangling `ask_user`, to be resumed
     next turn with `resume_answer` set. `main.py` stores/reloads the returned
     `conversation` via `MissionStore` (in-memory; any structure is fine).
   - Cap the tool loop at `MAX_STEPS = 25`, same as Claude.

The `resume_answer` path: when set, the last assistant turn contained tool
call(s) including `ask_user`; feed the user's answer back as that tool's result,
run any *other* pending tool calls for real, then continue the loop. (Mirror
`ClaudeProvider._resolve_pending`, but using OpenAI `tool_calls` / `tool` role
messages instead of Anthropic content blocks.)

## Tool + prompt reuse

- Reuse the **exact `SYSTEM_PROMPT`** string from `backend/brain/claude.py`.
  Factor it out into `backend/brain/prompt.py` (a `SYSTEM_PROMPT` constant) and
  import it into both providers so they never drift. Do not fork the wording.
- The 7 tools (`web_search`, `read_page`, `browser_actions`, `ask_user`,
  `show_media`, `list_local_files`, `read_local_file`) are defined in Anthropic
  schema (`name`, `description`, `input_schema`). Write a small converter to
  OpenAI tool schema:
  `{"type": "function", "function": {"name", "description", "parameters": <input_schema>}}`.
  The JSON Schema body is identical, so a one-function transform over the shared
  `TOOLS` list is enough. Keep a single source of `TOOLS` (move it to
  `backend/brain/tools.py` and import in both providers).
- `ask_user` semantics must match: if the model emits an `ask_user` tool call,
  emit a `question` event and return `paused=True` **without** executing it as a
  normal tool.
- `show_media`: on a successful call, emit the `media` event (copy the mapping
  from Claude's loop) in addition to returning the tool result.

## OpenAI-compatible specifics

- Client: `from openai import OpenAI` → `OpenAI(base_url=Settings.LOCAL_BASE_URL, api_key=Settings.LOCAL_API_KEY)`.
  Ollama accepts any non-empty key; vLLM uses whatever it was launched with.
- Request: `client.chat.completions.create(model=Settings.LOCAL_MODEL, messages=..., tools=..., tool_choice="auto", max_tokens=Settings.LOCAL_MAX_TOKENS)`.
- Message shapes:
  - system: `{"role": "system", "content": SYSTEM_PROMPT}` as the first message.
  - assistant tool call turn: append the returned assistant message including its
    `tool_calls` verbatim.
  - tool result: `{"role": "tool", "tool_call_id": <id>, "content": <json string>}`.
- Reading a response: `choice = resp.choices[0]`. If `choice.message.tool_calls`
  is empty/None → terminal, emit `result` with `choice.message.content`. Else run
  each tool call: `tc.function.name`, `json.loads(tc.function.arguments or "{}")`.
  Guard `json.loads` with try/except (local models sometimes emit malformed args)
  and on failure return a tool_result describing the error so the model can retry.
- Any interim `choice.message.content` alongside tool calls → emit as a
  `progress` event (same as Claude), so narration still reaches the user.
- Images (vision models only): attach to the last user message as OpenAI content
  parts: `{"type": "image_url", "image_url": {"url": "data:<media_type>;base64,<data>"}}`.
  If the configured model has no vision, images can be dropped with a logged note;
  don't crash.
- Truncate each tool_result JSON to ~8000 chars, matching Claude.

## Provider selection

- Add `backend/brain/factory.py` with `get_provider_class()` that returns
  `ClaudeProvider` or `LocalProvider` based on `Settings.BRAIN_PROVIDER`.
- In `backend/main.py` `/chat`, replace the two hardcoded `ClaudeProvider`
  references (the `build_conversation` call and the `ClaudeProvider(...)`
  construction) with the class from the factory. Keep the `RuntimeError → 503`
  handling — the local provider should raise `RuntimeError` with a clear message
  if it can't reach `LOCAL_BASE_URL`.
- Update `GET /health` to report the active provider instead of the hardcoded
  `"anthropic"`.

## Settings (`backend/settings.py`) — add

```python
BRAIN_PROVIDER  = os.getenv("FENRIS_BRAIN_PROVIDER", "anthropic").lower()  # "anthropic" | "local"
LOCAL_BASE_URL  = os.getenv("FENRIS_LOCAL_BASE_URL", "http://127.0.0.1:11434/v1")  # Ollama default; vLLM ~ :8000/v1
LOCAL_MODEL     = os.getenv("FENRIS_LOCAL_MODEL", "qwen2.5:14b-instruct")
LOCAL_API_KEY   = os.getenv("FENRIS_LOCAL_API_KEY", "ollama")  # placeholder; Ollama ignores it
LOCAL_MAX_TOKENS = int(os.getenv("FENRIS_LOCAL_MAX_TOKENS", "1024"))
```

Mirror these in `.env.example` with short comments, and add a "Local model
brain" section to `README.md` (parallel to the existing "Claude backend" one)
covering: set `FENRIS_BRAIN_PROVIDER=local`, install/run Ollama, pull the model,
start the backend, done — no cloud key needed.

## Dependencies

`requirements.txt` is currently empty. At minimum add `openai>=1.0`. (While
you're there, it's worth pinning the deps the project already imports —
`anthropic`, `fastapi`, `uvicorn`, `pydantic`, `requests`, `python-dotenv`,
`playwright` — but that's optional and separate from this task.)

## Running the local model

**Ollama (local, e.g. 24 GB GPU):**
```
# install Ollama, then:
ollama pull qwen2.5:14b-instruct     # or qwen2.5:7b-instruct on tighter VRAM
ollama serve                          # exposes http://127.0.0.1:11434/v1
```
Set `FENRIS_BRAIN_PROVIDER=local`, leave `FENRIS_LOCAL_BASE_URL` default, run the
backend as usual.

**vLLM (rented cloud GPU), same provider:**
```
pip install vllm
python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-14B-Instruct --port 8000
```
Set `FENRIS_LOCAL_BASE_URL=http://<host>:8000/v1` and
`FENRIS_LOCAL_MODEL=Qwen/Qwen2.5-14B-Instruct`. Nothing else changes.

**Model choice:** pick a model with real tool/function-calling support — Fenris
is useless without it. Qwen2.5-Instruct (7B/14B) and Llama-3.1-8B-Instruct are
solid starting points; 14B fits a 24 GB card quantized and is noticeably better
at multi-step tool use than 7B.

## Tests to add / run

Put these under `tests/` alongside the existing tests.

1. **Schema converter unit test:** Anthropic `TOOLS` → OpenAI tools, asserting
   names/descriptions/parameters survive for all 7 tools.
2. **Provider loop test with a fake OpenAI client** (no live model): stub the
   client so the first response returns a `web_search` tool call and the second
   returns final text. Assert: `tool_runner` was invoked with the right args, a
   `result` event fired, `paused=False`.
3. **ask_user pause/resume test (fake client):** first response emits an
   `ask_user` call → assert `paused=True` and a `question` event; then resume with
   `resume_answer` → assert it continues and ends on a `result`.
4. **Empty-final-turn test:** model returns no tool calls and empty content →
   still emits exactly one `result` event.

Manual smoke test with Ollama running:
```
uvicorn backend.main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health          # provider should read "local"
# then run `python main.py` and ask a plain question, a web question, and one
# that should trigger ask_user, confirming voice + HUD still behave.
```

## Acceptance criteria

- `FENRIS_BRAIN_PROVIDER=anthropic` behaves exactly as today (no regressions).
- `FENRIS_BRAIN_PROVIDER=local` with Ollama running answers plain questions,
  uses `web_search`/`read_page`, gates `browser_actions` on confirmation, and
  pauses/resumes on `ask_user` — all through the same `/chat` event stream.
- System prompt and tool list are shared (single source), not duplicated.
- New tests pass; existing tests still pass.

---

## Later: fine-tuning the model you now own (out of scope for this task)

Once the local provider works, this is the tuning path — do it *after* you've
used Fenris on the local model and collected real examples of where it's weak:

1. **Dataset:** export conversations from `data/fenris_memory.sqlite3` and turn
   the good ones into chat + tool-call training examples (user turn → ideal
   assistant reply or correct tool call). Quality/consistency over quantity;
   a few hundred strong examples beats thousands of noisy ones.
2. **Train:** LoRA/QLoRA with Unsloth or Axolotl on the same base model
   (Qwen2.5). Fits a 24 GB card for 7–14B; rent an A100/H100 by the hour for
   bigger or faster runs.
3. **Serve the tuned weights:** merge/export to GGUF, register in Ollama with a
   `Modelfile` (`FROM ./your-merged.gguf`), then point `FENRIS_LOCAL_MODEL` at it.
   No provider code changes — that's the payoff of doing the provider first.
