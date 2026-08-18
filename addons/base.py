from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


@dataclass
class AddonResult:
    status: str
    message: str
    data: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class Addon(ABC):
    """Contract for every Fenris add-on.

    Add-ons must validate their own input and must not perform an irreversible
    action unless their request carries an explicit confirmation.
    """

    id: str
    name: str
    description: str
    required_role = "admin"

    def manifest(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "required_role": self.required_role,
        }

    @abstractmethod
    def run(self, actor_name: str, actor_role: str, action: str, payload: dict, confirmed: bool) -> AddonResult:
        """Execute a named action after the backend has checked the caller role."""
