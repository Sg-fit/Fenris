import json
import re
from pathlib import Path


CUSTOM_MANIFEST = Path("addons") / "custom" / "manifest.json"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


def create_scaffold(addon_id: str, name: str, description: str, actions: list[str]) -> dict:
    """Register a safe manifest-only add-on scaffold.

    It cannot run arbitrary code. A future implementation must be reviewed and
    registered explicitly in addons/manager.py.
    """
    if not ID_PATTERN.fullmatch(addon_id):
        raise ValueError("addon_id must use 3-41 lowercase letters, digits, and underscores.")
    if not isinstance(name, str) or not 1 <= len(name) <= 80:
        raise ValueError("name must be 1 to 80 characters.")
    if not isinstance(description, str) or not 1 <= len(description) <= 300:
        raise ValueError("description must be 1 to 300 characters.")
    if not isinstance(actions, list) or not actions or len(actions) > 8 or any(not isinstance(action, str) or not ID_PATTERN.fullmatch(action) for action in actions):
        raise ValueError("actions must be 1 to 8 lowercase action identifiers.")

    CUSTOM_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifests = json.loads(CUSTOM_MANIFEST.read_text(encoding="utf-8")) if CUSTOM_MANIFEST.exists() else []
    if any(item["id"] == addon_id for item in manifests):
        raise ValueError("An add-on with that id already exists.")
    item = {"id": addon_id, "name": name, "description": description, "actions": actions, "status": "scaffold"}
    manifests.append(item)
    CUSTOM_MANIFEST.write_text(json.dumps(manifests, indent=2), encoding="utf-8")
    return item
