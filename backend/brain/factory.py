from backend.brain.claude import ClaudeProvider
from backend.brain.local import LocalProvider
from backend.settings import Settings


def get_provider_class():
    """Which brain provider class /chat should use this request, selected by
    FENRIS_BRAIN_PROVIDER. Both providers share the same build_conversation /
    __init__(tool_runner) / stream_reply contract, so callers never need to
    branch on which one they got."""
    if Settings.BRAIN_PROVIDER == "local":
        return LocalProvider
    return ClaudeProvider
