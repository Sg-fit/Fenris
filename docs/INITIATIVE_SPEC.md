# Fenris — Initiative: speaking up on its own from memory

Today Fenris only speaks unprompted when a reminder you explicitly set comes due
(Gap #2). This adds **initiative**: Fenris periodically considers what it knows about
you (facts + recent conversation from Gap #3) and the current time, and *occasionally*
decides there's something worth surfacing on its own — "you mentioned wanting to email
Sam yesterday, still want to?" — then delivers it through the existing proactive voice
loop.

This is the single feature most able to feel magical **and** most able to feel naggy.
So the entire design is biased toward silence: **off by default, defaults to saying
nothing, hard-rate-limited, quiet-hours-respected, opt-in.** Those are acceptance
criteria, not preferences.

Build on what exists; do not regress reminders or the wake-word loop.

---

## Current state (relevant)

- `backend/proactive/store.py` `ProactiveStore`: `reminders` table + `due(owner, now)`
  (atomically marks delivered). The desktop client (`core/proactive.py`) already polls
  `GET /proactive/due` for the current owner and **speaks whatever text it returns**,
  respecting `PROACTIVE_ENABLED` and quiet hours. So anything surfaced through `due`
  is delivered with no client change.
- `backend/memory/semantic.py` `SemanticMemory.facts(owner, limit)` — durable facts.
- `backend/memory/store.py` `MemoryStore.history(owner, None, limit)` — recent messages.
- Providers have `complete(system, user) -> str` (single-shot, no tools) from Gap #3.
- `backend/main.py`: module-level `memory`, `semantic`, `proactive`; `/proactive/due`;
  role helper `can_access_owner`; `AuditLog`. FastAPI app — add a startup hook here.
- `backend/settings.py` + `.env.example` + client `config.py` (quiet hours live there).

---

## A. Initiative store

Extend `ProactiveStore` (or add a sibling `initiatives` table in the same DB — your
call, keep it one class if clean):

```
initiatives(id, owner, text, context_hash, created_at, delivered INTEGER DEFAULT 0)
```
- `add_initiative(owner, text, context_hash) -> int`.
- `due_initiatives(owner, now_iso)` — undelivered, atomically marked delivered (same
  pattern as `due`).
- `recent_initiative_hashes(owner, limit)` and/or `recent_initiative_texts` — for
  dedup, so the same idea isn't raised twice.
- `pending_initiative_count(owner)` — to cap how many can stack undelivered.
- Include initiatives in `clear(owner)` so "forget me" wipes them too.

**Merge into delivery:** `GET /proactive/due` should return reminders **and** due
initiatives together (each tagged with a `type`: `"reminder"` | `"initiative"`), both
marked delivered. The client already speaks `text`; optionally it can use a softer
lead-in for `type == "initiative"` ("By the way — …") vs reminders ("Reminder — …") —
minor, optional.

## B. The consideration loop (backend)

A daemon thread started from a FastAPI startup hook in `main.py`. Every
`Settings.INITIATIVE_INTERVAL` (default long — see D), for each **known owner**
(owners that have stored facts/memory; never guests):

1. **Rate-limit gate:** skip this owner unless it's been at least
   `INITIATIVE_MIN_HOURS` since their last consideration (track last-considered time
   per owner, in-memory is fine). Skip if `pending_initiative_count(owner)` already
   at `INITIATIVE_MAX_PENDING` (don't stack).
2. **Build context:** the owner's `semantic.facts(owner)` + a small slice of
   `memory.history(owner, None, N)` + `Current time: …`.
3. **Ask the model** via `provider.complete(system, user)` with a prompt that is
   heavily biased to silence:
   > "Given what you know about {name} and the current time, is there ONE genuinely
   > useful thing worth proactively bringing up right now — an unfinished intention
   > they mentioned, a time-sensitive follow-up, something they'd thank you for
   > remembering? Only if it clears a high bar. If there's any doubt, or it's just
   > filler, reply exactly NONE. Otherwise reply with one short spoken sentence."
4. If the reply is `NONE`/empty → do nothing. Otherwise compute a `context_hash`
   (e.g. hash of the normalized suggestion), **skip if it matches a recent
   initiative** (dedup), else `add_initiative(...)` and audit `initiative_created`.

Which provider to use: construct one via `get_provider_class()` with no tool_runner
(a plain completion). Wrap the whole per-owner step so one failure never kills the
thread or affects requests. The loop must be a no-op when `Settings.INITIATIVE` is
false (don't even start the thread).

Note "known owners": derive from distinct owners in the facts/memory tables. Fine to
query once per loop iteration.

## C. Delivery (client) — mostly free

Because `/proactive/due` now includes initiatives, the existing `core/proactive.py`
loop already speaks them, already respects quiet hours and `PROACTIVE_ENABLED`, and
already only polls for the recognized owner. The only optional change is the softer
lead-in by `type` (B/A above). Confirm no double-speak / overlap regressions with the
turn-active guard from Gap #2.

## D. Settings

Backend (`backend/settings.py` + `.env.example`):
```
INITIATIVE            = env bool, default FALSE   # the whole feature, opt-in
INITIATIVE_INTERVAL   = seconds between loop ticks, default 1800
INITIATIVE_MIN_HOURS  = min hours between considerations per owner, default 4
INITIATIVE_MAX_PENDING= max undelivered initiatives per owner, default 1
INITIATIVE_HISTORY_N  = recent messages to include as context, default 20
```
Document in `.env.example` that this is the "Fenris brings things up on its own"
feature, off by default, and that quiet hours (client `PROACTIVE_QUIET_*`) also gate
when initiatives are spoken. Add a short README section.

## E. Tests (`tests/`)

- Store: `add_initiative` + `due_initiatives` (undelivered past → returned once, then
  marked delivered); dedup via `recent_initiative_hashes`; `pending_initiative_count`;
  `clear` wipes initiatives.
- Generation step with a fake `complete`: a real suggestion → stored; `NONE`/empty →
  nothing stored; a suggestion whose hash matches a recent one → skipped.
- Rate-limit: a second consideration within `INITIATIVE_MIN_HOURS` is skipped; the
  max-pending cap blocks new ones.
- `/proactive/due` returns reminders + initiatives together, each `type`-tagged, both
  marked delivered (no re-delivery on a second poll).
- Off by default: `INITIATIVE=false` → loop/thread does nothing, no initiatives ever.
- Guests excluded; per-owner isolation.

Pass timestamps/clock explicitly into tests for determinism.

## F. Acceptance criteria

- With `FENRIS_INITIATIVE=false` (default), behavior is exactly as today — no thread
  effects, no unprompted speech beyond explicit reminders.
- With it on: over time Fenris occasionally surfaces a genuinely relevant, memory-
  grounded suggestion through the existing voice loop — never more than
  `INITIATIVE_MAX_PENDING` pending, never more often than `INITIATIVE_MIN_HOURS` per
  person, never in quiet hours, never to guests, never the same idea twice.
- The model defaults to `NONE` — a run of empty considerations produces silence, not
  filler.
- All existing tests still pass; new tests pass.

## G. Note

This is the internal-only version (memory + time). Once calendar/email integrations
exist later, the same consideration loop can factor in real events ("your 3pm moved")
— but that's out of scope here; keep this grounded purely in stored memory and time.
