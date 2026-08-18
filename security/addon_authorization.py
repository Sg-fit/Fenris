import hashlib
import hmac
import os
from pathlib import Path

from config import Config


def make_password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def verify_creator_password(password: str) -> bool:
    """Check a scrypt hash in an admin-controlled external file."""
    if not Config.ADDON_CREATOR_AUTH_FILE or not password:
        return False
    try:
        stored = Path(Config.ADDON_CREATOR_AUTH_FILE).read_text(encoding="utf-8").strip()
        salt_hex, expected = stored.split(":", 1)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1).hex()
        return hmac.compare_digest(actual, expected)
    except (OSError, ValueError, TypeError):
        return False
