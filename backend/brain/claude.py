import json
from typing import Callable

from anthropic import Anthropic

from backend.brain.prompt import SYSTEM_PROMPT
from backend.brain.tools import TOOLS
from backend.settings import Settings


class ClaudeProvider:
    # A mission needs more room than a quick reply, but this still bounds a
    # confused model to a finite number of API calls.
    MAX_STEPS = 25

    def __init__(self, tool_runner=None):
        if not Settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY has not been configured.")
        self.client = Anthropic(api_key=Settings.ANTHROPIC_API_KEY)
        # tool_runner(tool_name, tool_input) -> dict result. When absent, the
        # provider replies without browsing tools.
        self.tool_runner = tool_runner

    @staticmethod
    def build_conversation(messages: list[dict[str, str]], images: list | None = None) -> list[dict]:
        """Turn a plain user/assistant message list into a fresh conversation,
        attaching any uploaded images to the most recent user message."""
        conversation: list[dict] = [dict(message) for message in messages]
        if images:
            for message in reversed(conversation):
                if message.get("role") == "user":
                    text = message.get("content", "")
                    blocks = [{"type": "text", "text": text}] if text else []
                    for image in images:
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": image["media_type"],
                                    "data": image["data"],
                                },
                            }
                        )
                    message["content"] = blocks
                    break
        return conversation

    def _resolve_pending(self, last_assistant_message: dict, answer: str) -> list[dict]:
        """Build the tool_result batch for a resumed turn. The ask_user call gets
        the user's answer; any other tool_use blocks in that same turn (the model
        should not normally mix these, but it's handled if it does) are actually
        run now, so the resumed conversation stays valid."""
        results = []
        for block in last_assistant_message["content"]:
            if getattr(block, "type", None) != "tool_use":
                continue
            if block.name == "ask_user":
                content = answer
            else:
                try:
                    content = json.dumps(self.tool_runner(block.name, block.input))[:8000]
                except Exception as error:
                    content = json.dumps({"status": "error", "message": str(error)})
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
        return results

    def complete(self, system: str, user: str) -> str:
        """Single-shot, tool-free call — used by things like the fact
        extractor that just need one cheap answer, not a full mission loop."""
        response = self.client.messages.create(
            model=Settings.ANTHROPIC_MODEL,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text").strip()

    def stream_reply(
        self,
        conversation: list[dict],
        on_event: Callable[[dict], None],
        resume_answer: str | None = None,
        memory_context: str | None = None,
    ) -> tuple[bool, list[dict]]:
        """Run (or resume) the tool loop, emitting progress/question/result events
        as they happen. Returns (paused, conversation): paused=True means the
        conversation ends mid-mission on a dangling ask_user tool_use, ready to be
        resumed later with the user's answer as resume_answer. memory_context, when
        given, is appended to the system prompt — long-term facts/recall about this
        person; with memory_context=None behavior is identical to not having it."""
        tools = TOOLS if self.tool_runner else []
        system = f"{SYSTEM_PROMPT}\n\n{memory_context}" if memory_context else SYSTEM_PROMPT

        if resume_answer is not None:
            conversation.append({"role": "user", "content": self._resolve_pending(conversation[-1], resume_answer)})

        for _ in range(self.MAX_STEPS):
            response = self.client.messages.create(
                model=Settings.ANTHROPIC_MODEL,
                max_tokens=1024,
                system=system,
                tools=tools,
                messages=conversation,
            )
            text = "".join(block.text for block in response.content if block.type == "text").strip()

            if response.stop_reason != "tool_use":
                # Always emit something — an empty final turn (e.g. cut off by
                # max_tokens) must never leave the client with zero events.
                on_event({"type": "result", "text": text or "I finished but didn't have anything more to add."})
                return False, conversation

            conversation.append({"role": "assistant", "content": response.content})
            ask_block = next(
                (b for b in response.content if b.type == "tool_use" and b.name == "ask_user"), None
            )
            if ask_block:
                if text:
                    on_event({"type": "progress", "text": text})
                on_event({"type": "question", "text": ask_block.input.get("question", "")})
                return True, conversation

            if text:
                on_event({"type": "progress", "text": text})

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    output = self.tool_runner(block.name, block.input)
                except Exception as error:  # never let a tool crash the mission
                    output = {"status": "error", "message": str(error)}
                if block.name == "show_media" and output.get("status") == "complete":
                    data = output.get("data") or {}
                    on_event(
                        {
                            "type": "media",
                            "source": data.get("source"),
                            "kind": data.get("kind"),
                            "location": data.get("location"),
                            "caption": block.input.get("caption", ""),
                        }
                    )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(output)[:8000],
                    }
                )
            conversation.append({"role": "user", "content": results})

        on_event({"type": "result", "text": "I could not finish that safely, so I stopped."})
        return False, conversation
