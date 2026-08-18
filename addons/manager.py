from addons.base import Addon, AddonResult
from addons.image_print import ImagePrintAddon
from addons.local_files import LocalFilesAddon
from addons.media import MediaAddon
from addons.projector import ProjectorAddon
from addons.system_control import SystemControlAddon
from addons.web_browser import WebBrowserAddon
from backend.audit import AuditLog


class AddonManager:
    def __init__(self):
        enabled: list[Addon] = [
            ProjectorAddon(),
            ImagePrintAddon(),
            WebBrowserAddon(),
            MediaAddon(),
            LocalFilesAddon(),
            SystemControlAddon(),
        ]
        self._addons = {addon.id: addon for addon in enabled}
        self.audit = AuditLog()

    def manifests(self) -> list[dict]:
        return [addon.manifest() for addon in self._addons.values()]

    def run(self, addon_id: str, actor_name: str, actor_role: str, action: str, payload: dict, confirmed: bool) -> AddonResult:
        addon = self._addons.get(addon_id)
        if not addon:
            result = AddonResult("not_found", f"No add-on named '{addon_id}'.")
            self.audit.record("addon_request", actor_name, actor_role, addon_id, {"action": action, "status": result.status})
            return result
        if addon.required_role == "admin" and actor_role != "admin":
            result = AddonResult("denied", "This add-on is available to the administrator only.")
        else:
            result = addon.run(actor_name, actor_role, action, payload, confirmed)
        self.audit.record("addon_request", actor_name, actor_role, addon_id, {"action": action, "confirmed": confirmed, "status": result.status, "payload": payload})
        return result
