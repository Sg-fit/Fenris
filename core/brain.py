import json
from typing import Callable

import requests

from config import Config


class Brain:
    """Desktop-side client for Fenris's local brain API."""

    @property
    def available(self) -> bool:
        return Config.ASSISTANT_MODE != "offline"

    def reply(
        self,
        messages: list[dict[str, str]],
        actor_name: str = "guest",
        actor_role: str = "guest",
        images: list | None = None,
        on_event: Callable[[dict], None] | None = None,
        session_id: str = "",
    ) -> str:
        """Send a turn to the backend and return its final spoken text.

        The backend streams newline-delimited JSON events as a mission
        progresses. Every event (including the terminal "question" or
        "result") is passed to on_event as it arrives, so a caller can speak
        progress narration immediately and track whether the turn ended on a
        question (mission paused, awaiting an answer) rather than a finished
        result. The return value is always the text of that terminal event.

        session_id groups this and future turns into one continuous run for
        persistent storage (see last_session()) — independent of how much
        live context is sent in messages.
        """
        if Config.ASSISTANT_MODE == "offline":
            return "I am in offline mode. I can still use my built-in local commands."
        try:
            response = requests.post(
                f"{Config.BACKEND_URL}/chat",
                json={
                    "messages": messages,
                    "actor_name": actor_name,
                    "actor_role": actor_role,
                    "images": images or [],
                    "session_id": session_id,
                },
                # Missions can run for minutes; keep the connect timeout short
                # but give the read side plenty of room.
                timeout=(10, 600),
                stream=True,
            )
            response.raise_for_status()
            try:
                final_text = None
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if event.get("type") in {"question", "result"}:
                        final_text = event.get("text", "")
                    if on_event is not None:
                        on_event(event)
                return final_text if final_text is not None else "I didn't get a reply."
            finally:
                response.close()
        except requests.ConnectionError:
            return "My local brain service is not running. Start it with: uvicorn backend.main:app --host 127.0.0.1 --port 8000."
        except (requests.RequestException, KeyError, ValueError) as error:
            print(f"[Brain API error] {error}")
            return "My local brain service could not complete that request."

    def memory_history(self, owner: str, actor_name: str, actor_role: str) -> list[dict[str, str]]:
        if actor_role == "guest" or Config.ASSISTANT_MODE == "offline":
            return []
        try:
            response = requests.get(
                f"{Config.BACKEND_URL}/memory/{owner}",
                params={"actor_name": actor_name, "actor_role": actor_role, "limit": Config.MAX_HISTORY_MESSAGES},
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("messages", [])
        except requests.RequestException:
            return []

    def last_session(self, owner: str, actor_name: str, actor_role: str) -> tuple[str | None, list[dict[str, str]]]:
        """The most recent prior session on record for this owner, if any —
        used to offer "pick up where we left off" on a fresh run."""
        if actor_role == "guest" or Config.ASSISTANT_MODE == "offline":
            return None, []
        try:
            response = requests.get(
                f"{Config.BACKEND_URL}/memory/{owner}/last-session",
                params={"actor_name": actor_name, "actor_role": actor_role},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("session_id"), data.get("messages", [])
        except requests.RequestException:
            return None, []

    def clear_memory(self, owner: str, actor_name: str, actor_role: str) -> bool:
        if actor_role == "guest" or Config.ASSISTANT_MODE == "offline":
            return False
        try:
            response = requests.delete(
                f"{Config.BACKEND_URL}/memory/{owner}",
                params={"actor_name": actor_name, "actor_role": actor_role},
                timeout=10,
            )
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False

    def due_reminders(self, owner: str, actor_name: str, actor_role: str) -> list[dict]:
        """Reminders and (if enabled) self-generated initiatives that just
        came due for this person, each dict tagged type="reminder"|
        "initiative" — the backend marks them delivered as part of returning
        them, so a poll failure here (backend down, network blip) is
        swallowed and just retried next tick, same as memory_history/
        last_session."""
        if actor_role == "guest" or Config.ASSISTANT_MODE == "offline":
            return []
        try:
            response = requests.get(
                f"{Config.BACKEND_URL}/proactive/due",
                params={"owner": owner, "actor_name": actor_name, "actor_role": actor_role},
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("due", [])
        except requests.RequestException:
            return []
