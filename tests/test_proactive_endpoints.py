"""Tests for when-resolution, tool dispatch, and role checks around
reminders. Uses backend.main's real module-level singletons (same pattern as
test_memory_context.py) — always cleans up the test-namespaced actors it
touches so it doesn't leave residue in the real local database."""

import pytest
from fastapi.testclient import TestClient

from backend.main import _resolve_fire_at, _run_proactive_tool, app, proactive

client = TestClient(app)


# -- when resolution -----------------------------------------------------


def test_resolve_fire_at_in_minutes_is_close_to_now_plus_delta():
    from datetime import datetime, timedelta, timezone

    before = datetime.now(timezone.utc)
    fire_at = _resolve_fire_at(None, 10)
    parsed = datetime.fromisoformat(fire_at)
    after = datetime.now(timezone.utc)

    assert before + timedelta(minutes=10) <= parsed <= after + timedelta(minutes=10, seconds=2)


def test_resolve_fire_at_accepts_absolute_iso():
    fire_at = _resolve_fire_at("2030-01-01T12:00:00+00:00", None)
    assert fire_at.startswith("2030-01-01T12:00:00")


def test_resolve_fire_at_rejects_both_given():
    with pytest.raises(ValueError):
        _resolve_fire_at("2030-01-01T12:00:00+00:00", 10)


def test_resolve_fire_at_rejects_neither_given():
    with pytest.raises(ValueError):
        _resolve_fire_at(None, None)


def test_resolve_fire_at_rejects_non_positive_minutes():
    with pytest.raises(ValueError):
        _resolve_fire_at(None, 0)


def test_resolve_fire_at_rejects_invalid_iso_string():
    with pytest.raises(ValueError):
        _resolve_fire_at("not-a-date", None)


# -- tool dispatch ---------------------------------------------------------


def test_set_reminder_creates_a_row_for_the_actor():
    proactive.clear("test-actor-reminders-1")
    try:
        result = _run_proactive_tool(
            "set_reminder", {"text": "stretch", "in_minutes": 5}, "test-actor-reminders-1", "user", "session-1"
        )
        assert result["status"] == "complete"
        assert len(proactive.pending("test-actor-reminders-1")) == 1
    finally:
        proactive.clear("test-actor-reminders-1")


def test_set_reminder_guest_gets_error_result_and_no_row():
    proactive.clear("guest")
    try:
        result = _run_proactive_tool(
            "set_reminder", {"text": "stretch", "in_minutes": 5}, "guest", "guest", "session-1"
        )
        assert result["status"] == "error"
        assert proactive.pending("guest") == []
    finally:
        proactive.clear("guest")


def test_list_reminders_returns_pending_for_the_actor():
    proactive.clear("test-actor-reminders-2")
    try:
        _run_proactive_tool(
            "set_reminder", {"text": "call mom", "in_minutes": 30}, "test-actor-reminders-2", "user", "s1"
        )
        result = _run_proactive_tool("list_reminders", {}, "test-actor-reminders-2", "user", "s1")
        assert result["status"] == "complete"
        assert len(result["data"]["reminders"]) == 1
        assert result["data"]["reminders"][0]["text"] == "call mom"
    finally:
        proactive.clear("test-actor-reminders-2")


def test_cancel_reminder_removes_it():
    proactive.clear("test-actor-reminders-3")
    try:
        created = _run_proactive_tool(
            "set_reminder", {"text": "x", "in_minutes": 5}, "test-actor-reminders-3", "user", "s1"
        )
        reminder_id = created["data"]["id"]
        result = _run_proactive_tool(
            "cancel_reminder", {"reminder_id": reminder_id}, "test-actor-reminders-3", "user", "s1"
        )
        assert result["data"]["cancelled"] is True
        assert proactive.pending("test-actor-reminders-3") == []
    finally:
        proactive.clear("test-actor-reminders-3")


# -- /proactive/due role checks --------------------------------------------


def test_due_endpoint_denies_guest():
    response = client.get(
        "/proactive/due",
        params={"owner": "test-actor-reminders-4", "actor_name": "test-actor-reminders-4", "actor_role": "guest"},
    )
    assert response.status_code == 403


def test_due_endpoint_allows_owner():
    proactive.clear("test-actor-reminders-4")
    response = client.get(
        "/proactive/due",
        params={"owner": "test-actor-reminders-4", "actor_name": "test-actor-reminders-4", "actor_role": "user"},
    )
    assert response.status_code == 200
    assert response.json()["due"] == []


def test_due_endpoint_allows_admin_for_another_owner():
    proactive.clear("test-actor-reminders-5")
    response = client.get(
        "/proactive/due",
        params={"owner": "test-actor-reminders-5", "actor_name": "some-admin", "actor_role": "admin"},
    )
    assert response.status_code == 200


def test_due_endpoint_denies_non_owner_non_admin():
    response = client.get(
        "/proactive/due",
        params={"owner": "someone-elses-name", "actor_name": "test-actor-reminders-4", "actor_role": "user"},
    )
    assert response.status_code == 403


# -- /proactive/due merges reminders + initiatives ---------------------------


def test_due_endpoint_merges_reminders_and_initiatives_type_tagged():
    from backend.main import proactive as proactive_store

    owner = "test-actor-reminders-6"
    proactive_store.clear(owner)
    try:
        proactive_store.add(owner, "2024-01-01T00:00:00+00:00", "a reminder", "s1")
        proactive_store.add_initiative(owner, "an initiative", "hash-1")

        response = client.get(
            "/proactive/due", params={"owner": owner, "actor_name": owner, "actor_role": "user"}
        )

        assert response.status_code == 200
        due = response.json()["due"]
        types = {item["type"] for item in due}
        texts = {item["text"] for item in due}
        assert types == {"reminder", "initiative"}
        assert texts == {"a reminder", "an initiative"}

        # Both were marked delivered — a second poll returns nothing.
        second = client.get(
            "/proactive/due", params={"owner": owner, "actor_name": owner, "actor_role": "user"}
        )
        assert second.json()["due"] == []
    finally:
        proactive_store.clear(owner)
