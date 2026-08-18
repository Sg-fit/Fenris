import subprocess
from pathlib import Path

from addons.base import Addon, AddonResult
from backend.settings import Settings

MAX_COMMAND_OUTPUT = 4_000
MAX_WRITE_BYTES = 200_000
COMMAND_TIMEOUT_SECONDS = 20
# Defense in depth even though shell=False is always used below — reject
# argument values that look like an attempt at shell injection.
SHELL_METACHARACTERS = set(";&|`$<>(){}!\n")


class SystemControlAddon(Addon):
    """Confirmation-gated control of this PC: launching allow-listed apps,
    running allow-listed commands, and writing files inside allow-listed
    folders. Nothing here ever runs with shell=True or accepts an arbitrary
    command — every capability is a named entry an admin configured in .env.
    Every action requires a fresh, explicit user_confirmed=true on that exact
    call; there is no trusted mode, no allow-list that skips the prompt, and
    an unconfirmed call always does nothing."""

    id = "system_control"
    name = "System control"
    description = (
        "Open allow-listed apps, run allow-listed commands, and write files in allow-listed "
        "folders — always confirmed by the user first."
    )
    required_role = "admin"

    def run(self, actor_name: str, actor_role: str, action: str, payload: dict, confirmed: bool) -> AddonResult:
        if action == "open_app":
            return self._open_app(payload, confirmed)
        if action == "run_command":
            return self._run_command(payload, confirmed)
        if action == "write_file":
            return self._write_file(payload, confirmed, append=False)
        if action == "append_file":
            return self._write_file(payload, confirmed, append=True)
        return AddonResult("invalid", "Supported actions: open_app, run_command, write_file, append_file.")

    # -- open_app ---------------------------------------------------------

    def _open_app(self, payload: dict, confirmed: bool) -> AddonResult:
        if not Settings.ALLOWED_APPS:
            return AddonResult("not configured", "No apps are allowed. Set FENRIS_ALLOWED_APPS in .env to enable this.")
        app = payload.get("app")
        if not isinstance(app, str) or app not in Settings.ALLOWED_APPS:
            return AddonResult("invalid", f"{app!r} isn't an allowed app.")

        if not confirmed:
            return AddonResult("confirmation_required", f"Ready to open {app}. Confirm to launch it.", {"app": app})

        exe = Settings.ALLOWED_APPS[app]
        try:
            subprocess.Popen([exe])
        except OSError as error:
            return AddonResult("error", f"Could not launch {app}: {error}")
        return AddonResult("complete", f"Opened {app}.", {"app": app})

    # -- run_command --------------------------------------------------------

    def _run_command(self, payload: dict, confirmed: bool) -> AddonResult:
        if not Settings.ALLOWED_COMMANDS:
            return AddonResult(
                "not configured", "No commands are allowed. Set FENRIS_ALLOWED_COMMANDS in .env to enable this."
            )
        command_id = payload.get("command_id")
        if not isinstance(command_id, str) or command_id not in Settings.ALLOWED_COMMANDS:
            return AddonResult("invalid", f"{command_id!r} isn't an allowed command.")

        args = payload.get("args") or []
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            return AddonResult("invalid", "args must be a list of strings.")
        for arg in args:
            if any(char in SHELL_METACHARACTERS for char in arg):
                return AddonResult("invalid", f"{arg!r} contains characters that aren't allowed in an argument.")

        argv = Settings.ALLOWED_COMMANDS[command_id].split() + args

        if not confirmed:
            return AddonResult(
                "confirmation_required",
                f"Ready to run: {' '.join(argv)}. Confirm to execute it.",
                {"command_id": command_id, "args": args},
            )

        try:
            result = subprocess.run(argv, shell=False, timeout=COMMAND_TIMEOUT_SECONDS, capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            return AddonResult("error", f"'{command_id}' took too long and was stopped.")
        except OSError as error:
            return AddonResult("error", f"Could not run '{command_id}': {error}")

        return AddonResult(
            "complete",
            f"Ran '{command_id}'.",
            {
                "command_id": command_id,
                "exit_code": result.returncode,
                "stdout": result.stdout[:MAX_COMMAND_OUTPUT],
                "stderr": result.stderr[:MAX_COMMAND_OUTPUT],
            },
        )

    # -- write_file / append_file -------------------------------------------

    @staticmethod
    def _resolve_writable(raw_path: str) -> Path | None:
        """Same containment check LocalFilesAddon._resolve uses — the
        resolved path must land inside one of the writable folders (or be
        one itself), so .. escapes and symlink tricks can't reach outside."""
        if not raw_path:
            return None
        try:
            resolved = Path(raw_path).expanduser().resolve()
        except (OSError, RuntimeError):
            return None
        for folder in Settings.WRITABLE_FOLDERS:
            if resolved == folder or folder in resolved.parents:
                return resolved
        return None

    def _write_file(self, payload: dict, confirmed: bool, append: bool) -> AddonResult:
        if not Settings.WRITABLE_FOLDERS:
            return AddonResult(
                "not configured", "No folders are writable. Set FENRIS_WRITABLE_FOLDERS in .env to enable this."
            )
        raw_path = payload.get("path")
        content = payload.get("content")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return AddonResult("invalid", "path is required.")
        if not isinstance(content, str):
            return AddonResult("invalid", "content is required.")
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return AddonResult("invalid", f"content is too large (max {MAX_WRITE_BYTES} bytes).")

        resolved = self._resolve_writable(raw_path)
        if resolved is None:
            return AddonResult("invalid", f"{raw_path} is outside the folders Fenris is allowed to write to.")

        verb = "append to" if append else "write"
        if not confirmed:
            preview = content if len(content) <= 200 else content[:200] + "…"
            return AddonResult(
                "confirmation_required",
                f"Ready to {verb} {resolved}. Confirm to save it.",
                {"path": str(resolved), "preview": preview},
            )

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "a" if append else "w", encoding="utf-8") as handle:
                handle.write(content)
        except OSError as error:
            return AddonResult("error", f"Could not {verb} {resolved.name}: {error}")

        return AddonResult(
            "complete",
            f"{'Appended to' if append else 'Wrote'} {resolved.name}.",
            {"path": str(resolved), "bytes_written": len(content.encode("utf-8"))},
        )
