"""Unit tests for SemanticMemory. Uses a deterministic toy embedder injected
in place of the real embeddings API call, so no live embeddings server is
needed and ranking behavior is fully predictable."""

import numpy as np
import pytest

from backend.memory.semantic import SemanticMemory


def toy_embed(texts):
    """3-dim toy embedding: [cat-ness, car-ness, weather-ness]. Deterministic
    and good enough to test ranking/filtering without a real model."""
    vectors = []
    for text in texts:
        lowered = text.lower()
        vector = np.array(
            [
                float("cat" in lowered),
                float("car" in lowered),
                float("weather" in lowered or "rain" in lowered or "sunny" in lowered),
            ],
            dtype=np.float32,
        )
        norm = np.linalg.norm(vector)
        vectors.append(vector / norm if norm > 0 else vector)
    return vectors


@pytest.fixture
def memory(tmp_path):
    store = SemanticMemory(database_path=tmp_path / "semantic_test.sqlite3")
    store.embed = toy_embed  # inject the deterministic embedder
    return store


def test_retrieve_ranks_closest_first(memory):
    memory.index_message("loki", "1", "I love my cat Whiskers")
    memory.index_message("loki", "2", "I just bought a new car")
    memory.index_message("loki", "3", "The weather is sunny today")

    results = memory.retrieve("loki", "tell me about my cat", k=3, min_score=0.0)

    assert results[0]["text"] == "I love my cat Whiskers"
    assert results[0]["score"] == pytest.approx(1.0)


def test_retrieve_filters_by_min_score(memory):
    memory.index_message("loki", "1", "I love my cat Whiskers")
    memory.index_message("loki", "2", "I just bought a new car")

    # A weather query has zero overlap with either indexed text -> score 0.
    results = memory.retrieve("loki", "what's the weather like", k=5, min_score=0.5)

    assert results == []


def test_retrieve_empty_store_returns_empty_list(memory):
    assert memory.retrieve("loki", "anything at all", k=5, min_score=0.0) == []


def test_retrieve_is_isolated_per_owner(memory):
    memory.index_message("loki", "1", "I love my cat Whiskers")
    memory.index_message("alex", "1", "I love my cat too")

    results = memory.retrieve("loki", "tell me about my cat", k=5, min_score=0.0)

    assert len(results) == 1
    assert all(r["text"] == "I love my cat Whiskers" for r in results)


def test_remember_fact_dedups_on_owner_and_text(memory):
    assert memory.remember_fact("loki", "Loki has a cat named Whiskers", "session-1") is True
    assert memory.remember_fact("loki", "Loki has a cat named Whiskers", "session-1") is False
    assert memory.facts("loki") == ["Loki has a cat named Whiskers"]


def test_clear_empties_both_facts_and_embeddings(memory):
    memory.remember_fact("loki", "Loki has a cat named Whiskers", "session-1")
    memory.index_message("loki", "msg-1", "some unrelated message text")

    memory.clear("loki")

    assert memory.facts("loki") == []
    assert memory.retrieve("loki", "cat", k=5, min_score=0.0) == []


def test_fail_soft_when_embed_endpoint_unreachable(tmp_path):
    broken = SemanticMemory(database_path=tmp_path / "broken_test.sqlite3")

    def broken_client():
        raise RuntimeError("connection refused")

    broken._client = broken_client

    assert broken.embed(["hello"]) is None
    broken.index_message("loki", "1", "hello")  # must not raise
    assert broken.retrieve("loki", "hello", k=5, min_score=0.0) == []
    # The fact itself is plain SQL — it survives even though embedding failed.
    assert broken.remember_fact("loki", "Loki likes hiking", "session-1") is True
    assert broken.facts("loki") == ["Loki likes hiking"]
