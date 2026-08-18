# Fenris — Gap #2: Proactivity (initiative, reminders, speaking unprompted)

Today Fenris only acts when it hears the wake word — it never speaks first. This
adds the **engine** for initiative: durable scheduled items, a tool the model uses
to set them, and a background delivery loop in the desktop client that speaks them
unprompted when they come due. Monitoring external sources (calendar/email/files)
is deliberately **out of scope** here — that arrives with Gap #1's integrations.
This is the mechanism those will later plug into.

Build on what exists; do not regress the wake-word loop or any current behavior.

---

## Current state (relevant facts)

- **Client** `core/assistant.py`: `run()` is a blocking loop — publishes HUD state,
  `listener.capture()`, `transcribe()`, dispatches turns. Voice out is
  `self.speaker.speak(text)` (`voice/speaker.py`); HUD updates via
  `self.hud.publish({...})` and `self.hud.url`. The recognized person is tracked in
  `self._last_speaker` (an `Identity` with `.name`/`.role`); `_typed_identity()`
  resolves the owner fallback (`_last_speaker` → `Config.OWNER_NAME` → first admin →
  `"owner"`). Turns run on background workers (`_dispatch` / `_run_converse`).
- **Backend** `backend/main.py`: FastAPI. Model tools are declared in
  `backend/brain/tools.py` (shared `TOOLS`) and dispatched by `_make_tool_runner`
  in `main.py` via the `_TOOL_ADDONS` map. Per-person data lives in
  `data/fenris_memory.sqlite3`; there's an `AuditLog` (`backend/audit.py`) and
  role checks (`guest`/`user`/`admin`).
- **Providers** take the system prompt internally; a `memory_context` string is
  already appended per request (from Gap #3). Reuse that mechanism to also give the
  model the current time (see B4) so it can schedule absolute times.

---

## A. Backend — scheduled items store + endpoints

### A1. `backend/proactive/store.py` (`ProactiveStore`)

Same SQLite DB as the memory stores (`DATABASE_PATH`, create table if absent,
same style). Table:

```
reminders(id, owner, fire_at TEXT /*ISO 8601 UTC*/, text, created_session,
          delivered INTEGER NOT NULL DEFAULT 0, created_at)
index on (owner, delivered, fire_at)
```

Methods:
- `add(owner, fire_at_iso, text, created_session) -> int` (returns id).
- `due(owner, now_iso) -> list[dict]` — return undelivered reminders with
  `fire_at <= now`, **and atomically mark them delivered in the same transaction**
  so a second poll never re-delivers them. Return `{id, text, fire_at}`.
- `pending(owner) -> list[dict]` — upcoming undelivered (for "what reminders do I
  have").
- `cancel(owner, reminder_id) -> bool`.
- `clear(owner)` — delete this owner's reminders (wire into the existing
  `DELETE /memory/{owner}` handler alongside `semantic.clear`, so "forget me"
  removes reminders too).

All times stored/compared as ISO 8601 UTC. Strict per-`owner` isolation.

### A2. Endpoints (`backend/main.py`)

- `POST /proactive/reminders` — body `{actor_name, actor_role, session_id, text,
  when}` where `when` is either an ISO 8601 timestamp **or** `{"in_minutes": N}`.
  Resolve to `fire_at` UTC. Reject `guest` (403). Audit `reminder_created`.
- `GET /proactive/due?owner=&actor_name=&actor_role=&now=` — role check via the
  existing `can_access_owner`; `now` optional (defaults to server now, UTC).
  Returns due items (already marked delivered by the store). Audit is optional here
  to avoid noise — a delivered-count is fine.
- `GET /proactive/reminders?owner=&actor_name=&actor_role=` — pending list.
- `DELETE /proactive/reminders/{id}?owner=&actor_name=&actor_role=` — cancel;
  audit `reminder_cancelled`.

Instantiate one module-level `ProactiveStore` next to `memory`/`semantic`.

### A3. Model tools (`backend/brain/tools.py` + dispatch)

Add three tools to the shared `TOOLS` list (so both providers get them via the
existing schema converter):
- `set_reminder` — `{text: str, when: str|null, in_minutes: int|null}`. Exactly one
  of `when`/`in_minutes`. Description tells the model: use `in_minutes` for relative
  ("in 20 minutes"), `when` (ISO, using the current time you were given) for
  absolute ("tomorrow 9am").
- `list_reminders` — no args.
- `cancel_reminder` — `{reminder_id: int}` (ids come from `list_reminders`).

These are **not** add-ons, so don't route them through `_TOOL_ADDONS`. Extend the
tool runner so `main.py` handles them directly against `ProactiveStore` for the
current `actor_name`/`actor_role`/`session_id` (guests: return a friendly "reminders
need an enrolled profile" error result, never raise). Keep the add-on tools working
exactly as before.

### A4. Give the model the current time

So it can schedule absolute times, prepend a line like
`Current time: <ISO local + tz>` to the per-request system context (either fold it
into the existing `memory_context` assembly in `/chat`, or add a tiny
`time_context` appended the same way). Must be present even for guests (who can read
time but can't set reminders). With this, `set_reminder(when=...)` is unambiguous.

---

## B. Client — background proactive delivery

### B1. `ProactiveDelivery` (new, e.g. `core/proactive.py` or inside `assistant.py`)

A daemon thread started from `Assistant.run()` (or `__init__`) that, every
`Config.PROACTIVE_POLL_SECONDS`:
1. Skips entirely if `not Config.PROACTIVE_ENABLED`.
2. Determines the owner to poll for — reuse `_typed_identity()` (recognized person,
   else `OWNER_NAME`, else admin). Never polls for a guest.
3. Skips if within quiet hours (`Config.PROACTIVE_QUIET_START/END`).
4. Skips if a turn is currently active or Fenris is mid-speech (see B3) — proactive
   messages must never talk over the user or an in-progress reply.
5. `GET /proactive/due` for that owner; for each due item, publish a HUD state and
   `self.speaker.speak(...)` it (a short lead-in like "Reminder — " is fine). Set
   HUD state back to sleeping/listening afterward.

Poll failures (backend down) are swallowed and retried next tick — never crash the
thread. Add a `Brain`-side helper (`core/brain.py`) for these calls, mirroring the
existing `memory_history`/`clear_memory` request helpers, rather than calling
`requests` from the assistant directly.

### B2. Config (`config.py`) + `.env.example`

```
PROACTIVE_ENABLED       (default true)
PROACTIVE_POLL_SECONDS  (default 30)
PROACTIVE_QUIET_START   (default "22:00")   # local HH:MM; no proactive speech
PROACTIVE_QUIET_END     (default "08:00")
```

### B3. Don't talk over anything — serialization

`self.speaker.speak()` is called from the main loop, mission workers, and now the
proactive thread. Ensure speech can't overlap:
- Add a lock inside `Speaker` (`voice/speaker.py`) so concurrent `speak()` calls
  serialize (inspect the file; if it already serializes, note that and skip).
- Track "a turn is in progress" on the `Assistant` (set around `_run_converse`
  and while capturing/handling) and have `ProactiveDelivery` check it (B1 step 4)
  so reminders wait for a natural gap instead of interrupting.

### B4. HUD (optional, nice-to-have)

If quick: a distinct HUD state/animation for a proactive message so the orb signals
"Fenris spoke on its own." Not required for acceptance.

---

## C. Optional stretch — initiative generation (off by default)

A periodic backend consideration that, from the person's facts/recent memory
(Gap #3) plus the current time, decides whether there's something worth saying
unprompted ("you meant to email Sam yesterday — still want to?") and, if so, queues
it as a proactive item. Gate behind `FENRIS_INITIATIVE=false` by default, and
rate-limit hard (at most once per N hours per person) so it's never naggy. Ship the
reminders engine first; treat this as a follow-up only if time allows.

---

## D. Tests (`tests/`)

- `ProactiveStore`: `add` + `due` returns only past-due undelivered and marks them
  delivered (a second `due` call returns nothing); `pending` excludes delivered;
  `cancel`; per-owner isolation; `clear` empties the owner.
- `when` resolution: `in_minutes` → correct `fire_at`; absolute ISO accepted;
  rejecting both/neither.
- Tool dispatch: `set_reminder` creates a row for the actor; guest → error result,
  no row; `list_reminders`/`cancel_reminder` behave.
- `/proactive/due` role checks: guest denied; owner/admin allowed.
- `ProactiveDelivery` with a fake brain + fake speaker/clock: a due item is spoken;
  quiet hours suppress; an active-turn flag suppresses; backend error is swallowed.

Pass timestamps explicitly into store/tests (don't rely on wall-clock) so tests are
deterministic.

---

## E. Acceptance criteria

- With `PROACTIVE_ENABLED=false`, behavior is identical to today (no extra thread
  effects, wake loop unchanged).
- With it on: saying "remind me in 2 minutes to stretch" causes Fenris to speak that
  reminder ~2 minutes later, unprompted, without the wake word — and it is not
  repeated on the next poll. "What reminders do I have?" lists pending ones; cancel
  works. Guests can't set or receive reminders. Quiet hours suppress speech.
  Proactive speech never overlaps an in-progress reply.
- `DELETE /memory/{owner}` also clears that person's reminders.
- New tests pass; all existing tests still pass.
