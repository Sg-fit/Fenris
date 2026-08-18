from backend.brain.tools import TOOLS, to_openai_tools


def test_to_openai_tools_preserves_count():
    openai_tools = to_openai_tools(TOOLS)
    assert len(openai_tools) == len(TOOLS) == 14


def test_to_openai_tools_shape_and_content():
    openai_tools = to_openai_tools(TOOLS)
    by_name = {tool["function"]["name"]: tool for tool in openai_tools}
    original_by_name = {tool["name"]: tool for tool in TOOLS}

    assert set(by_name) == set(original_by_name)
    for name, converted in by_name.items():
        original = original_by_name[name]
        assert converted["type"] == "function"
        assert converted["function"]["name"] == original["name"]
        assert converted["function"]["description"] == original["description"]
        assert converted["function"]["parameters"] == original["input_schema"]


def test_expected_tool_names_present():
    names = {tool["name"] for tool in TOOLS}
    assert names == {
        "web_search",
        "read_page",
        "browser_actions",
        "ask_user",
        "show_media",
        "list_local_files",
        "read_local_file",
        "set_reminder",
        "list_reminders",
        "cancel_reminder",
        "open_app",
        "run_command",
        "write_file",
        "append_file",
    }
