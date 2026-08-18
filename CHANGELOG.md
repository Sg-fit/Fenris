## 2026-07-19 — Typing and file/image uploads

- The HUD now has a composer: type messages to Fenris instead of speaking, and attach documents or images with the 📎 button.
- Uploaded images are sent to the model's vision; PDF, Word (.docx), and text/markdown/CSV documents have their text extracted locally and included with the message.
- Typed and uploaded input never needs the wake word and is attributed to the last recognized voice, or to `OWNER_NAME` when none has spoken yet.

## 2026-07-19 — Web browsing and actions in conversation

- The Claude brain can now use the web during a conversation through tools: `web_search` and `read_page` are read-only and run automatically; `browser_actions` (open/click/fill/submit in a real visible browser) runs only after the user approves the specific steps out loud.
- Wired the existing `web_browser` add-on to the `/chat` tool loop with role checks preserved (guests cannot browse) and every call recorded in the audit trail.

# Fenris change log

## 2026-07-18 — Initial architecture

- Added voice input/output diagnostics and local Whisper option.
- Added a local FastAPI backend with a Claude provider boundary.
- Added local speaker profiles, roles, and separate user memory.
- Added persistent SQLite conversation memory and admin memory-management policy.
- Added add-on framework with projector, image-print, and controlled web-browser starters.
- Added append-only local audit events for profile enrollment, memory deletion, add-on requests, and audit-log access.

## Recording future changes

Add a dated entry here whenever a capability, access rule, provider, data
location, or hardware integration changes. Runtime events belong in the local
audit database, not this file.
