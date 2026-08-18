# Fenris

Fenris is a local, voice-first personal assistant prototype. It listens through
your default microphone and speaks through your default Windows voice. Its
desktop client talks to a separate local FastAPI brain service.

## Start it

1. Activate the virtual environment: `\.venv\Scripts\Activate.ps1`
2. Test your microphone and speaker: `python voice_check.py`
3. Run: `python main.py`

Fenris starts asleep: say **"Fenris"** to wake it (for example, "Fenris, what
time is it?"). It stays awake for follow-up questions for 45 seconds after each
exchange, then goes back to standby; say `go to sleep` to send it back early.
While asleep, speech without the wake word is ignored and never sent anywhere.
Set `WAKE_WORD_ENABLED=false` in `.env` to make it respond to everything.

Say `help` for local commands. Say `clear memory` to erase the current-session
conversation, or `goodbye` to exit.

## Typing and file uploads

Besides speaking, you can type to Fenris directly in the HUD and attach files
with the 📎 button. Images are sent to Fenris's vision so it can describe or
reason about them; PDFs, Word documents, and text files have their text pulled
in automatically. Typed messages and uploads skip the wake word. They are
credited to whoever last spoke this session, or to `OWNER_NAME` from `.env`
before any voice is recognized — set that to your enrolled profile name so your
typed and spoken history stay together.

## Neural voice and visual HUD

Fenris speaks with a free Microsoft neural voice (edge-tts, internet required)
and falls back to the offline Windows voice automatically. Set
`TTS_ENGINE=offline` in `.env` to skip the neural voice, or pick another voice
with `EDGE_VOICE` (list them with `edge-tts --list-voices`).

Starting `python main.py` also opens a local HUD at `http://127.0.0.1:8765`:
an animated orb that reacts to standby, listening, thinking, and speaking,
with a live conversation transcript. It is served only on your machine. Set
`HUD_ENABLED=false` to turn it off, or `HUD_AUTO_OPEN=false` to stop the
browser from opening automatically.

## Voice settings

By default, speech-to-text uses Google's free recognizer, which needs an
internet connection but no API key. To use the local Whisper option instead,
add these lines to `.env`:

```ini
VOICE_INPUT_MODE=whisper
WHISPER_MODEL=base
```

Whisper downloads its selected model the first time it runs. `base` is a good
quality/speed starting point. `python voice_check.py` lists microphone indexes
and Windows voices; optionally set `MICROPHONE_INDEX=1` or `VOICE_NAME=Zira`.

## Claude backend and online AI mode

The desktop voice app never calls a model provider directly. Instead it calls
the local backend at `http://127.0.0.1:8000`, which owns model selection and
provider keys. Copy `.env.example` to `.env` if needed, then add your Anthropic
key:

```ini
ASSISTANT_MODE=auto
ANTHROPIC_API_KEY=your_key_here
```

Install the backend dependencies once, then run these in separate terminals:

```powershell
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
python main.py
```

The backend exposes `GET /health` and `POST /chat` behind a provider-agnostic
interface — see the next section for the other provider that lives behind the
same API. Set `ASSISTANT_MODE=offline` any time you want the local, key-free
version instead.

## Local model brain

Fenris can also run entirely on a model you host yourself — no Anthropic key,
no cloud call — via any server that speaks the OpenAI-compatible chat API
(Ollama or vLLM; the same provider code works against both, only the URL
changes). `GET /health` reports which brain is active.

**Ollama** (simplest, runs on your own GPU):

```powershell
# install Ollama, then:
ollama pull qwen2.5:14b-instruct
ollama serve
```

Set in `.env`:

```ini
FENRIS_BRAIN_PROVIDER=local
FENRIS_LOCAL_BASE_URL=http://127.0.0.1:11434/v1
FENRIS_LOCAL_MODEL=qwen2.5:14b-instruct
```

Then start the backend and client as usual (`uvicorn backend.main:app ...`,
`python main.py`) — nothing else changes.

**vLLM** (rented cloud GPU), same provider code:

```bash
pip install vllm
python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-14B-Instruct --port 8000
```

```ini
FENRIS_BRAIN_PROVIDER=local
FENRIS_LOCAL_BASE_URL=http://<host>:8000/v1
FENRIS_LOCAL_MODEL=Qwen/Qwen2.5-14B-Instruct
```

Pick a model with real tool/function-calling support — Fenris is useless
without it. Qwen2.5-Instruct (7B/14B) and Llama-3.1-8B-Instruct are solid
starting points; 14B fits a 24 GB card quantized and handles multi-step tool
use noticeably better than 7B. If the local server isn't reachable, `/chat`
returns a clear 503 rather than hanging.

## Persistent memory

Fenris stores each enrolled person’s conversation in a local SQLite database at
`data/fenris_memory.sqlite3`, grouped into sessions — one session per run of
the app, from open to close. Within a session, nothing is trimmed: the full
conversation stays in context for as long as the app is open. The first time
Fenris recognizes someone in a new run, if it has a previous session on record
for them, it asks whether to pick up where you left off or start fresh, rather
than silently doing either. Guests are not persisted. Regular users can read
or clear only their own history; the admin policy can access every enrolled
person’s history through the backend endpoints:

```text
GET    /memory/{owner}
GET    /memory/{owner}/last-session
DELETE /memory/{owner}
```

The optional `query` parameter on `GET /memory/{owner}` searches that person’s
stored message text. The `data/` folder stays local and is excluded from Git.

## Long-term memory

Session history (above) is the transcript; this is what Fenris actually
*remembers about you* across sessions. Each turn, durable facts — preferences,
names, relationships, projects, recurring context, not one-off task details —
are distilled out and stored per person, alongside semantic embeddings of both
those facts and the conversation itself. On later turns, the facts it has and
anything semantically related to what you just said are pulled back into
context, so it can recall something relevant even without keyword overlap.

This needs an embeddings endpoint — an OpenAI-compatible one, the same shape
the local model brain uses. The easy path is Ollama:

```powershell
ollama pull nomic-embed-text
```

It reuses `FENRIS_LOCAL_BASE_URL`/`FENRIS_LOCAL_API_KEY` by default, so this
works even when `FENRIS_BRAIN_PROVIDER=anthropic` — embeddings are a separate
call from the conversation itself. If that endpoint is ever unreachable, chat
still works exactly as normal, just without memory that turn (logged once,
not on every request). Set `FENRIS_SEMANTIC_MEMORY=false` to turn this off
entirely and revert `/chat` to using only the session transcript.

Strictly per-person and guest-excluded, same as session memory. `DELETE
/memory/{owner}` now clears facts and embeddings along with the transcript —
"forget me" actually forgets.

## Proactive delivery

Fenris can speak first — no wake word — when something it's tracking comes
due. Today that's reminders: say "remind me in 20 minutes to check the oven"
or "remind me tomorrow at 9am to call the vet," and Fenris will actually say
it unprompted when the time comes, not just note it down. Ask "what
reminders do I have?" to list pending ones, or ask to cancel one.

A background thread on the desktop client polls the backend every
`PROACTIVE_POLL_SECONDS` (default 30) for whichever enrolled person it's
currently tracking (the same recognized-speaker-or-owner-fallback logic used
for typed input). It never interrupts: it skips entirely during
`PROACTIVE_QUIET_START`–`PROACTIVE_QUIET_END` (default 22:00–08:00 local),
and while any turn — spoken, typed, or a running mission — is in progress.
Guests never set or receive reminders. Set `PROACTIVE_ENABLED=false` to turn
the whole mechanism off — no background thread at all, zero behavior change
from today.

This is deliberately just the *delivery* mechanism — reminders are the first
thing that schedules through it, and it's built so that watching external
sources (calendar, email) can plug into the same `reminders` table later
without new client-side machinery. `DELETE /memory/{owner}` clears a
person's pending reminders too, alongside their transcript, facts, and
embeddings.

## Initiative

Beyond reminders you explicitly set, Fenris can occasionally bring something
up entirely on its own — "you mentioned wanting to email Sam yesterday, still
want to?" — grounded only in stored facts and recent conversation (long-term
memory, above), never anything external. **Off by default**, and the whole
design leans toward silence on purpose: a background pass considers each
known person at most every `FENRIS_INITIATIVE_MIN_HOURS` (default 4), asks
the model for *one* genuinely useful thing worth saying or an exact `NONE`,
and only stores a suggestion if it clears that bar — a quiet run of
considerations is the expected, correct outcome, not a bug. At most
`FENRIS_INITIATIVE_MAX_PENDING` (default 1) can stack up undelivered per
person, and the same idea is never raised twice (deduped by a hash of the
suggestion). Guests are never considered — they're never in stored memory to
begin with.

Turn it on with `FENRIS_INITIATIVE=true` and an embeddings/completion setup
(see Long-term memory above); it delivers through the exact same proactive
voice loop as reminders, so it's already quiet-hours-respected and never
interrupts an active turn. `GET /proactive/due` returns reminders and
initiatives together, each tagged `type`, and the spoken lead-in differs
("Reminder — …" vs. "By the way — …") but nothing else about delivery does.

## Acting on your computer

`system_control` lets Fenris actually do things on this PC — open an app, run
a pre-approved command, write a file — the capability that most sets a
"personal assistant" apart from "chatbot with a microphone." It's also the
most dangerous thing in this project, so it's built on one absolute rule with
no exceptions: **Fenris always says exactly what it's about to do and waits
for your explicit yes before doing it — every single time, for every single
action.** There's no trusted mode, no "don't ask again," no allow-list entry
that skips the prompt. If a specific action wasn't just confirmed, nothing
happens.

Everything else about it is equally deliberate:

- **Admin-only.** `required_role = "admin"`, enforced by the same add-on
  manager every other add-on goes through.
- **Allow-list only, no arbitrary execution.** There is no "run any command"
  action. `open_app` only launches a name you've mapped to an exe in
  `FENRIS_ALLOWED_APPS`. `run_command` only runs a `command_id` you've mapped
  to a fixed argument template in `FENRIS_ALLOWED_COMMANDS` — always as an
  explicit argument list, never a shell (`shell=True` is never used, anywhere
  in this add-on), with a defense-in-depth check rejecting shell metacharacters
  in any extra arguments too. Anything not on a list is refused outright.
- **Folder-scoped writes, separate from reading.** `write_file`/`append_file`
  can only touch paths inside `FENRIS_WRITABLE_FOLDERS` — a second, independent
  allow-list from the read-only `FENRIS_LOCAL_FOLDERS` (`local_files` add-on),
  so you can grant read without write on the same folder. Resolved with the
  same containment check `local_files` uses, so `..` and symlink tricks can't
  reach outside it.
- **Off by default.** All three allow-lists are empty out of the box — with
  nothing configured, none of this can act, full stop.
- **Audited**, like every add-on call, payload included.

Reading/listing files stays with `local_files` — this add-on only ever
writes. See `.env.example` for the exact format of all three settings, and
the warning there about treating them as real permission grants.

## Change and audit records

[CHANGELOG.md](CHANGELOG.md) records major product and architecture changes.
Runtime events are kept locally in `data/fenris_audit.sqlite3`: voice-profile
enrollment, persistent-memory deletion, add-on requests (including denied and
confirmation-required requests), and audit-log views. Conversation text and
common sensitive fields such as passwords, PINs, tokens, and API keys are not
recorded in the audit trail.

The administrator can view recent operational events through `GET /audit` with
their admin identity. Audit records are append-only through Fenris’s API; make
regular backups of the local `data/` folder if you need long-term retention.

## Admin-authorized add-on creation

Fenris can create a safe add-on **scaffold** only after an admin submits a
request and enters a password verified against a hash stored outside the
project. Create that external hash file once, ideally on encrypted removable
storage:

```powershell
python create_addon_authorization.py E:\FenrisKeys\addon_creator.hash
```

Then set `FENRIS_ADDON_CREATOR_AUTH_FILE` in `.env` to that path. The backend
endpoint is `POST /addons/create`. It creates a manifest-only scaffold under
`addons/custom/manifest.json`, validates its name/actions, and records the
event. Scaffolds cannot control hardware, browse, or run arbitrary code until a
specific implementation has been reviewed and registered.

## Add-ons

The backend has a small, role-aware add-on system. Use [addons/TEMPLATE.py](addons/TEMPLATE.py)
as the starting point for a new capability, then register it in
`addons/manager.py`.

Two safe starter add-ons are included:

- `projector`: validates an image/video artifact, then requires confirmation
  before queuing a display request.
- `image_print`: validates image path, paper (`letter`, `a4`, or `4x6`), color,
  and copies before it can queue a print request.

They are admin-only and deliberately do not touch hardware yet. The next step
is choosing a specific projector/display and printer implementation; we can
then replace the `queued` result with that device adapter.

### Web browser add-on

`web_browser` provides read-only `research` and `browse` actions for enrolled
users. `interact` accepts a short, explicit sequence of `open`, `click`,
`fill`, and `wait` steps, but it always needs confirmation because it can change
website state. Add-ons do not have access to local/private network addresses.

Cookies from a logged-in `interact`/`browse` session are kept per enrolled
person for as long as the backend process runs (never written to disk), so a
login made in one request is still there on a later, separate one — guests
never get this. `browse` also returns a `fields` list of real selectors for
the inputs/buttons on the page, so filling in a form doesn't rely on guessed
selectors.

Install the browser engine once after installing requirements:

```powershell
playwright install chromium
```

Examples of the backend requests:

```json
{"actor_role":"user","action":"research","payload":{"query":"local weather forecast","limit":5}}
```

```json
{"actor_role":"admin","action":"interact","confirmed":true,"payload":{"steps":[{"action":"open","url":"https://example.com"}]}}
```

The key enables conversation with the model; it does **not** by itself give
Fenris permission to browse the web or control your computer. Those should be
added as separate, confirmation-based capabilities.

### Media display add-on

`media` lets Fenris actually show an image or video in the HUD instead of only
describing it in speech — a `show` action, read-only, no confirmation needed,
available to enrolled users. `source: "web"` takes any public http/https URL
(the same address rules as `web_browser` apply); `source: "local"` takes a file
path already on this PC and is served back to the HUD through its own
`/media` endpoint (validated by file existence and extension — only common
image/video formats are servable). AI-generated images aren't wired up yet;
that needs a separate image-generation provider and API key.

### Local files add-on

`local_files` lets Fenris list and read files on this PC, but only inside
folders you explicitly name in `FENRIS_LOCAL_FOLDERS` (`.env`) — off by
default. `list` is read-only and needs no confirmation; `read` always needs
your explicit go-ahead for that specific file, since it's the step that
actually exposes the file's content to the model. Text files, PDFs, and DOCX
are supported. Requesting a path outside the allowed folders is rejected.

## Local voice profiles and access roles

Create a local profile for each person in a quiet room:

```powershell
python enroll_voice.py master admin
python enroll_voice.py alex user
```

Fenris stores only an acoustic profile (not the recordings) in `data/`, which
is excluded from Git. Recognized people get separate conversation memory; an
unrecognized speaker is a guest and their conversation is not retained.

An enrolled `admin` may say `list profiles`, `read memory <name>`, or `clear
memory <name>` to manage every enrolled person’s current-session conversation
memory. Regular users can access only their own. Voice matching can be fooled
by recordings and can make mistakes, so add a second confirmation factor before
using this policy for sensitive or persistent data.

## Deliberate limits of this first version

Fenris does not control your computer, access private accounts, or run shell
commands. Those should be added as individually approved tools with clear
permissions and confirmation prompts, rather than as unrestricted commands.
