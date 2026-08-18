"""Unit tests for LocalProvider.stream_reply against a fake OpenAI-shaped
client — no live Ollama/vLLM server needed. LocalProvider.__init__ does a
network reachability probe, so these tests construct the provider directly
(bypassing __init__) and inject a fake client instead."""

import json

from backend.brain.local import LocalProvider


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, message):
        self.choices = [FakeChoice(message)]


class FakeCompletions:
    def __init__(self, responses):
        self.queue = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.queue.pop(0)


class FakeChat:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)


class FakeClient:
    def __init__(self, responses):
        self.chat = FakeChat(responses)


def make_provider(responses, tool_runner=None):
    provider = LocalProvider.__new__(LocalProvider)  # skip __init__'s network probe
    provider.client = FakeClient(responses)
    provider.tool_runner = tool_runner
    return provider


def test_tool_call_then_final_result():
    search_call = FakeToolCall("call_1", "web_search", json.dumps({"query": "weather today"}))
    first = FakeMessage(content="Let me check.", tool_calls=[search_call])
    second = FakeMessage(content="It's sunny.", tool_calls=None)

    seen_calls = []

    def tool_runner(name, args):
        seen_calls.append((name, args))
        return {"status": "complete", "data": {"results": []}}

    provider = make_provider([FakeResponse(first), FakeResponse(second)], tool_runner)

    events = []
    conversation = [{"role": "user", "content": "what's the weather"}]
    paused, convo = provider.stream_reply(conversation, events.append)

    assert paused is False
    assert seen_calls == [("web_search", {"query": "weather today"})]
    assert {"type": "progress", "text": "Let me check."} in events
    assert events[-1] == {"type": "result", "text": "It's sunny."}
    # The tool result must be threaded back into the conversation for context.
    assert any(m.get("role") == "tool" for m in convo)


def test_ask_user_pauses_then_resumes():
    ask_call = FakeToolCall("call_ask", "ask_user", json.dumps({"question": "Which city?"}))
    first = FakeMessage(content=None, tool_calls=[ask_call])
    second = FakeMessage(content="Got it, checking Paris.", tool_calls=None)

    provider = make_provider([FakeResponse(first)], tool_runner=lambda name, args: {"status": "complete"})

    events = []
    conversation = [{"role": "user", "content": "what's the weather"}]
    paused, convo = provider.stream_reply(conversation, events.append)

    assert paused is True
    assert events[-1] == {"type": "question", "text": "Which city?"}

    provider.client.chat.completions.queue.append(FakeResponse(second))
    events2 = []
    paused2, convo2 = provider.stream_reply(convo, events2.append, resume_answer="Paris")

    assert paused2 is False
    assert events2[-1] == {"type": "result", "text": "Got it, checking Paris."}
    # The answer must have been fed back as that tool_call's result.
    assert any(m.get("role") == "tool" and m.get("content") == "Paris" for m in convo2)


def test_empty_final_turn_still_emits_exactly_one_result():
    empty = FakeMessage(content="", tool_calls=None)
    provider = make_provider([FakeResponse(empty)])

    events = []
    paused, convo = provider.stream_reply([{"role": "user", "content": "hi"}], events.append)

    assert paused is False
    assert len(events) == 1
    assert events[0]["type"] == "result"
    assert events[0]["text"]  # never empty — must fall back to something


def test_memory_context_is_appended_to_system_message():
    empty = FakeMessage(content="ok", tool_calls=None)
    provider = make_provider([FakeResponse(empty)])

    events = []
    provider.stream_reply(
        [{"role": "user", "content": "hi"}],
        events.append,
        memory_context="What you know about Loki:\n- has a cat",
    )

    sent_messages = provider.client.chat.completions.calls[0]["messages"]
    assert sent_messages[0]["role"] == "system"
    assert "has a cat" in sent_messages[0]["content"]


def test_memory_context_none_leaves_system_message_unchanged():
    from backend.brain.prompt import SYSTEM_PROMPT

    empty = FakeMessage(content="ok", tool_calls=None)
    provider = make_provider([FakeResponse(empty)])

    events = []
    provider.stream_reply([{"role": "user", "content": "hi"}], events.append)  # memory_context defaults to None

    sent_messages = provider.client.chat.completions.calls[0]["messages"]
    assert sent_messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
