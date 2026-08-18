import threading


class MissionStore:
    """Holds paused mid-mission conversations, keyed by actor, so the next
    request from that person can resume exactly where it left off instead of
    starting a fresh conversation. In-memory only, same durability as the
    client's own per-session conversation memory — nothing here survives a
    backend restart."""

    def __init__(self):
        self._lock = threading.Lock()
        self._paused: dict[tuple[str, str], list[dict]] = {}

    def save(self, actor_name: str, actor_role: str, conversation: list[dict]) -> None:
        with self._lock:
            self._paused[(actor_name, actor_role)] = conversation

    def pop(self, actor_name: str, actor_role: str) -> list[dict] | None:
        with self._lock:
            return self._paused.pop((actor_name, actor_role), None)

    def clear(self, actor_name: str, actor_role: str) -> None:
        with self._lock:
            self._paused.pop((actor_name, actor_role), None)
