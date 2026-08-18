from backend.main import _build_memory_context


def test_build_memory_context_empty_returns_none():
    assert _build_memory_context("Loki", [], []) is None


def test_build_memory_context_includes_facts_and_hits():
    facts = ["Loki has a cat named Whiskers"]
    hits = [{"text": "Loki mentioned moving to Seattle", "kind": "message", "score": 0.9}]

    context = _build_memory_context("Loki", facts, hits)

    assert context is not None
    assert "Loki has a cat named Whiskers" in context
    assert "Loki mentioned moving to Seattle" in context


def test_build_memory_context_facts_only():
    context = _build_memory_context("Loki", ["Loki prefers dark mode"], [])
    assert context is not None
    assert "Loki prefers dark mode" in context


def test_build_memory_context_hits_only():
    hits = [{"text": "Talked about a Seattle trip", "kind": "message", "score": 0.6}]
    context = _build_memory_context("Loki", [], hits)
    assert context is not None
    assert "Talked about a Seattle trip" in context
