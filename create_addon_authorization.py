"""Create a password hash file at a location you control outside Fenris."""
import sys
from getpass import getpass
from pathlib import Path

from security.addon_authorization import make_password_hash


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python create_addon_authorization.py <external-file-path>")
    password = getpass("Choose add-on creator password: ")
    confirm = getpass("Confirm password: ")
    if not password or password != confirm:
        raise SystemExit("Passwords did not match.")
    target = Path(sys.argv[1]).expanduser()
    if target.resolve().is_relative_to(Path.cwd().resolve()):
        raise SystemExit("Choose a path outside the Fenris project folder.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(make_password_hash(password), encoding="utf-8")
    print("Authorization hash created. Keep this file outside the project and set FENRIS_ADDON_CREATOR_AUTH_FILE to its path in .env.")


if __name__ == "__main__":
    main()
