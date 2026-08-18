from backend.proactive.store import ProactiveStore


def make_store(tmp_path):
    return ProactiveStore(database_path=tmp_path / "proactive_test.sqlite3")


def test_add_and_due_marks_delivered_so_second_call_returns_nothing(tmp_path):
    store = make_store(tmp_path)
    store.add("loki", "2024-01-01T00:00:00+00:00", "stretch", "session-1")

    first = store.due("loki", "2024-01-01T00:05:00+00:00")
    assert len(first) == 1
    assert first[0]["text"] == "stretch"

    second = store.due("loki", "2024-01-01T00:10:00+00:00")
    assert second == []


def test_due_excludes_future_reminders(tmp_path):
    store = make_store(tmp_path)
    store.add("loki", "2099-01-01T00:00:00+00:00", "far future", "session-1")

    assert store.due("loki", "2024-01-01T00:00:00+00:00") == []


def test_pending_excludes_delivered(tmp_path):
    store = make_store(tmp_path)
    store.add("loki", "2024-01-01T00:00:00+00:00", "stretch", "session-1")
    store.add("loki", "2099-01-01T00:00:00+00:00", "far future", "session-1")

    store.due("loki", "2024-06-01T00:00:00+00:00")  # delivers the first one only

    pending = store.pending("loki")
    assert len(pending) == 1
    assert pending[0]["text"] == "far future"


def test_cancel_removes_reminder(tmp_path):
    store = make_store(tmp_path)
    reminder_id = store.add("loki", "2099-01-01T00:00:00+00:00", "far future", "session-1")

    assert store.cancel("loki", reminder_id) is True
    assert store.pending("loki") == []
    assert store.cancel("loki", reminder_id) is False  # already gone


def test_per_owner_isolation(tmp_path):
    store = make_store(tmp_path)
    store.add("loki", "2024-01-01T00:00:00+00:00", "loki's reminder", "session-1")
    store.add("alex", "2024-01-01T00:00:00+00:00", "alex's reminder", "session-1")

    loki_due = store.due("loki", "2024-06-01T00:00:00+00:00")

    assert len(loki_due) == 1
    assert loki_due[0]["text"] == "loki's reminder"
    assert len(store.pending("alex")) == 1  # untouched by loki's poll


def test_clear_empties_owner_only(tmp_path):
    store = make_store(tmp_path)
    store.add("loki", "2099-01-01T00:00:00+00:00", "loki's reminder", "session-1")
    store.add("alex", "2099-01-01T00:00:00+00:00", "alex's reminder", "session-1")

    store.clear("loki")

    assert store.pending("loki") == []
    assert len(store.pending("alex")) == 1
