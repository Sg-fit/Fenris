import threading
from datetime import datetime
from datetime import time as dtime

from config import Config


class ProactiveDelivery:
    """Background thread that polls the backend for due items and speaks
    them unprompted — no wake word, no active turn. This is purely the
    delivery mechanism; it doesn't decide what's worth saying (that's
    reminders you set explicitly, and — if enabled — Fenris's own initiative
    engine considering what it knows about you; /proactive/due returns both,
    type-tagged, and this loop doesn't need to care which is which beyond
    picking a lead-in).

    Never talks over the user: skipped entirely while a turn is active, and
    during quiet hours. Poll failures (backend down) are swallowed and
    retried next tick — this thread must never crash the app."""

    def __init__(self, assistant, clock=datetime.now):
        self.assistant = assistant
        self._clock = clock  # injectable for deterministic quiet-hours tests
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not Config.PROACTIVE_ENABLED:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(Config.PROACTIVE_POLL_SECONDS)

    def run_once(self) -> None:
        """One poll cycle, with the same error containment as the background
        loop — exposed separately so it's directly testable without threads."""
        try:
            self._tick()
        except Exception as error:  # this thread must never die
            print(f"[Proactive] delivery tick failed: {error}")

    def _tick(self) -> None:
        speaker = self.assistant._typed_identity()
        if speaker.role == "guest":
            return
        if self._in_quiet_hours():
            return
        if self.assistant.turn_in_progress():
            return

        due = self.assistant.brain.due_reminders(speaker.name, speaker.name, speaker.role)
        if not due:
            return

        for item in due:
            lead_in = "By the way —" if item.get("type") == "initiative" else "Reminder —"
            self.assistant.speaker.speak(f"{lead_in} {item['text']}")
        self.assistant.hud.publish({"type": "state", "value": "listening"})

    @staticmethod
    def _parse_hhmm(value: str) -> dtime:
        hour, minute = value.split(":")
        return dtime(int(hour), int(minute))

    def _in_quiet_hours(self) -> bool:
        start = self._parse_hhmm(Config.PROACTIVE_QUIET_START)
        end = self._parse_hhmm(Config.PROACTIVE_QUIET_END)
        now = self._clock().time()
        if start <= end:
            return start <= now < end
        return now >= start or now < end  # window wraps past midnight
