import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np

from backend.memory.store import DATABASE_PATH
from backend.settings import Settings


class SemanticMemory:
    """Durable, per-person facts plus vector recall of past messages/facts —
    lives in the same SQLite file as MemoryStore. Brute-force numpy cosine
    ranking is plenty at personal scale; no vector DB needed. Every method is
    fail-soft around the embeddings endpoint: if it's unreachable, callers get
    an empty/None result (logged once) instead of an exception."""

    def __init__(self, database_path: Path = DATABASE_PATH):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._openai_client = None
        self._warned = False
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS mem_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source_session TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner, text)
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_mem_facts_owner ON mem_facts(owner)")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS mem_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('message', 'fact')),
                    ref_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_mem_embeddings_owner ON mem_embeddings(owner)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _warn_once(self, message: str) -> None:
        if not self._warned:
            print(f"[SemanticMemory] {message}")
            self._warned = True

    def _client(self):
        if self._openai_client is None:
            from openai import OpenAI

            self._openai_client = OpenAI(base_url=Settings.EMBED_BASE_URL, api_key=Settings.EMBED_API_KEY)
        return self._openai_client

    def embed(self, texts: list[str]) -> list[np.ndarray] | None:
        """Unit-normalized embedding vectors for texts, one API call. None on
        any failure (endpoint down, package missing, bad response) — callers
        must treat that as "no semantic memory available right now", not an
        error to propagate."""
        if not texts:
            return []
        try:
            response = self._client().embeddings.create(model=Settings.EMBED_MODEL, input=texts)
        except Exception as error:
            self._warn_once(f"Embeddings endpoint unreachable ({Settings.EMBED_BASE_URL}): {error}")
            return None
        vectors = []
        for item in response.data:
            vector = np.array(item.embedding, dtype=np.float32)
            norm = np.linalg.norm(vector)
            vectors.append(vector / norm if norm > 0 else vector)
        return vectors

    def _index(self, owner: str, kind: str, ref_id: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        vectors = self.embed([text])
        if not vectors:
            return
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO mem_embeddings (owner, kind, ref_id, text, vector) VALUES (?, ?, ?, ?, ?)",
                (owner, kind, ref_id, text, vectors[0].tobytes()),
            )

    def index_message(self, owner: str, ref_id: str, text: str) -> None:
        self._index(owner, "message", ref_id, text)

    def index_fact(self, owner: str, ref_id: str, text: str) -> None:
        self._index(owner, "fact", ref_id, text)

    def remember_fact(self, owner: str, text: str, source_session: str) -> bool:
        """Insert a durable fact, deduped on (owner, text). Returns whether it
        was actually new (already-known facts are silently no-ops)."""
        text = (text or "").strip()
        if not text:
            return False
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO mem_facts (owner, text, source_session) VALUES (?, ?, ?)",
                (owner, text, source_session),
            )
            is_new = cursor.rowcount > 0
            fact_id = cursor.lastrowid
        if is_new:
            self.index_fact(owner, str(fact_id), text)
        return is_new

    def retrieve(self, owner: str, query: str, k: int | None = None, min_score: float | None = None) -> list[dict]:
        """Top-k (text, kind, score) semantically nearest to query for this
        owner, above min_score. [] if there's nothing indexed or embedding
        failed — never raises."""
        k = Settings.MEMORY_TOPK if k is None else k
        min_score = Settings.MEMORY_MIN_SCORE if min_score is None else min_score
        if not query or not query.strip():
            return []
        query_vectors = self.embed([query])
        if not query_vectors:
            return []
        query_vector = query_vectors[0]

        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT kind, text, vector FROM mem_embeddings WHERE owner = ?", (owner,)
            ).fetchall()
        if not rows:
            return []

        scored = []
        for kind, text, vector_blob in rows:
            vector = np.frombuffer(vector_blob, dtype=np.float32)
            # Both sides are already unit-normalized, so the dot product is
            # the cosine similarity directly.
            score = float(np.dot(query_vector, vector))
            if score >= min_score:
                scored.append({"text": text, "kind": kind, "score": score})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:k]

    def facts(self, owner: str, limit: int | None = None) -> list[str]:
        limit = Settings.MEMORY_FACT_CAP if limit is None else limit
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT text FROM mem_facts WHERE owner = ? ORDER BY id DESC LIMIT ?", (owner, limit)
            ).fetchall()
        return [row[0] for row in reversed(rows)]

    def clear(self, owner: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM mem_facts WHERE owner = ?", (owner,))
            connection.execute("DELETE FROM mem_embeddings WHERE owner = ?", (owner,))

    def distinct_owners(self) -> list[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT DISTINCT owner FROM mem_facts").fetchall()
        return [row[0] for row in rows]
