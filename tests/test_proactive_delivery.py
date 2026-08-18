"""Unit tests for ProactiveDelivery against a fake assistant/brain/speaker
and an injected clock — no real backend, no wall-clock dependency, no
threads (calls run_once() directly)."""

from datetime import datetime

from config import Config
from core.proactive import ProactiveDelivery


class FakeIdentity:
    def __init__(self, name, role):
        self.name = name
        self.role = role


class FakeSpeaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


class FakeHud:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


class FakeBrain:
    def __init__(self, due_items=None, raise_error=False):
        self._due_items = due_items or []
        self._raise_error = raise_error
        self.calls = 0

    def due_reminders(self, owner, actor_name, actor_role):
        self.calls += 1
        if self._raise_error:
            raise RuntimeError("backend unreachable")
        return self._due_items


class FakeAssistant:
    def __init__(self, identity, brain, busy=False):
        self._identity = identity
        self.brain = brain
        self.speaker = FakeSpeaker()
        self.hud = FakeHud()
        self._busy = busy

    def _typed_identity(self):
        return self._identity

    def turn_in_progress(self):
        return self._busy


NOON = lambda: datetime(2024, 1, 1, 12, 0)  # noqa: E731 — well outside default quiet hours
LATE_NIGHT = lambda: datetime(2024, 1, 1, 23, 0)  # noqa: E731 — inside default 22:00-08:00 quiet hours


def _set_default_quiet_hours(monkeypatch):
    monkeypatch.setattr(Config, "PROACTIVE_QUIET_START", "22:00")
    monkeypatch.setattr(Config, "PROACTIVE_QUIET_END", "08:00")


def test_due_item_is_spoken(monkeypatch):
    _set_default_quiet_hours(monkeypatch)
    identity = FakeIdentity("loki", "admin")
    brain = FakeBrain(due_items=[{"id": 1, "text": "stretch", "fire_at": "2024-01-01T12:00:00+00:00"}])
    assistant = FakeAssistant(identity, brain)
    delivery = ProactiveDelivery(assistant, clock=NOON)

    delivery.run_once()

    assert assistant.speaker.spoken == ["Reminder — stretch"]


def test_multiple_due_items_are_all_spoken(monkeypatch):
    _set_default_quiet_hours(monkeypatch)
    identity = FakeIdentity("loki", "admin")
    brain = FakeBrain(
        due_items=[
            {"id": 1, "text": "stretch", "fire_at": "..."},
            {"id": 2, "text": "drink water", "fire_at": "..."},
        ]
    )
    assistant = FakeAssistant(identity, brain)
    delivery = ProactiveDelivery(assistant, clock=NOON)

    delivery.run_once()

    assert assistant.speaker.spoken == ["Reminder — stretch", "Reminder — drink water"]


def test_quiet_hours_suppress_speech_and_skip_the_poll(monkeypatch):
    _set_default_quiet_hours(monkeypatch)
    identity = FakeIdentity("loki", "admin")
    brain = FakeBrain(due_items=[{"id": 1, "text": "stretch", "fire_at": "..."}])
    assistant = FakeAssistant(identity, brain)
    delivery = ProactiveDelivery(assistant, clock=LATE_NIGHT)

    delivery.run_once()

    assert assistant.speaker.spoken == []
    assert brain.calls == 0  # never even polled the backend


def test_active_turn_suppresses_speech_and_skips_the_poll(monkeypatch):
    _set_default_quiet_hours(monkeypatch)
    identity = FakeIdentity("loki", "admin")
    brain = FakeBrain(due_items=[{"id": 1, "text": "stretch", "fire_at": "..."}])
    assistant = FakeAssistant(identity, brain, busy=True)
    delivery = ProactiveDelivery(assistant, clock=NOON)

    delivery.run_once()

    assert assistant.speaker.spoken == []
    assert brain.calls == 0


def test_backend_error_is_swallowed_not_raised(monkeypatch):
    _set_default_quiet_hours(monkeypatch)
    identity = FakeIdentity("loki", "admin")
    brain = FakeBrain(raise_error=True)
    assistant = FakeAssistant(identity, brain)
    delivery = ProactiveDelivery(assistant, clock=NOON)

    delivery.run_once()  # must not raise

    assert assistant.speaker.spoken == []


def test_guest_identity_is_never_polled(monkeypatch):
    _set_default_quiet_hours(monkeypatch)
    identity = FakeIdentity("guest", "guest")
    brain = FakeBrain(due_items=[{"id": 1, "text": "stretch", "fire_at": "..."}])
    assistant = FakeAssistant(identity, brain)
    delivery = ProactiveDelivery(assistant, clock=NOON)

    delivery.run_once()

    assert brain.calls == 0
    assert assistant.speaker.spoken == []


def test_no_due_items_speaks_nothing(monkeypatch):
    _set_default_quiet_hours(monkeypatch)
    identity = FakeIdentity("loki", "admin")
    brain = FakeBrain(due_items=[])
    assistant = FakeAssistant(identity, brain)
    delivery = ProactiveDelivery(assistant, clock=NOON)

    delivery.run_once()

    assert assistant.speaker.spoken == []
