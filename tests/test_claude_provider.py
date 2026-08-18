"""Unit tests for ClaudeProvider.stream_reply against a fake Anthropic-shaped
client — no live API key or network call needed."""

from backend.brain.claude import ClaudeProvider
from backend.brain.prompt import SYSTEM_PROMPT


class FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeAnthropicResponse:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class FakeMessagesAPI:
    def __init__(self, responses):
        self.queue = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.queue.pop(0)


class FakeAnthropicClient:
    def __init__(self, responses):
        self.messages = FakeMessagesAPI(responses)


def make_provider(responses, tool_runner=None):
    provider = ClaudeProvider.__new__(ClaudeProvider)  # skip __init__'s API key check
    provider.client = FakeAnthropicClient(responses)
    provider.tool_runner = tool_runner
    return provider


def test_empty_final_turn_still_emits_exactly_one_result():
    response = FakeAnthropicResponse([FakeTextBlock("")], stop_reason="end_turn")
    provider = make_provider([response])

    events = []
    paused, convo = provider.stream_reply([{"role": "user", "content": "hi"}], events.append)

    assert paused is False
    assert len(events) == 1
    assert events[0]["type"] == "result"
    assert events[0]["text"]  # never empty — must fall back to something


def test_memory_context_is_appended_to_system_prompt():
    response = FakeAnthropicResponse([FakeTextBlock("ok")], stop_reason="end_turn")
    provider = make_provider([response])

    events = []
    provider.stream_reply(
        [{"role": "user", "content": "hi"}],
        events.append,
        memory_context="What you know about Loki:\n- has a cat",
    )

    sent = provider.client.messages.calls[0]
    assert "has a cat" in sent["system"]
    assert sent["system"].startswith(SYSTEM_PROMPT)


def test_memory_context_none_leaves_system_prompt_unchanged():
    response = FakeAnthropicResponse([FakeTextBlock("ok")], stop_reason="end_turn")
    provider = make_provider([response])

    events = []
    provider.stream_reply([{"role": "user", "content": "hi"}], events.append)  # memory_context defaults to None

    sent = provider.client.messages.calls[0]
    assert sent["system"] == SYSTEM_PROMPT
