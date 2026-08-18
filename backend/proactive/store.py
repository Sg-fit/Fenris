import sqlite3
from contextlib import closing
from pathlib import Path

from backend.memory.store import DATABASE_PATH


class ProactiveStore:
    """Scheduled reminders and self-generated initiatives — same SQLite file
    as the other memory stores. Reminder times are stored/compared as ISO
    8601 UTC strings throughout (they sort lexically the same as
    chronologically). Strict per-owner isolation everywhere."""

    def __init__(self, database_path: Path = DATABASE_PATH):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    fire_at TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_session TEXT NOT NULL DEFAULT '',
                    delivered INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_owner_delivered_fire "
                "ON reminders(owner, delivered, fire_at)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS initiatives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    text TEXT NOT NULL,
                    context_hash TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_initiatives_owner_delivered ON initiatives(owner, delivered)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    # -- reminders ----------------------------------------------------------

    def add(self, owner: str, fire_at_iso: str, text: str, created_session: str) -> int:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO reminders (owner, fire_at, text, created_session) VALUES (?, ?, ?, ?)",
                (owner, fire_at_iso, text, created_session),
            )
            return cursor.lastrowid

    def due(self, owner: str, now_iso: str) -> list[dict]:
        """Undelivered reminders at or before now_iso — atomically marked
        delivered in the same transaction, so a second poll (or a retry after
        a dropped response) never re-delivers the same reminder."""
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT id, text, fire_at FROM reminders "
                "WHERE owner = ? AND delivered = 0 AND fire_at <= ? ORDER BY fire_at",
                (owner, now_iso),
            ).fetchall()
            if rows:
                ids = [row[0] for row in rows]
                placeholders = ",".join("?" * len(ids))
                connection.execute(f"UPDATE reminders SET delivered = 1 WHERE id IN ({placeholders})", ids)
        return [{"id": row[0], "text": row[1], "fire_at": row[2]} for row in rows]

    def pending(self, owner: str) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, text, fire_at FROM reminders WHERE owner = ? AND delivered = 0 ORDER BY fire_at",
                (owner,),
            ).fetchall()
        return [{"id": row[0], "text": row[1], "fire_at": row[2]} for row in rows]

    def cancel(self, owner: str, reminder_id: int) -> bool:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute("DELETE FROM reminders WHERE owner = ? AND id = ?", (owner, reminder_id))
            return cursor.rowcount > 0

    # -- initiatives ----------------------------------------------------

    def add_initiative(self, owner: str, text: str, context_hash: str) -> int:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO initiatives (owner, text, context_hash) VALUES (?, ?, ?)",
                (owner, text, context_hash),
            )
            return cursor.lastrowid

    def due_initiatives(self, owner: str, now_iso: str | None = None) -> list[dict]:
        """All of this owner's undelivered initiatives — atomically marked
        delivered, same pattern as due(). Unlike reminders, an initiative has
        no scheduled fire time: it becomes due the moment it's created, so
        now_iso is accepted only for symmetry with due() and isn't used to
        filter."""
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT id, text FROM initiatives WHERE owner = ? AND delivered = 0 ORDER BY id", (owner,)
            ).fetchall()
            if rows:
                ids = [row[0] for row in rows]
                placeholders = ",".join("?" * len(ids))
                connection.execute(f"UPDATE initiatives SET delivered = 1 WHERE id IN ({placeholders})", ids)
        return [{"id": row[0], "text": row[1]} for row in rows]

    def recent_initiative_hashes(self, owner: str, limit: int = 20) -> list[str]:
        """Recent context_hashes (delivered or not) for this owner, most
        recent first — used to dedup so the same idea isn't raised twice."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT context_hash FROM initiatives WHERE owner = ? ORDER BY id DESC LIMIT ?", (owner, limit)
            ).fetchall()
        return [row[0] for row in rows]

    def pending_initiative_count(self, owner: str) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM initiatives WHERE owner = ? AND delivered = 0", (owner,)
            ).fetchone()
        return row[0] if row else 0

    # -- shared ---------------------------------------------------------

    def clear(self, owner: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM reminders WHERE owner = ?", (owner,))
            connection.execute("DELETE FROM initiatives WHERE owner = ?", (owner,))
