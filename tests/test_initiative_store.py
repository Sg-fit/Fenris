from backend.proactive.store import ProactiveStore


def make_store(tmp_path):
    return ProactiveStore(database_path=tmp_path / "initiative_test.sqlite3")


def test_add_and_due_initiatives_marks_delivered(tmp_path):
    store = make_store(tmp_path)
    store.add_initiative("loki", "you meant to email Sam", "hash1")

    first = store.due_initiatives("loki")
    assert len(first) == 1
    assert first[0]["text"] == "you meant to email Sam"

    second = store.due_initiatives("loki")
    assert second == []


def test_recent_initiative_hashes_for_dedup(tmp_path):
    store = make_store(tmp_path)
    store.add_initiative("loki", "suggestion one", "hash1")
    store.add_initiative("loki", "suggestion two", "hash2")

    hashes = store.recent_initiative_hashes("loki")
    assert set(hashes) == {"hash1", "hash2"}


def test_pending_initiative_count(tmp_path):
    store = make_store(tmp_path)
    assert store.pending_initiative_count("loki") == 0

    store.add_initiative("loki", "suggestion", "hash1")
    assert store.pending_initiative_count("loki") == 1

    store.due_initiatives("loki")  # delivers it
    assert store.pending_initiative_count("loki") == 0


def test_clear_wipes_initiatives_too(tmp_path):
    store = make_store(tmp_path)
    store.add("loki", "2099-01-01T00:00:00+00:00", "a reminder", "s1")
    store.add_initiative("loki", "a suggestion", "hash1")

    store.clear("loki")

    assert store.pending("loki") == []
    assert store.pending_initiative_count("loki") == 0


def test_initiatives_are_per_owner_isolated(tmp_path):
    store = make_store(tmp_path)
    store.add_initiative("loki", "loki's suggestion", "hash1")
    store.add_initiative("alex", "alex's suggestion", "hash1")  # same hash, different owner

    assert store.pending_initiative_count("loki") == 1
    assert store.pending_initiative_count("alex") == 1
    assert "hash1" in store.recent_initiative_hashes("loki")
    assert store.recent_initiative_hashes("someone-else") == []
