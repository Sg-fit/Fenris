import json
import queue
import threading
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from addons.manager import AddonManager
from addons.factory import create_scaffold
from backend.audit import AuditLog
from backend.brain.factory import get_provider_class
from backend.brain.missions import MissionStore
from backend.memory.extractor import extract_facts
from backend.memory.semantic import SemanticMemory
from backend.memory.store import MemoryStore
from backend.proactive.initiative import InitiativeEngine
from backend.proactive.store import ProactiveStore
from backend.settings import Settings


app = FastAPI(title="Fenris Brain API", version="0.1.0")
addons = AddonManager()
memory = MemoryStore()
# Durable cross-session memory (facts + semantic recall). None when disabled —
# every use site below is gated on this, so /chat behaves exactly as before
# when FENRIS_SEMANTIC_MEMORY is off.
semantic = SemanticMemory() if Settings.SEMANTIC_MEMORY else None
proactive = ProactiveStore()
audit = AuditLog()
missions = MissionStore()
# Fenris occasionally speaking up on its own, from memory — off unless
# FENRIS_INITIATIVE is explicitly set; .start() itself no-ops otherwise, so
# this line alone never changes behavior.
initiative_engine = InitiativeEngine(memory, semantic, proactive, audit)


@app.on_event("startup")
def start_initiative_engine() -> None:
    initiative_engine.start()


class Message(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=12_000)


class ImagePart(BaseModel):
    media_type: str = Field(pattern="^image/(png|jpeg|gif|webp)$")
    data: str = Field(min_length=1, max_length=8_000_000)


class ChatRequest(BaseModel):
    # A live session is meant to stay untrimmed for as long as it runs (see
    # memory/memory.py); this is a safety ceiling, not the expected size —
    # matches Config.MAX_HISTORY_MESSAGES on the client.
    messages: list[Message] = Field(min_length=1, max_length=500)
    actor_name: str = Field(default="guest", min_length=1, max_length=80)
    actor_role: str = Field(default="guest", pattern="^(guest|user|admin)$")
    images: list[ImagePart] = Field(default_factory=list, max_length=6)
    # Groups this actor's messages into one continuous run (app open to close)
    # for persistent storage, independent of the live context sent per turn.
    session_id: str = Field(min_length=1, max_length=100)


class AddonRequest(BaseModel):
    actor_name: str = Field(default="guest", min_length=1, max_length=80)
    actor_role: str = Field(pattern="^(guest|user|admin)$")
    action: str = Field(min_length=1, max_length=64)
    payload: dict = Field(default_factory=dict)
    confirmed: bool = False


class AddonCreateRequest(BaseModel):
    actor_name: str = Field(min_length=1, max_length=80)
    actor_role: str = Field(pattern="^admin$")
    authorization_password: str = Field(min_length=1, max_length=256, repr=False)
    addon_id: str
    name: str
    description: str
    actions: list[str]


class ReminderCreateRequest(BaseModel):
    actor_name: str = Field(min_length=1, max_length=80)
    actor_role: str = Field(pattern="^(guest|user|admin)$")
    session_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    # Either an ISO 8601 timestamp, or {"in_minutes": N} — see _resolve_fire_at.
    when: str | dict | None = None


@app.get("/health")
def health():
    return {"status": "ok", "provider": Settings.BRAIN_PROVIDER}


@app.get("/addons")
def list_addons():
    return {"addons": addons.manifests()}


@app.post("/addons/{addon_id}/run")
def run_addon(addon_id: str, request: AddonRequest):
    return addons.run(addon_id, request.actor_name, request.actor_role, request.action, request.payload, request.confirmed).to_dict()


@app.post("/addons/create", status_code=201)
def create_addon(request: AddonCreateRequest):
    from security.addon_authorization import verify_creator_password

    if not verify_creator_password(request.authorization_password):
        audit.record("addon_creation_denied", request.actor_name, request.actor_role, request.addon_id)
        raise HTTPException(status_code=403, detail="Admin authorization was not verified.")
    try:
        scaffold = create_scaffold(request.addon_id, request.name, request.description, request.actions)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    audit.record("addon_scaffold_created", request.actor_name, request.actor_role, request.addon_id, {"actions": request.actions})
    return {"status": "created", "addon": scaffold, "note": "Scaffold only; review and implement it before enabling external actions."}


@app.get("/audit")
def get_audit(actor_name: str, actor_role: str, limit: int = 100):
    if actor_role != "admin":
        raise HTTPException(status_code=403, detail="The audit trail is available to the administrator only.")
    audit.record("audit_viewed", actor_name, actor_role, details={"limit": limit})
    return {"events": audit.recent(limit)}


def can_access_owner(actor_name: str, actor_role: str, owner: str) -> bool:
    return actor_role == "admin" or actor_name == owner


@app.get("/memory/{owner}")
def get_memory(owner: str, actor_name: str, actor_role: str, query: str | None = None, limit: int = 12):
    if not can_access_owner(actor_name, actor_role, owner):
        raise HTTPException(status_code=403, detail="You can access only your own memory.")
    return {"owner": owner, "messages": memory.history(owner, query, limit)}


@app.get("/memory/{owner}/last-session")
def get_last_session(owner: str, actor_name: str, actor_role: str, exclude: str | None = None):
    if not can_access_owner(actor_name, actor_role, owner):
        raise HTTPException(status_code=403, detail="You can access only your own memory.")
    session_id, messages = memory.last_session(owner, exclude)
    return {"owner": owner, "session_id": session_id, "messages": messages}


@app.delete("/memory/{owner}")
def clear_memory(owner: str, actor_name: str, actor_role: str):
    if not can_access_owner(actor_name, actor_role, owner):
        raise HTTPException(status_code=403, detail="You can clear only your own memory.")
    memory.clear(owner)
    if semantic is not None:
        semantic.clear(owner)
    proactive.clear(owner)
    audit.record("memory_cleared", actor_name, actor_role, owner)
    return {"status": "cleared", "owner": owner}


def _build_memory_context(name: str, facts: list[str], hits: list[dict]) -> str | None:
    """Facts + semantically-recalled snippets, formatted for the system
    prompt. None when there's nothing to add — callers must not change the
    prompt at all in that case."""
    parts = []
    if facts:
        parts.append(f"What you know about {name}:\n" + "\n".join(f"- {fact}" for fact in facts))
    if hits:
        parts.append("Relevant things from past conversations:\n" + "\n".join(f"- {hit['text']}" for hit in hits))
    return "\n\n".join(parts) if parts else None


def _time_context() -> str:
    """The model needs to know "now" to schedule absolute reminder times —
    always included, even for guests (who can't set reminders but can still
    reason about the time)."""
    return f"Current time: {datetime.now().astimezone().isoformat()}"


def _resolve_fire_at(when: str | None, in_minutes: int | None) -> str:
    """Resolve either an absolute ISO 8601 'when' or a relative 'in_minutes'
    into an absolute ISO 8601 UTC fire_at string. Exactly one must be given."""
    if (when is None) == (in_minutes is None):
        raise ValueError("Provide exactly one of when or in_minutes.")
    if in_minutes is not None:
        if not isinstance(in_minutes, int) or in_minutes < 1:
            raise ValueError("in_minutes must be a positive integer.")
        return (datetime.now(timezone.utc) + timedelta(minutes=in_minutes)).isoformat()
    try:
        parsed = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{when!r} isn't a valid ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        # Naive timestamps are assumed to already be in the "Current time"
        # zone the model was given — treat as local, then convert to UTC.
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).isoformat()


@app.post("/proactive/reminders")
def create_reminder(request: ReminderCreateRequest):
    if request.actor_role == "guest":
        raise HTTPException(status_code=403, detail="Guests can't set reminders.")
    in_minutes = request.when.get("in_minutes") if isinstance(request.when, dict) else None
    when_iso = request.when if isinstance(request.when, str) else None
    try:
        fire_at = _resolve_fire_at(when_iso, in_minutes)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    reminder_id = proactive.add(request.actor_name, fire_at, request.text, request.session_id)
    audit.record("reminder_created", request.actor_name, request.actor_role, str(reminder_id), {"fire_at": fire_at})
    return {"id": reminder_id, "fire_at": fire_at}


@app.get("/proactive/due")
def get_due_reminders(owner: str, actor_name: str, actor_role: str, now: str | None = None):
    if actor_role == "guest":
        raise HTTPException(status_code=403, detail="Guests can't receive reminders.")
    if not can_access_owner(actor_name, actor_role, owner):
        raise HTTPException(status_code=403, detail="You can access only your own reminders.")
    now_iso = now or datetime.now(timezone.utc).isoformat()
    reminders = [{"type": "reminder", **item} for item in proactive.due(owner, now_iso)]
    initiatives = [{"type": "initiative", **item} for item in proactive.due_initiatives(owner, now_iso)]
    items = reminders + initiatives
    if items:
        audit.record(
            "proactive_delivered",
            actor_name,
            actor_role,
            owner,
            {"reminders": len(reminders), "initiatives": len(initiatives)},
        )
    return {"owner": owner, "due": items}


@app.get("/proactive/reminders")
def get_pending_reminders(owner: str, actor_name: str, actor_role: str):
    if actor_role == "guest":
        raise HTTPException(status_code=403, detail="Guests don't have reminders.")
    if not can_access_owner(actor_name, actor_role, owner):
        raise HTTPException(status_code=403, detail="You can access only your own reminders.")
    return {"owner": owner, "reminders": proactive.pending(owner)}


@app.delete("/proactive/reminders/{reminder_id}")
def cancel_reminder(reminder_id: int, owner: str, actor_name: str, actor_role: str):
    if actor_role == "guest":
        raise HTTPException(status_code=403, detail="Guests don't have reminders.")
    if not can_access_owner(actor_name, actor_role, owner):
        raise HTTPException(status_code=403, detail="You can cancel only your own reminders.")
    cancelled = proactive.cancel(owner, reminder_id)
    audit.record("reminder_cancelled", actor_name, actor_role, str(reminder_id), {"found": cancelled})
    return {"cancelled": cancelled}


# Maps a model tool call to a role-aware add-on action.
_TOOL_ADDONS = {
    "web_search": (
        "web_browser",
        "research",
        lambda i: {"query": i.get("query"), "limit": i.get("limit", 5), "site": i.get("site")},
        False,
    ),
    "read_page": ("web_browser", "browse", lambda i: {"url": i.get("url")}, False),
    "browser_actions": (
        "web_browser",
        "interact",
        lambda i: {"steps": i.get("steps", []), "show_window": bool(i.get("show_window", False))},
        True,
    ),
    "show_media": (
        "media",
        "show",
        lambda i: {"source": i.get("source"), "location": i.get("location"), "kind": i.get("kind")},
        False,
    ),
    "list_local_files": ("local_files", "list", lambda i: {"path": i.get("path")}, False),
    "read_local_file": ("local_files", "read", lambda i: {"path": i.get("path")}, True),
    "open_app": ("system_control", "open_app", lambda i: {"app": i.get("app")}, True),
    "run_command": (
        "system_control",
        "run_command",
        lambda i: {"command_id": i.get("command_id"), "args": i.get("args") or []},
        True,
    ),
    "write_file": (
        "system_control",
        "write_file",
        lambda i: {"path": i.get("path"), "content": i.get("content")},
        True,
    ),
    "append_file": (
        "system_control",
        "append_file",
        lambda i: {"path": i.get("path"), "content": i.get("content")},
        True,
    ),
}

# Reminder tools aren't add-ons — they go straight against ProactiveStore, so
# they're handled directly in the tool runner rather than through _TOOL_ADDONS.
_PROACTIVE_TOOLS = {"set_reminder", "list_reminders", "cancel_reminder"}


def _run_proactive_tool(tool_name: str, tool_input: dict, actor_name: str, actor_role: str, session_id: str) -> dict:
    if actor_role == "guest":
        return {"status": "error", "message": "Reminders need an enrolled profile — guests can't set or view them."}

    if tool_name == "set_reminder":
        text = str(tool_input.get("text", "")).strip()
        if not text:
            return {"status": "error", "message": "text is required."}
        try:
            fire_at = _resolve_fire_at(tool_input.get("when"), tool_input.get("in_minutes"))
        except ValueError as error:
            return {"status": "error", "message": str(error)}
        reminder_id = proactive.add(actor_name, fire_at, text, session_id)
        audit.record("reminder_created", actor_name, actor_role, str(reminder_id), {"fire_at": fire_at})
        return {"status": "complete", "data": {"id": reminder_id, "fire_at": fire_at}}

    if tool_name == "list_reminders":
        return {"status": "complete", "data": {"reminders": proactive.pending(actor_name)}}

    if tool_name == "cancel_reminder":
        reminder_id = tool_input.get("reminder_id")
        if not isinstance(reminder_id, int):
            return {"status": "error", "message": "reminder_id must be an integer."}
        cancelled = proactive.cancel(actor_name, reminder_id)
        audit.record("reminder_cancelled", actor_name, actor_role, str(reminder_id), {"found": cancelled})
        return {"status": "complete" if cancelled else "invalid", "data": {"cancelled": cancelled}}

    return {"status": "error", "message": f"Unknown proactive tool '{tool_name}'."}


def _make_tool_runner(actor_name: str, actor_role: str, session_id: str):
    def run_tool(tool_name: str, tool_input: dict) -> dict:
        if tool_name in _PROACTIVE_TOOLS:
            return _run_proactive_tool(tool_name, tool_input, actor_name, actor_role, session_id)
        mapping = _TOOL_ADDONS.get(tool_name)
        if mapping is None:
            return {"status": "error", "message": f"Unknown tool '{tool_name}'."}
        addon_id, action, build_payload, requires_confirmation = mapping
        confirmed = bool(tool_input.get("user_confirmed")) if requires_confirmation else True
        result = addons.run(addon_id, actor_name, actor_role, action, build_payload(tool_input), confirmed)
        return result.to_dict()

    return run_tool


@app.post("/chat")
def chat(request: ChatRequest):
    provider_class = get_provider_class()
    try:
        provider = provider_class(
            tool_runner=_make_tool_runner(request.actor_name, request.actor_role, request.session_id)
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    actor_name, actor_role = request.actor_name, request.actor_role
    # If this actor left a mission mid-question last turn, this message is the
    # answer: resume the same conversation instead of starting a fresh one.
    paused_conversation = missions.pop(actor_name, actor_role)
    if paused_conversation is not None:
        conversation = paused_conversation
        resume_answer = request.messages[-1].content
    else:
        conversation = provider_class.build_conversation(
            [message.model_dump() for message in request.messages],
            images=[image.model_dump() for image in request.images],
        )
        resume_answer = None

    # Always present (even for guests) so the model can schedule absolute
    # reminder times unambiguously; facts/recall are appended when available.
    memory_context = _time_context()
    if actor_role != "guest" and semantic is not None:
        try:
            facts_and_hits = _build_memory_context(
                actor_name,
                semantic.facts(actor_name),
                semantic.retrieve(actor_name, request.messages[-1].content),
            )
            if facts_and_hits:
                memory_context += "\n\n" + facts_and_hits
        except Exception as error:
            print(f"[SemanticMemory] context assembly failed: {error}")

    def event_stream():
        events: "queue.Queue" = queue.Queue()
        outcome: dict = {}

        def on_event(event: dict) -> None:
            if event.get("type") in {"result", "question"}:
                outcome["last_text"] = event.get("text", "")
            events.put(event)

        def worker() -> None:
            try:
                paused, convo = provider.stream_reply(
                    conversation, on_event, resume_answer=resume_answer, memory_context=memory_context
                )
            except Exception as error:
                print(f"[Claude provider error] {error}")
                on_event({"type": "result", "text": "My local brain service could not complete that request."})
                paused, convo = False, conversation
            outcome["paused"] = paused
            outcome["conversation"] = convo
            events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            event = events.get()
            if event is None:
                break
            yield json.dumps(event) + "\n"

        if outcome.get("paused"):
            missions.save(actor_name, actor_role, outcome["conversation"])
        if actor_role != "guest":
            user_text = request.messages[-1].content
            user_row_id = memory.add(actor_name, "user", user_text, request.session_id)
            if "last_text" in outcome:
                assistant_text = outcome["last_text"]
                assistant_row_id = memory.add(actor_name, "assistant", assistant_text, request.session_id)
                if semantic is not None:
                    try:
                        semantic.index_message(actor_name, str(user_row_id), user_text)
                        semantic.index_message(actor_name, str(assistant_row_id), assistant_text)
                        for fact in extract_facts(provider.complete, user_text, assistant_text):
                            semantic.remember_fact(actor_name, fact, request.session_id)
                    except Exception as error:
                        print(f"[SemanticMemory] indexing/extraction failed: {error}")

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
