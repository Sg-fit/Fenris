from datetime import datetime


class SkillManager:
    """Local, deterministic commands that need no network access."""

    def handle(self, text: str) -> str | None:
        command = text.lower().strip()

        if command in {"what time is it", "what's the time", "tell me the time", "time"}:
            return datetime.now().strftime("It is %I:%M %p.").replace(" 0", " ")

        if command in {"help", "what can you do", "commands"}:
            return (
                "I can chat, remember the current conversation, tell you the time, "
                "and clear our conversation. Say goodbye or exit to stop me."
            )

        return None
