from pathlib import Path

from addons.base import Addon, AddonResult


class ProjectorAddon(Addon):
    id = "projector"
    name = "Projector display"
    description = "Prepares an approved image or video artifact for display."

    def run(self, actor_name: str, actor_role: str, action: str, payload: dict, confirmed: bool) -> AddonResult:
        if action != "show":
            return AddonResult("invalid", "Supported action: show.")
        artifact = payload.get("artifact_path")
        if not isinstance(artifact, str) or not artifact:
            return AddonResult("invalid", "artifact_path is required.")
        suffix = Path(artifact).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".mp4"}:
            return AddonResult("invalid", "Only image and MP4 artifacts are supported.")
        if not confirmed:
            return AddonResult(
                "confirmation_required",
                f"Ready to display {Path(artifact).name}. Repeat with confirmed=true to proceed.",
                {"artifact_path": artifact},
            )
        # Hardware adapter intentionally comes later: this is the safe plug-in seam.
        return AddonResult("queued", "Projector display request queued.", {"artifact_path": artifact})
