from backend.memory.extractor import extract_facts


def test_extract_facts_parses_lines():
    def fake_complete(system, user):
        return "Loki has a dog named Rex\nLoki works as a game developer"

    facts = extract_facts(fake_complete, "I have a dog named Rex and I'm a game dev", "Nice!")

    assert facts == ["Loki has a dog named Rex", "Loki works as a game developer"]


def test_extract_facts_none_reply_yields_empty_list():
    def fake_complete(system, user):
        return "NONE"

    assert extract_facts(fake_complete, "how's the weather", "It's sunny.") == []


def test_extract_facts_blank_reply_yields_empty_list():
    def fake_complete(system, user):
        return "   "

    assert extract_facts(fake_complete, "hi", "hello") == []


def test_extract_facts_json_list_reply_is_parsed():
    def fake_complete(system, user):
        return '["Loki lives in Seattle", "Loki has a cat"]'

    assert extract_facts(fake_complete, "I live in Seattle with my cat", "Nice!") == [
        "Loki lives in Seattle",
        "Loki has a cat",
    ]


def test_extract_facts_never_raises_when_complete_errors():
    def raising_complete(system, user):
        raise RuntimeError("model unreachable")

    assert extract_facts(raising_complete, "hi", "hello") == []


def test_extract_facts_skips_the_call_entirely_for_empty_user_text():
    calls = []

    def fake_complete(system, user):
        calls.append((system, user))
        return "NONE"

    assert extract_facts(fake_complete, "", "hello") == []
    assert calls == []
