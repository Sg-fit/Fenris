import os

from addons.base import Addon, AddonResult
from addons.net import safe_public_url

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}


class MediaAddon(Addon):
    """Displays an image or video in the visual HUD — from the public web or a
    local file. Read-only: it never changes anything, it only shows it."""

    id = "media"
    name = "Media display"
    description = "Display an image or video in the visual HUD, from the web or a local file."
    required_role = "user"

    def run(self, actor_name: str, actor_role: str, action: str, payload: dict, confirmed: bool) -> AddonResult:
        if action == "show":
            return self._show(payload)
        return AddonResult("invalid", "Supported actions: show.")

    def _show(self, payload: dict) -> AddonResult:
        source = payload.get("source")
        location = payload.get("location")
        kind = payload.get("kind")
        if source not in {"web", "local"}:
            return AddonResult("invalid", "source must be 'web' or 'local'.")
        if kind not in {"image", "video"}:
            return AddonResult("invalid", "kind must be 'image' or 'video'.")
        if not isinstance(location, str) or not location.strip():
            return AddonResult("invalid", "location is required.")

        if source == "web":
            try:
                url = safe_public_url(location)
            except ValueError as error:
                return AddonResult("invalid", str(error))
            return AddonResult("complete", "Ready to display.", {"source": "web", "kind": kind, "location": url})

        path = os.path.abspath(location)
        if not os.path.isfile(path):
            return AddonResult("invalid", f"No file found at {location}.")
        extension = os.path.splitext(path)[1].lower()
        allowed = IMAGE_EXTENSIONS if kind == "image" else VIDEO_EXTENSIONS
        if extension not in allowed:
            return AddonResult("invalid", f"{extension or 'that file type'} isn't a supported {kind} format.")
        return AddonResult("complete", "Ready to display.", {"source": "local", "kind": kind, "location": path})
