"""Copy this file, rename it, then register the add-on in addons/manager.py."""
from addons.base import Addon, AddonResult


class ExampleAddon(Addon):
    id = "example"
    name = "Example add-on"
    description = "One sentence explaining the capability."
    required_role = "admin"  # Use "user" only for safe, non-sensitive actions.

    def run(self, action: str, payload: dict, confirmed: bool) -> AddonResult:
        if action != "do_thing":
            return AddonResult("invalid", "Supported action: do_thing.")
        if not confirmed:
            return AddonResult("confirmation_required", "Confirm this action before it runs.", payload)
        # Validate every payload field before adding a real external side effect.
        return AddonResult("queued", "Example request accepted.", payload)
