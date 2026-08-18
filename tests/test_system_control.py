"""Tests for the system_control add-on. The headline property under test:
an unconfirmed mutating call must never reach subprocess or the filesystem —
verified by patching both and asserting they're never invoked, not just by
checking the returned status."""

import subprocess

import pytest

from addons.manager import AddonManager
from addons.system_control import MAX_WRITE_BYTES, SystemControlAddon
from backend.settings import Settings


@pytest.fixture
def addon():
    return SystemControlAddon()


# -- open_app ---------------------------------------------------------------


def test_open_app_not_configured_when_allow_list_empty(addon, monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_APPS", {})
    result = addon.run("loki", "admin", "open_app", {"app": "notepad"}, True)
    assert result.status == "not configured"


def test_open_app_unconfirmed_does_not_launch(addon, monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_APPS", {"notepad": "notepad.exe"})
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append((a, k)))

    result = addon.run("loki", "admin", "open_app", {"app": "notepad"}, False)

    assert result.status == "confirmation_required"
    assert calls == []


def test_open_app_confirmed_launches_the_allow_listed_exe(addon, monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_APPS", {"notepad": "notepad.exe"})
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: calls.append(argv))

    result = addon.run("loki", "admin", "open_app", {"app": "notepad"}, True)

    assert result.status == "complete"
    assert calls == [["notepad.exe"]]


def test_open_app_unknown_app_refused_and_never_launched(addon, monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_APPS", {"notepad": "notepad.exe"})
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a))

    result = addon.run("loki", "admin", "open_app", {"app": "totally_unlisted"}, True)

    assert result.status == "invalid"
    assert calls == []


# -- run_command --------------------------------------------------------------


def test_run_command_not_configured_when_allow_list_empty(addon, monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_COMMANDS", {})
    result = addon.run("loki", "admin", "run_command", {"command_id": "ipconfig"}, True)
    assert result.status == "not configured"


def test_run_command_unconfirmed_does_not_run(addon, monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_COMMANDS", {"ipconfig": "ipconfig /all"})
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))

    result = addon.run("loki", "admin", "run_command", {"command_id": "ipconfig"}, False)

    assert result.status == "confirmation_required"
    assert calls == []


def test_run_command_confirmed_uses_argv_list_and_never_shell(addon, monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_COMMANDS", {"ipconfig": "ipconfig /all"})
    calls = []

    class FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = addon.run("loki", "admin", "run_command", {"command_id": "ipconfig"}, True)

    assert result.status == "complete"
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert isinstance(argv, list)
    assert argv == ["ipconfig", "/all"]
    assert kwargs.get("shell") is False


def test_run_command_appends_extra_args_to_template(addon, monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_COMMANDS", {"ping_google": "ping -n 4 google.com"})
    calls = []

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda argv, **k: calls.append(argv) or FakeCompleted())

    addon.run("loki", "admin", "run_command", {"command_id": "ping_google", "args": ["-w", "500"]}, True)

    assert calls == [["ping", "-n", "4", "google.com", "-w", "500"]]


def test_run_command_unknown_id_refused_and_never_run(addon, monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_COMMANDS", {"ipconfig": "ipconfig /all"})
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))

    result = addon.run("loki", "admin", "run_command", {"command_id": "not_a_real_command"}, True)

    assert result.status == "invalid"
    assert calls == []


def test_run_command_rejects_shell_metacharacters_in_args(addon, monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_COMMANDS", {"ping_google": "ping -n 4 google.com"})
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))

    result = addon.run(
        "loki", "admin", "run_command", {"command_id": "ping_google", "args": ["; rm -rf /"]}, True
    )

    assert result.status == "invalid"
    assert calls == []


# -- write_file / append_file ---------------------------------------------


def test_write_file_not_configured_when_allow_list_empty(addon, monkeypatch):
    monkeypatch.setattr(Settings, "WRITABLE_FOLDERS", [])
    result = addon.run("loki", "admin", "write_file", {"path": "notes.txt", "content": "hi"}, True)
    assert result.status == "not configured"


def test_write_file_outside_allowed_folder_refused(addon, monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside" / "secret.txt"
    monkeypatch.setattr(Settings, "WRITABLE_FOLDERS", [allowed])

    result = addon.run("loki", "admin", "write_file", {"path": str(outside), "content": "hi"}, True)

    assert result.status == "invalid"
    assert not outside.exists()


def test_write_file_unconfirmed_does_not_write(addon, monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(Settings, "WRITABLE_FOLDERS", [allowed])
    target = allowed / "notes.txt"

    result = addon.run("loki", "admin", "write_file", {"path": str(target), "content": "hi"}, False)

    assert result.status == "confirmation_required"
    assert not target.exists()


def test_write_file_confirmed_inside_allowed_folder_writes(addon, monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(Settings, "WRITABLE_FOLDERS", [allowed])
    target = allowed / "notes.txt"

    result = addon.run("loki", "admin", "write_file", {"path": str(target), "content": "hello"}, True)

    assert result.status == "complete"
    assert target.read_text(encoding="utf-8") == "hello"


def test_append_file_unconfirmed_does_not_write(addon, monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(Settings, "WRITABLE_FOLDERS", [allowed])
    target = allowed / "log.txt"
    target.write_text("first\n", encoding="utf-8")

    result = addon.run("loki", "admin", "append_file", {"path": str(target), "content": "second\n"}, False)

    assert result.status == "confirmation_required"
    assert target.read_text(encoding="utf-8") == "first\n"


def test_append_file_confirmed_appends(addon, monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(Settings, "WRITABLE_FOLDERS", [allowed])
    target = allowed / "log.txt"
    target.write_text("first\n", encoding="utf-8")

    result = addon.run("loki", "admin", "append_file", {"path": str(target), "content": "second\n"}, True)

    assert result.status == "complete"
    assert target.read_text(encoding="utf-8") == "first\nsecond\n"


def test_write_file_size_cap_enforced(addon, monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(Settings, "WRITABLE_FOLDERS", [allowed])
    target = allowed / "big.txt"
    too_big = "x" * (MAX_WRITE_BYTES + 1)

    result = addon.run("loki", "admin", "write_file", {"path": str(target), "content": too_big}, True)

    assert result.status == "invalid"
    assert not target.exists()


# -- role enforcement (via AddonManager) ------------------------------------


def test_manager_denies_non_admin_actors(monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_APPS", {"notepad": "notepad.exe"})
    manager = AddonManager()

    user_result = manager.run("system_control", "alex", "user", "open_app", {"app": "notepad"}, True)
    guest_result = manager.run("system_control", "guest", "guest", "open_app", {"app": "notepad"}, True)

    assert user_result.status == "denied"
    assert guest_result.status == "denied"


def test_manager_allows_admin_actor(monkeypatch):
    monkeypatch.setattr(Settings, "ALLOWED_APPS", {})  # not configured, but role check happens first
    manager = AddonManager()

    result = manager.run("system_control", "loki", "admin", "open_app", {"app": "notepad"}, True)

    assert result.status == "not configured"  # reached the add-on, wasn't denied by role
