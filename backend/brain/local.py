import json
from typing import Callable

from backend.brain.prompt import SYSTEM_PROMPT
from backend.brain.tools import TOOLS, to_openai_tools
from backend.settings import Settings


class LocalProvider:
    """Drop-in replacement for ClaudeProvider that talks to a locally-served
    open-weight model over the OpenAI-compatible chat completions API. Works
    against Ollama or vLLM unchanged — only Settings.LOCAL_BASE_URL differs."""

    # Matches ClaudeProvider's cap: enough room for a real mission, still
    # bounded so a confused model can't loop forever.
    MAX_STEPS = 25

    def __init__(self, tool_runner=None):
        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError(
                "The local model provider needs the openai package. Run: pip install -r requirements.txt"
            ) from error
        self.client = OpenAI(base_url=Settings.LOCAL_BASE_URL, api_key=Settings.LOCAL_API_KEY)
        try:
            # A cheap, standard OpenAI-compatible endpoint both Ollama's /v1
            # shim and vLLM support — used purely as a reachability probe so
            # a dead local server fails fast with a clear message instead of
            # surfacing as an opaque mid-conversation error later.
            self.client.models.list(timeout=5)
        except Exception as error:
            raise RuntimeError(
                f"Could not reach the local model server at {Settings.LOCAL_BASE_URL}. Is it running? ({error})"
            ) from error
        # tool_runner(tool_name, tool_input) -> dict result. When absent, the
        # provider replies without browsing tools.
        self.tool_runner = tool_runner

    @staticmethod
    def build_conversation(messages: list[dict[str, str]], images: list | None = None) -> list[dict]:
        """Turn a plain user/assistant message list into a fresh conversation,
        attaching any uploaded images to the most recent user message. The
        system prompt is not included here — stream_reply prepends it fresh
        each call, mirroring how ClaudeProvider passes system= separately."""
        conversation: list[dict] = [dict(message) for message in messages]
        if images:
            for message in reversed(conversation):
                if message.get("role") == "user":
                    text = message.get("content", "")
                    parts = [{"type": "text", "text": text}] if text else []
                    for image in images:
                        parts.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{image['media_type']};base64,{image['data']}"},
                            }
                        )
                    # A non-vision model will error on this shape rather than
                    # silently ignore it; that surfaces as a normal tool-loop
                    # failure instead of crashing the process.
                    message["content"] = parts
                    break
        return conversation

    def _resolve_pending(self, last_assistant_message: dict, answer: str) -> list[dict]:
        """Build the tool-result messages for a resumed turn. The ask_user
        call gets the user's answer; any other tool_calls in that same turn
        (the model should not normally mix these, but it's handled if it
        does) are actually run now, so the resumed conversation stays valid.
        Unlike Anthropic's single batched tool_result message, OpenAI wants
        one "tool" role message per tool_call."""
        results = []
        for call in last_assistant_message.get("tool_calls") or []:
            name = call["function"]["name"]
            if name == "ask_user":
                content = answer
            else:
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}
                try:
                    content = json.dumps(self.tool_runner(name, args))[:8000]
                except Exception as error:
                    content = json.dumps({"status": "error", "message": str(error)})
            results.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        return results

    def complete(self, system: str, user: str) -> str:
        """Single-shot, tool-free call — used by things like the fact
        extractor that just need one cheap answer, not a full mission loop."""
        response = self.client.chat.completions.create(
            model=Settings.LOCAL_MODEL,
            max_tokens=300,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return (response.choices[0].message.content or "").strip()

    def stream_reply(
        self,
        conversation: list[dict],
        on_event: Callable[[dict], None],
        resume_answer: str | None = None,
        memory_context: str | None = None,
    ) -> tuple[bool, list[dict]]:
        """Run (or resume) the tool loop, emitting progress/question/result/media
        events as they happen — same contract as ClaudeProvider.stream_reply.
        Returns (paused, conversation): paused=True means the conversation
        ends mid-mission on a dangling ask_user tool_call, ready to be resumed
        later with the user's answer as resume_answer. memory_context, when
        given, is appended to the system message — long-term facts/recall
        about this person; with memory_context=None behavior is identical to
        not having it."""
        tools = to_openai_tools(TOOLS) if self.tool_runner else None
        system = f"{SYSTEM_PROMPT}\n\n{memory_context}" if memory_context else SYSTEM_PROMPT

        if resume_answer is not None:
            conversation.extend(self._resolve_pending(conversation[-1], resume_answer))

        for _ in range(self.MAX_STEPS):
            response = self.client.chat.completions.create(
                model=Settings.LOCAL_MODEL,
                max_tokens=Settings.LOCAL_MAX_TOKENS,
                messages=[{"role": "system", "content": system}, *conversation],
                tools=tools,
                tool_choice="auto" if tools else None,
            )
            message = response.choices[0].message
            text = (message.content or "").strip()
            tool_calls = message.tool_calls or []

            if not tool_calls:
                # Always emit something — an empty final turn must never
                # leave the client with zero events.
                on_event({"type": "result", "text": text or "I finished but didn't have anything more to add."})
                return False, conversation

            assistant_message = {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.function.name, "arguments": call.function.arguments},
                    }
                    for call in tool_calls
                ],
            }
            conversation.append(assistant_message)

            ask_call = next((call for call in tool_calls if call.function.name == "ask_user"), None)
            if ask_call:
                if text:
                    on_event({"type": "progress", "text": text})
                question = (self._parse_args(ask_call) or {}).get("question", "")
                on_event({"type": "question", "text": question})
                return True, conversation

            if text:
                on_event({"type": "progress", "text": text})

            for call in tool_calls:
                name = call.function.name
                args = self._parse_args(call)
                if args is None:
                    output = {"status": "error", "message": f"Malformed arguments for {name}."}
                else:
                    try:
                        output = self.tool_runner(name, args)
                    except Exception as error:  # never let a tool crash the mission
                        output = {"status": "error", "message": str(error)}
                    if name == "show_media" and output.get("status") == "complete":
                        data = output.get("data") or {}
                        on_event(
                            {
                                "type": "media",
                                "source": data.get("source"),
                                "kind": data.get("kind"),
                                "location": data.get("location"),
                                "caption": args.get("caption", ""),
                            }
                        )
                conversation.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(output)[:8000]})

        on_event({"type": "result", "text": "I could not finish that safely, so I stopped."})
        return False, conversation

    @staticmethod
    def _parse_args(call) -> dict | None:
        """Local models occasionally emit malformed tool-call arguments;
        never let that crash the mission."""
        try:
            return json.loads(call.function.arguments or "{}")
        except (json.JSONDecodeError, TypeError):
            return None
