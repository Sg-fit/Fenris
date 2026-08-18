from security.identity import Identity


def can_access_memory(requester: Identity, owner: str) -> bool:
    """Admins may manage all session memory; everyone else may manage their own."""
    return requester.role == "admin" or requester.name == owner
