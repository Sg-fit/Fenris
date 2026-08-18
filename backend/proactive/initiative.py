import hashlib
import threading
from datetime import datetime, timedelta, timezone

from backend.brain.factory import get_provider_class
from backend.settings import Settings

CONSIDERATION_PROMPT = """You are Fenris, privately considering — not as part of
any conversation — whether there's something worth proactively bringing up to
{name} right now.

Given what you know about them and the current time, is there ONE genuinely
useful thing worth proactively bringing up right now — an unfinished intention
they mentioned, a time-sensitive follow-up, something they'd thank you for
remembering? Only if it clearly clears a high bar. If there's any doubt at
all, or it's just filler, reply with exactly: NONE

Otherwise reply with exactly one short, natural spoken sentence — nothing
else, no preamble, no quotes around it."""


class InitiativeEngine:
    """Background thread that periodically considers, per known person,
    whether there's something worth Fenris bringing up unprompted — grounded
    only in stored facts/memory and the current time. Heavily biased toward
    silence: hard per-person rate limit, a pending cap, dedup against recent
    suggestions, and a complete no-op unless FENRIS_INITIATIVE is explicitly
    turned on. One owner's failure (or the model being unreachable) never
    kills the thread or blocks other owners."""

    def __init__(self, memory, semantic, proactive, audit):
        self.memory = memory
        self.semantic = semantic
        self.proactive = proactive
        self.audit = audit
        self._last_considered: dict[str, datetime] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not Settings.INITIATIVE:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(Settings.INITIATIVE_INTERVAL)

    def tick(self) -> None:
        """One full pass over known owners. Public (not just internal to
        _run) so it's directly testable without threads."""
        try:
            provider = get_provider_class()(tool_runner=None)
        except RuntimeError as error:
            print(f"[Initiative] provider unavailable this tick: {error}")
            return
        for owner in self._known_owners():
            try:
                self._consider(owner, provider)
            except Exception as error:  # one owner's failure must never stop the rest
                print(f"[Initiative] considering {owner!r} failed: {error}")

    def _known_owners(self) -> list[str]:
        owners = set(self.memory.distinct_owners())
        if self.semantic is not None:
            owners |= set(self.semantic.distinct_owners())
        return sorted(owners)

    def _consider(self, owner: str, provider) -> None:
        now = datetime.now(timezone.utc)
        last = self._last_considered.get(owner)
        if last is not None and now - last < timedelta(hours=Settings.INITIATIVE_MIN_HOURS):
            return
        if self.proactive.pending_initiative_count(owner) >= Settings.INITIATIVE_MAX_PENDING:
            return

        # Mark considered regardless of outcome — a "nothing worth saying"
        # result still counts against the rate limit, so a quiet person
        # doesn't get re-considered every single tick.
        self._last_considered[owner] = now

        facts = self.semantic.facts(owner) if self.semantic is not None else []
        history = self.memory.history(owner, None, Settings.INITIATIVE_HISTORY_N)
        context = self._build_context(owner, facts, history)

        reply = provider.complete(CONSIDERATION_PROMPT.format(name=owner), context)
        suggestion = (reply or "").strip()
        if not suggestion or suggestion.upper() == "NONE":
            return

        context_hash = hashlib.sha256(suggestion.strip().lower().encode("utf-8")).hexdigest()
        if context_hash in self.proactive.recent_initiative_hashes(owner):
            return

        self.proactive.add_initiative(owner, suggestion, context_hash)
        self.audit.record("initiative_created", owner, "system", owner, {"text": suggestion})

    @staticmethod
    def _build_context(owner: str, facts: list[str], history: list[dict]) -> str:
        parts = [f"Current time: {datetime.now().astimezone().isoformat()}"]
        if facts:
            parts.append(f"What you know about {owner}:\n" + "\n".join(f"- {fact}" for fact in facts))
        if history:
            transcript = "\n".join(f"{message['role']}: {message['content']}" for message in history)
            parts.append("Recent conversation:\n" + transcript)
        return "\n\n".join(parts)
