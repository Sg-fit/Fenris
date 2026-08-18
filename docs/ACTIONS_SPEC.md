# Fenris — Gap #1: Acting on your computer (with a prompt before every action)

This gives Fenris the ability to *do things* on your computer — the capability most
absent today and the one that most makes it feel like JARVIS. It is also the **most
dangerous** capability in the system, so it is built entirely inside the existing
permissioned add-on framework, and the security rules below are **hard acceptance
criteria, not suggestions**.

Scope: **one add-on, `system_control`.** No smart-home / Home Assistant — out of scope,
do not build it.

## THE central rule: always prompt before acting

Fenris must **never** control the computer without first telling the user exactly what
it's about to do and getting an explicit yes. Every computer action — opening an app,
running a command, writing a file — is **confirmation-gated**: on the first request the
add-on returns `confirmation_required` describing the action, Fenris speaks/shows that
to the user, and only after the user explicitly approves does the model re-issue the
call with `user_confirmed=true`. There is **no** "trusted mode", no per-session
"don't ask again", no allow-list that skips the prompt. Unconfirmed ⇒ nothing happens.
An action taken without a fresh, explicit confirmation is a bug.

## Other non-negotiable security rules

1. **No arbitrary code execution, ever.** There is no "run any shell command" action.
   Only pre-approved, allow-listed operations run. `shell=True` is forbidden; always
   pass an explicit argv list.
2. **Allow-list only.** Apps, commands, and writable folders come from explicit env
   allow-lists. Anything not on the list is refused with a clear message. Empty
   allow-list ⇒ that action is simply off ("not configured" result).
3. **Admin-only** (`required_role = "admin"`), enforced by `AddonManager`.
4. **You control which folders Fenris can touch — first-class rule.** Access is
   folder-scoped and fully user-controlled, split into two independent allow-lists:
   read access is limited to `FENRIS_LOCAL_FOLDERS` (existing `local_files` add-on),
   and write access to a **separate** `FENRIS_WRITABLE_FOLDERS`. You can grant read
   without write on the same folder. Anything outside the relevant list is refused —
   resolved with the same `.resolve()` + `folder in parents` containment check
   `LocalFilesAddon._resolve` uses, so `..` escapes and symlink tricks can't reach
   outside. Never in either list by default: system dirs, home root, the Fenris project
   itself. Both lists are empty by default (no file access until you name folders).
5. **Off by default.** With nothing configured, none of this can act.
6. **Audited.** The manager already audits every add-on call with payload; keep that.

## Existing framework to build on

- `addons/base.py`: `Addon` ABC — `id`, `name`, `description`, `required_role`,
  `run(actor_name, actor_role, action, payload, confirmed) -> AddonResult`.
- `addons/manager.py` `AddonManager`: registers add-on instances, enforces the admin
  role, audits every call. Register `SystemControlAddon` here.
- `addons/local_files.py`: the template — allow-list resolution, a read-only action vs
  a gated action (`_read` returns `confirmation_required` unless `confirmed`), size
  caps, defensive returns. Mirror its shape exactly for the gating.
- `backend/main.py`: `_TOOL_ADDONS` maps a model tool → `(addon_id, action,
  build_payload, requires_confirmation)`; `requires_confirmation=True` makes the runner
  pass `confirmed=user_confirmed`. All new tools use `True`.
- `backend/brain/tools.py`: shared `TOOLS` (both providers). Add tool schemas here.
- `backend/brain/prompt.py`: `SYSTEM_PROMPT` documents each tool. Add gating-heavy docs.
- `backend/settings.py`: add the allow-list settings.

## A. `system_control` add-on (`addons/system_control.py`)

`id="system_control"`, `required_role="admin"`. Every action below is
confirmation-gated (returns `confirmation_required` when `confirmed` is false, and does
nothing else).

### `open_app`
- Payload `{app: str}`. `app` must be a key in `Settings.ALLOWED_APPS`
  (`FENRIS_ALLOWED_APPS`, e.g. `notepad=notepad.exe;browser=C:\...\chrome.exe`). Reject
  anything not a key. Launch detached via `subprocess.Popen([exe])` — no shell.

### `run_command`
- Payload `{command_id: str, args: list[str] (optional)}`. `command_id` must be a key in
  `Settings.ALLOWED_COMMANDS` (`FENRIS_ALLOWED_COMMANDS`), each mapping to a fixed argv
  template the user pre-defined. Build `template + validated args` and run with
  `subprocess.run(argv, shell=False, timeout=…, capture_output=True)`. Reject unknown
  `command_id`. Reject arg values containing shell metacharacters (defense in depth even
  though shell is off). Return truncated stdout/stderr. This is the *only* command path
  and it is allow-list bound — there is deliberately no free-form command action.

### `write_file` / `append_file`
- Payload `{path: str, content: str}`. Resolve `path` against
  `Settings.WRITABLE_FOLDERS` (`FENRIS_WRITABLE_FOLDERS`) using the containment check;
  reject anything outside. Enforce a max content size. Write UTF-8 (`append_file`
  appends). Return the resolved path and bytes written.

(Reading/listing files stays with the existing `local_files` add-on — don't duplicate.)

Each action returns `AddonResult("not configured", ...)` when its allow-list is empty,
so an unconfigured Fenris cannot act.

## B. Tools, mapping, prompt

Add to `backend/brain/tools.py` `TOOLS` and map in `_TOOL_ADDONS`, all with
`requires_confirmation=True`:
- `open_app` → (`system_control`, `open_app`, …, **True**)
- `run_command` → (`system_control`, `run_command`, …, **True**)
- `write_file` → (`system_control`, `write_file`, …, **True**)
- `append_file` → (`system_control`, `append_file`, …, **True**)

Each schema includes `user_confirmed: boolean`. In `prompt.py`, document them with the
same discipline as `browser_actions`, made explicit: **before any computer action,
state exactly what you'll do (which app, which command + args, which file and what
you'll write) in plain language, wait for the user's explicit approval, and only then
set `user_confirmed=true`.** Never run an app/command/write the user hasn't just
approved. If they didn't clearly say yes, set `user_confirmed=false` so they're asked.
Report failures in plain terms (no raw errors/exceptions/tool names).

## C. Settings (`backend/settings.py`) + `.env.example`

```python
ALLOWED_APPS     = _parse_pairs(os.getenv("FENRIS_ALLOWED_APPS", ""))       # name=exe; empty ⇒ open_app off
ALLOWED_COMMANDS = _parse_pairs(os.getenv("FENRIS_ALLOWED_COMMANDS", ""))   # id=argv template; empty ⇒ run_command off
WRITABLE_FOLDERS = [Path(p).expanduser().resolve() for p in                 # empty ⇒ writes off
                    os.getenv("FENRIS_WRITABLE_FOLDERS", "").split(";") if p.strip()]
```
Document each in `.env.example` with a loud warning that these grant real action
capability on your machine and should be scoped to exactly what you want Fenris to do,
and add a README "Acting on your computer" section covering the model: admin-only,
allow-list only, **prompts before every action**, audited, off by default.

## D. Tests (`tests/`)

- **Confirmation gating (the headline):** every mutating action with `confirmed=False`
  returns `confirmation_required` and performs **no** side effect —
  `subprocess`/filesystem patched to assert they were never called.
- `open_app`/`run_command`: unknown app/command_id → refused, nothing launched.
- `run_command`: shell-metacharacter args rejected; argv is a list; `shell` never True.
- `write_file`: path outside `WRITABLE_FOLDERS` refused; inside + confirmed → written;
  size cap enforced; unconfirmed → not written.
- Role: a `user`/`guest` calling `system_control` is denied by the manager.
- Not configured: empty allow-lists → informative results, no side effects.

## E. Acceptance criteria

- **Every** computer action prompts first; an unconfirmed request never touches the OS
  or filesystem.
- Nothing runs arbitrary shell; only allow-listed apps/commands execute, only via argv.
- Every action is admin-gated; file writes cannot escape `FENRIS_WRITABLE_FOLDERS`.
- With nothing configured, all of it is inert.
- Existing add-ons/tools and all prior tests still pass; new tests pass.

## F. Follow-up (not built here): productivity integrations

Calendar/email fit the same add-on shape (read actions unconfirmed, send/create actions
confirmation-gated) but need OAuth credential handling, so they're a separate later
brief — and calendar pairs with Gap #2's proactivity so Fenris can remind you about real
events, not just manual reminders.
