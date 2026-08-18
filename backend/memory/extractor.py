import json
from typing import Callable

EXTRACTOR_SYSTEM_PROMPT = """Extract only durable facts worth remembering long-term
about the user from this exchange — preferences, names, relationships, projects,
recurring context they'd expect you to remember next time. Not transient chit-chat,
not one-off task details, not anything generic or already obvious.

Reply with each fact as a short standalone statement, one per line, nothing else —
no numbering, no commentary. If nothing in this exchange is worth keeping
long-term, reply with exactly: NONE"""


def extract_facts(complete: Callable[[str, str], str], user_text: str, assistant_text: str) -> list[str]:
    """Distill durable facts about the user from one exchange, via a single
    cheap model call. Never raises into the caller — any failure (the call
    itself, or an unparseable reply) just yields no facts for this turn."""
    if not user_text or not user_text.strip():
        return []
    prompt = f"User said: {user_text}\n\nAssistant replied: {assistant_text}"
    try:
        raw = complete(EXTRACTOR_SYSTEM_PROMPT, prompt)
    except Exception:
        return []
    return _parse(raw)


def _parse(raw: str) -> list[str]:
    if not raw or not isinstance(raw, str):
        return []
    text = raw.strip()
    if not text or text.upper() == "NONE":
        return []

    # Defensive: also accept a JSON list, in case the model wraps it that way.
    if text.startswith("["):
        try:
            items = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            items = None
        if isinstance(items, list):
            return [str(item).strip() for item in items if str(item).strip()]

    facts = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if not line or line.upper() == "NONE":
            continue
        facts.append(line)
    return facts
