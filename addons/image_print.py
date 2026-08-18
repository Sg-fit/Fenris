from pathlib import Path

from addons.base import Addon, AddonResult


class ImagePrintAddon(Addon):
    id = "image_print"
    name = "Image print"
    description = "Validates image-print requirements before submitting a print job."

    def run(self, actor_name: str, actor_role: str, action: str, payload: dict, confirmed: bool) -> AddonResult:
        if action != "print":
            return AddonResult("invalid", "Supported action: print.")
        image = payload.get("image_path")
        copies = payload.get("copies", 1)
        paper = payload.get("paper", "letter")
        color = payload.get("color", True)
        if not isinstance(image, str) or Path(image).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            return AddonResult("invalid", "image_path must point to a PNG, JPG, JPEG, or WEBP file.")
        if not isinstance(copies, int) or not 1 <= copies <= 10:
            return AddonResult("invalid", "copies must be an integer from 1 to 10.")
        if paper not in {"letter", "a4", "4x6"} or not isinstance(color, bool):
            return AddonResult("invalid", "Use paper: letter, a4, or 4x6 and a boolean color value.")
        requirements = {"image_path": image, "copies": copies, "paper": paper, "color": color}
        if not confirmed:
            return AddonResult("confirmation_required", "Print requirements validated. Confirm to queue the job.", requirements)
        # Replace this return with a Windows/CUPS adapter only after printer selection is explicit.
        return AddonResult("queued", "Image print request queued.", requirements)
