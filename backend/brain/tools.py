TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the public web and return a list of result titles and URLs. Set site to "
            "search only within one domain/platform (e.g. reddit.com) when the user asks to "
            "search a specific place, not the whole web."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                "site": {
                    "type": "string",
                    "description": "Optional: a domain to restrict results to, e.g. reddit.com or nytimes.com.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_page",
        "description": "Open a public http/https URL and return its title and visible text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "A complete http or https URL."},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_actions",
        "description": (
            "Perform an explicit sequence of browser steps that can change website "
            "state (open, click, fill, wait). Requires the user's prior approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 40,
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["open", "click", "fill", "wait"]},
                            "url": {"type": "string"},
                            "selector": {"type": "string"},
                            "value": {"type": "string"},
                            "milliseconds": {"type": "integer"},
                        },
                        "required": ["action"],
                    },
                },
                "user_confirmed": {
                    "type": "boolean",
                    "description": "True only if the user explicitly approved these exact steps.",
                },
                "show_window": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "True only if the user explicitly asked to see the browser or watch it "
                        "happen. Runs invisibly in the background otherwise."
                    ),
                },
            },
            "required": ["steps", "user_confirmed"],
        },
    },
    {
        "name": "ask_user",
        "description": (
            "Ask the user a question when you're genuinely blocked and need their "
            "input to keep going on a multi-step task. Not for trivial preferences "
            "you could reasonably decide yourself. The task resumes once they answer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question, phrased naturally for speech."},
            },
            "required": ["question"],
        },
    },
    {
        "name": "show_media",
        "description": (
            "Display an image or video in Fenris's visual HUD instead of just describing it. "
            "Read-only; doesn't need confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["web", "local"],
                    "description": "\"web\" for a public http/https URL you found or were given; \"local\" for a file already on this PC.",
                },
                "location": {"type": "string", "description": "The URL (for web) or file path (for local)."},
                "kind": {"type": "string", "enum": ["image", "video"]},
                "caption": {"type": "string", "description": "A short spoken-style caption for what's being shown."},
            },
            "required": ["source", "location", "kind"],
        },
    },
    {
        "name": "list_local_files",
        "description": "List files in the user's allowed local folders. Read-only; doesn't need confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A folder to list. Omit to list all allowed top-level folders.",
                },
            },
        },
    },
    {
        "name": "read_local_file",
        "description": (
            "Read a local file's contents (only inside the user's allowed folders). This exposes "
            "the file's content to you, so it requires the user's explicit go-ahead first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The exact file path, as returned by list_local_files."},
                "user_confirmed": {
                    "type": "boolean",
                    "description": "True only if the user explicitly agreed to have this specific file read.",
                },
            },
            "required": ["path", "user_confirmed"],
        },
    },
    {
        "name": "set_reminder",
        "description": (
            "Schedule a reminder that Fenris will speak unprompted, without the wake word, "
            "when it comes due. Use in_minutes for a relative time ('in 20 minutes'), or when "
            "(an ISO 8601 timestamp, using the current time you were given) for an absolute "
            "time ('tomorrow at 9am'). Provide exactly one of the two."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to remind the user of."},
                "when": {
                    "type": "string",
                    "description": "Absolute ISO 8601 timestamp — only if not using in_minutes.",
                },
                "in_minutes": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Minutes from now — only if not using when.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List this person's upcoming reminders that haven't fired yet.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel a pending reminder by its id, as returned by list_reminders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "integer", "description": "The reminder's id from list_reminders."},
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "open_app",
        "description": (
            "Launch an app the user has explicitly allow-listed. Changes what's running on their "
            "PC, so it always needs the user's fresh, explicit approval first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "The app's allow-listed name, not a file path."},
                "user_confirmed": {
                    "type": "boolean",
                    "description": "True only if the user just explicitly approved opening this app.",
                },
            },
            "required": ["app", "user_confirmed"],
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run a command the user has explicitly allow-listed, with optional extra arguments. "
            "There is no free-form/arbitrary command execution — only pre-approved command_ids run, "
            "and only via a fixed argument list, never a shell. Always needs the user's fresh, "
            "explicit approval of the exact command and arguments first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command_id": {"type": "string", "description": "The command's allow-listed id."},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra arguments appended to the command's fixed template, if needed.",
                },
                "user_confirmed": {
                    "type": "boolean",
                    "description": "True only if the user just explicitly approved this exact command and args.",
                },
            },
            "required": ["command_id", "user_confirmed"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write (overwrite) a file inside a folder the user has explicitly made writable. "
            "Always needs the user's fresh, explicit approval of the exact file and content first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write, inside an allowed folder."},
                "content": {"type": "string", "description": "The full file content to write."},
                "user_confirmed": {
                    "type": "boolean",
                    "description": "True only if the user just explicitly approved writing this exact content.",
                },
            },
            "required": ["path", "content", "user_confirmed"],
        },
    },
    {
        "name": "append_file",
        "description": (
            "Append to a file inside a folder the user has explicitly made writable. Always needs "
            "the user's fresh, explicit approval of the exact file and content first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to append to, inside an allowed folder."},
                "content": {"type": "string", "description": "The content to append."},
                "user_confirmed": {
                    "type": "boolean",
                    "description": "True only if the user just explicitly approved appending this exact content.",
                },
            },
            "required": ["path", "content", "user_confirmed"],
        },
    },
]


def to_openai_tools(tools: list[dict]) -> list[dict]:
    """Reshape Anthropic-style tool schemas (name/description/input_schema)
    into OpenAI's {"type": "function", "function": {...}} form. The JSON
    Schema body itself is identical between the two, so this is a pure
    reshape — there's a single source of truth (TOOLS above) for both
    providers."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in tools
    ]
