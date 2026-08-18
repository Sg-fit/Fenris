class ConversationMemory:
    """Keeps the current session's transcript in memory, untrimmed — a
    session (app open to close) is meant to be one continuous conversation,
    not a rolling window."""

    def __init__(self):
        self.messages: list[dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def clear(self) -> None:
        self.messages.clear()

    def load(self, messages: list[dict[str, str]]) -> None:
        """Replace session memory with validated history loaded from the backend."""
        self.messages = [
            {"role": item["role"], "content": item["content"]}
            for item in messages
            if item.get("role") in {"user", "assistant"} and isinstance(item.get("content"), str)
        ]
