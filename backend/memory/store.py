import sqlite3
from contextlib import closing
from pathlib import Path


DATABASE_PATH = Path("data") / "fenris_memory.sqlite3"


class MemoryStore:
    def __init__(self, database_path: Path = DATABASE_PATH):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_messages_owner_id ON messages(owner, id)")
            # Migrate databases created before sessions existed.
            columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)")}
            if "session_id" not in columns:
                connection.execute("ALTER TABLE messages ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def add(self, owner: str, role: str, content: str, session_id: str) -> int:
        """Returns the new row's id, so callers (e.g. semantic indexing) can
        link back to exactly this message."""
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO messages (owner, role, content, session_id) VALUES (?, ?, ?, ?)",
                (owner, role, content, session_id),
            )
            return cursor.lastrowid

    def history(self, owner: str, query: str | None = None, limit: int = 12) -> list[dict[str, str]]:
        limit = max(1, min(limit, 500))
        with closing(self._connect()) as connection:
            if query:
                rows = connection.execute(
                    "SELECT role, content FROM messages WHERE owner = ? AND content LIKE ? ORDER BY id DESC LIMIT ?",
                    (owner, f"%{query}%", limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT role, content FROM messages WHERE owner = ? ORDER BY id DESC LIMIT ?",
                    (owner, limit),
                ).fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def last_session(self, owner: str, exclude_session_id: str | None = None) -> tuple[str | None, list[dict[str, str]]]:
        """The most recent session (other than exclude_session_id) this owner
        has on record, and its messages in order. Powers the "pick up where we
        left off" prompt. Returns (None, []) if there's nothing to resume."""
        with closing(self._connect()) as connection:
            if exclude_session_id:
                row = connection.execute(
                    "SELECT session_id FROM messages WHERE owner = ? AND session_id != '' AND session_id != ? "
                    "ORDER BY id DESC LIMIT 1",
                    (owner, exclude_session_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT session_id FROM messages WHERE owner = ? AND session_id != '' ORDER BY id DESC LIMIT 1",
                    (owner,),
                ).fetchone()
            if not row:
                return None, []
            session_id = row[0]
            rows = connection.execute(
                "SELECT role, content FROM messages WHERE owner = ? AND session_id = ? ORDER BY id",
                (owner, session_id),
            ).fetchall()
        return session_id, [{"role": role, "content": content} for role, content in rows]

    def clear(self, owner: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM messages WHERE owner = ?", (owner,))

    def distinct_owners(self) -> list[str]:
        """Everyone with at least one stored message — guests are never
        written here, so this is naturally guest-free."""
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT DISTINCT owner FROM messages").fetchall()
        return [row[0] for row in rows]
