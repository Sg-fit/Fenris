"""Unit tests for InitiativeEngine against fake memory/semantic/provider
collaborators and a real (tmp-path) ProactiveStore — no live model, no
threads (calls _consider()/tick() directly)."""

import pytest

import backend.proactive.initiative as initiative_module
from backend.proactive.initiative import InitiativeEngine
from backend.proactive.store import ProactiveStore
from backend.settings import Settings


class FakeMemory:
    def __init__(self, owners, history=None):
        self._owners = list(owners)
        self._history = history or []

    def distinct_owners(self):
        return self._owners

    def history(self, owner, query, limit):
        return self._history


class FakeSemantic:
    def __init__(self, owners, facts=None):
        self._owners = list(owners)
        self._facts = facts or []

    def distinct_owners(self):
        return self._owners

    def facts(self, owner, limit=None):
        return self._facts


class FakeAudit:
    def __init__(self):
        self.records = []

    def record(self, *args, **kwargs):
        self.records.append((args, kwargs))


class FakeProvider:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.reply


@pytest.fixture
def store(tmp_path):
    return ProactiveStore(database_path=tmp_path / "engine_test.sqlite3")


def make_engine(store, owners=("loki",), facts=None, history=None):
    memory = FakeMemory(owners, history)
    semantic = FakeSemantic(owners, facts)
    audit = FakeAudit()
    return InitiativeEngine(memory, semantic, store, audit), audit


# -- generation -------------------------------------------------------------


def test_real_suggestion_is_stored(store):
    engine, audit = make_engine(store)
    provider = FakeProvider("You meant to email Sam yesterday — still want to?")

    engine._consider("loki", provider)

    assert store.pending_initiative_count("loki") == 1
    assert audit.records  # initiative_created was recorded


def test_none_reply_stores_nothing(store):
    engine, audit = make_engine(store)
    provider = FakeProvider("NONE")

    engine._consider("loki", provider)

    assert store.pending_initiative_count("loki") == 0
    assert audit.records == []


def test_empty_reply_stores_nothing(store):
    engine, _ = make_engine(store)
    provider = FakeProvider("   ")

    engine._consider("loki", provider)

    assert store.pending_initiative_count("loki") == 0


def test_duplicate_suggestion_is_deduped_not_stored_twice(store):
    engine, _ = make_engine(store)
    provider = FakeProvider("Call the dentist back")

    engine._consider("loki", provider)
    first_count = store.pending_initiative_count("loki")

    engine._last_considered.clear()  # bypass the rate limit to isolate dedup
    engine._consider("loki", provider)
    second_count = store.pending_initiative_count("loki")

    assert first_count == 1
    assert second_count == 1  # the repeat was skipped, not added again


# -- rate limiting / capping -------------------------------------------------


def test_rate_limit_skips_second_consideration_within_min_hours(store, monkeypatch):
    monkeypatch.setattr(Settings, "INITIATIVE_MIN_HOURS", 4)
    engine, _ = make_engine(store)
    provider = FakeProvider("Suggestion A")

    engine._consider("loki", provider)
    engine._consider("loki", provider)  # too soon

    assert len(provider.calls) == 1


def test_max_pending_blocks_new_considerations(store, monkeypatch):
    monkeypatch.setattr(Settings, "INITIATIVE_MAX_PENDING", 1)
    engine, _ = make_engine(store)
    store.add_initiative("loki", "already pending", "existing-hash")

    provider = FakeProvider("A new suggestion")
    engine._consider("loki", provider)

    assert provider.calls == []  # never even asked the model
    assert store.pending_initiative_count("loki") == 1  # still just the one


# -- owners / robustness -----------------------------------------------------


def test_known_owners_is_sorted_union_of_memory_and_semantic(store):
    memory = FakeMemory(["zack", "alex"])
    semantic = FakeSemantic(["alex", "loki"])
    engine = InitiativeEngine(memory, semantic, store, FakeAudit())

    assert engine._known_owners() == ["alex", "loki", "zack"]


def test_tick_never_raises_when_one_owner_fails(store, monkeypatch):
    class ExplodingMemory(FakeMemory):
        def history(self, owner, query, limit):
            raise RuntimeError("boom")

    memory = ExplodingMemory(["loki"])
    semantic = FakeSemantic(["loki"])
    audit = FakeAudit()
    engine = InitiativeEngine(memory, semantic, store, audit)

    class DummyProviderClass:
        def __init__(self, tool_runner=None):
            pass

        def complete(self, system, user):
            return "NONE"

    monkeypatch.setattr(initiative_module, "get_provider_class", lambda: DummyProviderClass)

    engine.tick()  # must not raise despite the owner's history() blowing up


def test_tick_is_noop_when_provider_unavailable(store, monkeypatch):
    memory = FakeMemory(["loki"])
    semantic = FakeSemantic(["loki"])
    audit = FakeAudit()
    engine = InitiativeEngine(memory, semantic, store, audit)

    class BrokenProviderClass:
        def __init__(self, tool_runner=None):
            raise RuntimeError("no api key configured")

    monkeypatch.setattr(initiative_module, "get_provider_class", lambda: BrokenProviderClass)

    engine.tick()  # must not raise

    assert store.pending_initiative_count("loki") == 0


# -- off by default ----------------------------------------------------------


def test_start_is_noop_when_initiative_disabled(monkeypatch):
    monkeypatch.setattr(Settings, "INITIATIVE", False)
    engine = InitiativeEngine(FakeMemory([]), FakeSemantic([]), None, FakeAudit())

    engine.start()

    assert engine._thread is None
