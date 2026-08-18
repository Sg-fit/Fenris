import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


AUDIT_PATH = Path("data") / "fenris_audit.sqlite3"
SENSITIVE_KEYS = {"password", "passcode", "pin", "token", "secret", "api_key", "authorization"}


def _redact(value):
    if isinstance(value, dict):
        return {key: "[redacted]" if key.lower() in SENSITIVE_KEYS else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class AuditLog:
    """Append-only local operational audit trail. It never stores conversation text."""

    def __init__(self, path: Path = AUDIT_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_name TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    target TEXT,
                    details TEXT NOT NULL
                )"""
            )

    def _connect(self):
        return sqlite3.connect(self.path)

    def record(self, event_type: str, actor_name: str, actor_role: str, target: str = "", details: dict | None = None) -> None:
        safe_details = json.dumps(_redact(details or {}), sort_keys=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO audit_events (occurred_at, event_type, actor_name, actor_role, target, details) VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), event_type, actor_name, actor_role, target, safe_details),
            )

    def recent(self, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT occurred_at, event_type, actor_name, actor_role, target, details FROM audit_events ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [
            {
                "occurred_at": occurred_at,
                "event_type": event_type,
                "actor_name": actor_name,
                "actor_role": actor_role,
                "target": target,
                "details": json.loads(details),
            }
            for occurred_at, event_type, actor_name, actor_role, target, details in rows
        ]
