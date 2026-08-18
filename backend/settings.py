import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _parse_pairs(raw: str) -> dict[str, str]:
    """'key1=value1;key2=value2' -> {"key1": "value1", "key2": "value2"}.
    Blank/malformed entries are skipped rather than raising, so a typo in
    .env degrades to "that entry is missing" instead of crashing startup."""
    pairs: dict[str, str] = {}
    for item in raw.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, _, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            pairs[key] = value
    return pairs


class Settings:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    # Folders Fenris is allowed to list/read files from, comma-separated.
    # Empty by default — local file access is off until you name folders here.
    LOCAL_DATA_FOLDERS = [
        Path(folder).expanduser().resolve()
        for folder in os.getenv("FENRIS_LOCAL_FOLDERS", "").split(",")
        if folder.strip()
    ]

    # Which brain runs the conversation: "anthropic" (default, cloud) or
    # "local" (an open-weight model served over an OpenAI-compatible API —
    # Ollama or vLLM, selected purely by LOCAL_BASE_URL, no code change).
    BRAIN_PROVIDER = os.getenv("FENRIS_BRAIN_PROVIDER", "anthropic").lower()
    LOCAL_BASE_URL = os.getenv("FENRIS_LOCAL_BASE_URL", "http://127.0.0.1:11434/v1")
    LOCAL_MODEL = os.getenv("FENRIS_LOCAL_MODEL", "qwen2.5:14b-instruct")
    # Ollama ignores this; vLLM uses whatever it was launched with.
    LOCAL_API_KEY = os.getenv("FENRIS_LOCAL_API_KEY", "ollama")
    LOCAL_MAX_TOKENS = int(os.getenv("FENRIS_LOCAL_MAX_TOKENS", "1024"))

    # Durable cross-session memory: distilled facts + semantic recall of past
    # messages, injected into context so Fenris remembers people, not just
    # the current transcript. Off entirely reverts /chat to today's behavior.
    SEMANTIC_MEMORY = os.getenv("FENRIS_SEMANTIC_MEMORY", "true").lower() in {"1", "true", "yes", "on"}
    # Reuses the local OpenAI-compatible endpoint by default (e.g. Ollama's
    # nomic-embed-text) — works even when BRAIN_PROVIDER is "anthropic".
    EMBED_BASE_URL = os.getenv("FENRIS_EMBED_BASE_URL", LOCAL_BASE_URL)
    EMBED_MODEL = os.getenv("FENRIS_EMBED_MODEL", "nomic-embed-text")
    EMBED_API_KEY = os.getenv("FENRIS_EMBED_API_KEY", LOCAL_API_KEY)
    MEMORY_TOPK = int(os.getenv("FENRIS_MEMORY_TOPK", "6"))
    MEMORY_MIN_SCORE = float(os.getenv("FENRIS_MEMORY_MIN_SCORE", "0.35"))
    MEMORY_FACT_CAP = int(os.getenv("FENRIS_MEMORY_FACT_CAP", "40"))

    # Acting on the computer (system_control add-on) — every one of these is
    # empty by default, meaning that capability is simply off. Populating
    # them grants Fenris real ability to launch programs, run commands, or
    # write files on this machine; every action is still confirmation-gated
    # and admin-only regardless, but only scope these to exactly what you
    # want Fenris able to do.
    ALLOWED_APPS = _parse_pairs(os.getenv("FENRIS_ALLOWED_APPS", ""))
    ALLOWED_COMMANDS = _parse_pairs(os.getenv("FENRIS_ALLOWED_COMMANDS", ""))
    WRITABLE_FOLDERS = [
        Path(folder).expanduser().resolve()
        for folder in os.getenv("FENRIS_WRITABLE_FOLDERS", "").split(";")
        if folder.strip()
    ]

    # Initiative: Fenris periodically considers whether there's something
    # worth bringing up on its own, from stored facts/memory + the time —
    # not just reminders you explicitly set. Off by default; the design is
    # deliberately biased toward silence (see backend/main.py's consideration
    # prompt) — rate-limited hard, capped, quiet-hours-respected, guest-free.
    INITIATIVE = os.getenv("FENRIS_INITIATIVE", "false").lower() in {"1", "true", "yes", "on"}
    INITIATIVE_INTERVAL = int(os.getenv("FENRIS_INITIATIVE_INTERVAL", "1800"))
    INITIATIVE_MIN_HOURS = float(os.getenv("FENRIS_INITIATIVE_MIN_HOURS", "4"))
    INITIATIVE_MAX_PENDING = int(os.getenv("FENRIS_INITIATIVE_MAX_PENDING", "1"))
    INITIATIVE_HISTORY_N = int(os.getenv("FENRIS_INITIATIVE_HISTORY_N", "20"))
