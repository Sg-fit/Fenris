import base64
import binascii
import io
import re
import threading
import time
import uuid
import webbrowser
from difflib import SequenceMatcher
from urllib.parse import quote

from config import Config
from core.brain import Brain
from core.proactive import ProactiveDelivery
from memory.memory import ConversationMemory
from security.identity import Identity, VoiceIdentity
from security.policy import can_access_memory
from skills.manager import SkillManager
from ui.server import create_hud
from voice.listener import Listener
from voice.speaker import Speaker


class _MissionCancelled(Exception):
    """Raised from within an on_event callback to unwind out of a Brain.reply()
    call in progress when the user cancels a running mission."""


class Assistant:
    def __init__(self):
        self.hud = create_hud()
        self.hud.start()
        self.listener = Listener()
        self.speaker = Speaker(hud=self.hud)
        self.brain = Brain()
        self.memories: dict[str, ConversationMemory] = {}
        self.skills = SkillManager()
        self.identity = VoiceIdentity()
        self._greeted: set[str] = set()
        self._last_speaker: Identity | None = None
        # One background worker per actor at a time, so a running mission
        # doesn't block the main loop from listening, while still never
        # sending two concurrent brain calls for the same person.
        self._active_threads: dict[str, threading.Thread] = {}
        self._cancelled: set[str] = set()
        # A session id groups one actor's messages into a single continuous
        # run (open to close) in persistent storage. _session_pending holds a
        # previous session's messages while we're waiting to hear whether to
        # resume them.
        self._session_ids: dict[str, str] = {}
        self._session_pending: dict[str, list[dict]] = {}
        # Set while handle() is synchronously routing an utterance, so the
        # proactive-delivery thread never starts speaking mid-turn. The
        # actual background mission duration is covered separately by
        # _active_threads liveness (see turn_in_progress()).
        self._processing = False
        self.proactive = ProactiveDelivery(self)

    SLEEP_COMMANDS = {"go to sleep", "never mind", "nevermind", "that's all", "that is all"}
    CANCEL_COMMANDS = {"stop the mission", "cancel the mission", "cancel that mission"}
    CONTINUE_WORDS = ("continue", "yes", "yeah", "resume", "pick up", "keep going", "y")
    FRESH_WORDS = ("fresh", "no", "nope", "start over", "new session", "start fresh", "n")

    def run(self):
        self.speaker.speak("Fenris.")
        if self.brain.available:
            print("[Status] Online AI conversation is enabled.")
        else:
            print("[Status] Running local voice mode. Not abloe to enable online conversation.")

        self.proactive.start()
        if Config.PROACTIVE_ENABLED:
            print("[Status] Proactive delivery is enabled.")

        wake_enabled = Config.WAKE_WORD_ENABLED
        if wake_enabled:
            print(f'[Status] Say "{Config.WAKE_WORDS[0].capitalize()}" to wake me.')
        if self.hud.active:
            print(f"[Status] Visual HUD: {self.hud.url}")
            if Config.HUD_AUTO_OPEN:
                webbrowser.open(self.hud.url)
        active_until = 0.0

        while True:
            # Typed messages and uploads from the HUD are explicit, so they are
            # always handled and never need the wake word.
            if self._handle_hud_inputs():
                active_until = time.monotonic() + Config.WAKE_ACTIVE_SECONDS

            sleeping = wake_enabled and time.monotonic() >= active_until
            self.hud.publish({"type": "state", "value": "sleeping" if sleeping else "listening"})
            audio = self.listener.capture(quiet=sleeping)
            if audio is None:
                continue
            text = self.listener.transcribe(audio, quiet=sleeping)
            if text is None:
                continue

            if sleeping:
                command = self._strip_wake_word(text, fuzzy=True)
                if command is None:
                    # Not addressed to Fenris; stay asleep. Print what was heard
                    # so a misheard wake word is easy to spot and add to WAKE_WORDS.
                    print(f"[Standby] Heard {text!r} — no wake word, ignoring.")
                    continue
                print(f"[You] {text}")
                speaker = self._identify(audio)
                self.hud.publish({"type": "user", "text": text, "speaker": speaker.name})
                greeting = self._greeting_for(speaker)
                if command:
                    if greeting:
                        self.speaker.speak(greeting)
                    self.handle(command, speaker)
                else:
                    self.speaker.speak(greeting or "Yes?")
                active_until = time.monotonic() + Config.WAKE_ACTIVE_SECONDS
                continue

            speaker = self._identify(audio)
            self.hud.publish({"type": "user", "text": text, "speaker": speaker.name})
            greeting = self._greeting_for(speaker)
            if greeting:
                self.speaker.speak(greeting)
            if wake_enabled and text.lower().strip(" ,.!?") in self.SLEEP_COMMANDS:
                self.speaker.speak("Going to sleep.")
                active_until = 0.0
                continue

            stripped = self._strip_wake_word(text)
            self.handle(stripped if stripped else text, speaker)
            if wake_enabled:
                active_until = time.monotonic() + Config.WAKE_ACTIVE_SECONDS

    def _identify(self, audio) -> Identity:
        speaker = self.identity.identify(audio)
        if speaker.role in {"user", "admin"}:
            self._last_speaker = speaker
        return speaker

    def _typed_identity(self) -> Identity:
        """Who typed/uploaded from the HUD: the last recognized voice, or the owner."""
        if self._last_speaker is not None:
            return self._last_speaker
        if Config.OWNER_NAME:
            role = self.identity.profiles.get(Config.OWNER_NAME, {}).get("role", "admin")
            return Identity(Config.OWNER_NAME, role, 1.0)
        for name, profile in self.identity.profiles.items():
            if profile.get("role") == "admin":
                return Identity(name, "admin", 1.0)
        return Identity("owner", "admin", 1.0)

    def _handle_hud_inputs(self) -> bool:
        """Process any typed messages / uploads from the HUD. Returns True if any."""
        items = self.hud.drain_inputs()
        if not items:
            return False
        for item in items:
            text = (item.get("text") or "").strip()
            images, documents = self._split_attachments(item.get("attachments", []))
            if not text and not images and not documents:
                continue
            speaker = self._typed_identity()
            note = " ".join(f"[{name}]" for name, _ in documents) if documents else ""
            echo = (text + (" " + note if note else "") + (" [image]" if images else "")).strip()
            self.hud.publish({"type": "user", "text": echo, "speaker": speaker.name})

            message = text
            for name, doc_text in documents:
                message += f"\n\n[Attached document: {name}]\n{doc_text}"
            if not message.strip():
                message = "(see the attached file)"
            self.handle(message, speaker, images=images)
        return True

    def _split_attachments(self, attachments: list) -> tuple[list, list]:
        """Return (images, documents). images: [{media_type, data}]; documents: [(name, text)]."""
        images, documents = [], []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            name = str(attachment.get("name", "file"))
            mime = str(attachment.get("mime", ""))
            data = attachment.get("data", "")
            try:
                raw = base64.b64decode(data, validate=False)
            except (binascii.Error, ValueError):
                continue
            if mime.startswith("image/"):
                images.append({"media_type": mime, "data": data})
            else:
                extracted = self._extract_document(name, mime, raw)
                if extracted:
                    documents.append((name, extracted[: Config.ATTACH_MAX_DOC_CHARS]))
                else:
                    print(f"[Upload] Could not read {name}; unsupported or empty file.")
        return images, documents

    @staticmethod
    def _extract_document(name: str, mime: str, raw: bytes) -> str | None:
        lowered = name.lower()
        try:
            if lowered.endswith(".pdf") or mime == "application/pdf":
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(raw))
                return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
            if lowered.endswith(".docx") or mime.endswith("wordprocessingml.document"):
                import docx

                document = docx.Document(io.BytesIO(raw))
                return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
            # Plain text, markdown, csv, code, etc.
            return raw.decode("utf-8", errors="replace").strip()
        except Exception as error:  # keep one bad file from stopping the rest
            print(f"[Upload] Failed to read {name}: {error}")
            return None

    def _greeting_for(self, speaker: Identity) -> str | None:
        """Greet enrolled people the first time they are recognized this session."""
        if speaker.role in {"user", "admin"} and speaker.name not in self._greeted:
            self._greeted.add(speaker.name)
            return f"Welcome back, {speaker.name.capitalize()}."
        return None

    @staticmethod
    def _strip_wake_word(text: str, fuzzy: bool = False) -> str | None:
        """Return the command with the wake word removed.

        Returns None when no wake word is present, and an empty string when the
        utterance is only the wake word itself ("Fenris?"). With fuzzy=True,
        close mishearings ("Fenrir", "fen risk") also count as the wake word.
        """
        targets = [wake.replace(" ", "") for wake in Config.WAKE_WORDS]

        def matches(word: str) -> bool:
            if word in targets:
                return True
            if not fuzzy:
                return False
            return any(
                SequenceMatcher(None, word, target).ratio() >= Config.WAKE_SENSITIVITY
                for target in targets
            )

        tokens = list(re.finditer(r"\S+", text))
        cleaned = [re.sub(r"[^a-z']", "", token.group().lower()) for token in tokens]
        for index, word in enumerate(cleaned):
            if word and matches(word):
                start, end = tokens[index].start(), tokens[index].end()
            elif (
                index + 1 < len(cleaned)
                and word
                and cleaned[index + 1]
                and matches(word + cleaned[index + 1])
            ):
                start, end = tokens[index].start(), tokens[index + 1].end()
            else:
                continue
            return (text[:start] + text[end:]).strip(" ,.!?")
        return None

    def handle(self, text: str, speaker: Identity = Identity(), images: list | None = None):
        # Set for the synchronous routing below, so proactive delivery never
        # starts speaking mid-turn; the background mission duration itself is
        # covered by _active_threads liveness (see turn_in_progress()).
        self._processing = True
        try:
            print(f"[Identity] {speaker.name} ({speaker.role}; confidence {speaker.confidence:.2f})")

            # Uploads (images/documents) go straight to the brain; the local
            # command and skill shortcuts are for plain spoken/typed phrases.
            if images:
                self._dispatch(text, speaker, images)
                return

            command = text.lower().strip()
            if command in {"goodbye", "exit", "quit", "shutdown"}:
                self.speaker.speak("Goodbye.")
                raise SystemExit(0)

            if command in {"list profiles", "list users"}:
                if speaker.role != "admin":
                    self.speaker.speak("That information is available to the administrator only.")
                    return
                names = ", ".join(self.identity.profiles) or "no enrolled profiles"
                self.speaker.speak(f"Enrolled profiles: {names}.")
                return

            if command.startswith("read memory "):
                owner = command.removeprefix("read memory ").strip()
                if not can_access_memory(speaker, owner):
                    self.speaker.speak("You can access only your own conversation memory.")
                    return
                messages = self.brain.memory_history(owner, speaker.name, speaker.role)
                if not messages:
                    self.speaker.speak(f"There is no current-session conversation memory for {owner}.")
                    return
                latest = messages[-1]["content"]
                self.speaker.speak(f"{owner} has {len(messages)} stored messages. The latest is: {latest}")
                return

            if command.startswith("clear memory "):
                owner = command.removeprefix("clear memory ").strip()
                if not can_access_memory(speaker, owner):
                    self.speaker.speak("You can clear only your own conversation memory.")
                    return
                self.memories.pop(owner, None)
                if self.brain.clear_memory(owner, speaker.name, speaker.role):
                    self.speaker.speak(f"Conversation memory cleared for {owner}.")
                else:
                    self.speaker.speak("I cleared the current-session memory, but could not reach persistent memory.")
                return

            if command in {"clear memory", "forget our conversation"}:
                if speaker.role == "guest":
                    self.speaker.speak("Guests do not have saved conversation memory.")
                    return
                self.memories.pop(speaker.name, None)
                if self.brain.clear_memory(speaker.name, speaker.name, speaker.role):
                    self.speaker.speak("Conversation memory cleared.")
                else:
                    self.speaker.speak("I cleared the current-session memory, but could not reach persistent memory.")
                return

            local_reply = self.skills.handle(text)
            if local_reply:
                self.speaker.speak(local_reply)
                return

            self._dispatch(text, speaker, None)
        finally:
            self._processing = False

    def turn_in_progress(self) -> bool:
        """True while handle() is synchronously routing an utterance, or
        while any actor's background mission thread is still running —
        proactive delivery must never speak over either."""
        if self._processing:
            return True
        return any(thread.is_alive() for thread in self._active_threads.values())

    def _dispatch(self, text: str, speaker: Identity, images: list | None):
        """Run a turn on a background worker so a long-running mission never
        blocks the main loop from listening. At most one worker per actor at a
        time; a new utterance while theirs is still running is either a cancel
        command or gets a short "still working" reply instead of overlapping."""
        existing = self._active_threads.get(speaker.name)
        if existing is not None and existing.is_alive():
            if text.lower().strip(" ,.!?") in self.CANCEL_COMMANDS:
                self._cancelled.add(speaker.name)
                self.speaker.speak("Stopping the mission.")
            else:
                self.speaker.speak("Still working on that — I'll let you know.")
            return

        thread = threading.Thread(target=self._run_converse, args=(text, speaker, images), daemon=True)
        self._active_threads[speaker.name] = thread
        thread.start()

    def _run_converse(self, text: str, speaker: Identity, images: list | None):
        try:
            self._converse(text, speaker, images)
        finally:
            self._cancelled.discard(speaker.name)

    def _converse(self, text: str, speaker: Identity, images: list | None):
        """Send a turn (optionally with images) to the brain and speak the reply.

        A single turn may cover many steps if the request is a mission: progress
        narration is spoken as it arrives via on_event, and the return value is
        whichever text ends the turn — a final result, or a question if the
        mission paused to ask something (it resumes transparently next time this
        actor speaks)."""
        if speaker.name in self._session_pending:
            self._resolve_session_choice(text, speaker)
            return

        if speaker.role == "guest":
            memory = ConversationMemory()
            session_id = str(uuid.uuid4())
        else:
            memory = self.memories.get(speaker.name)
            if memory is None:
                if speaker.name not in self._session_ids:
                    self._session_ids[speaker.name] = str(uuid.uuid4())
                    _, previous = self.brain.last_session(speaker.name, speaker.name, speaker.role)
                    if previous:
                        self._session_pending[speaker.name] = previous
                        self.speaker.speak("Pick up where we left off, or start fresh?")
                        return
                memory = ConversationMemory()
                self.memories[speaker.name] = memory
            session_id = self._session_ids[speaker.name]

        memory.add("user", text)
        self.hud.publish({"type": "state", "value": "thinking"})

        def on_event(event: dict) -> None:
            if speaker.name in self._cancelled:
                raise _MissionCancelled()
            event_type = event.get("type")
            if event_type == "progress":
                self.speaker.speak(event.get("text", ""))
            elif event_type == "media":
                location = event.get("location", "")
                if event.get("source") == "local":
                    url = f"{self.hud.url}/media?path={quote(location)}"
                else:
                    url = location
                self.hud.publish(
                    {"type": "media", "kind": event.get("kind"), "url": url, "caption": event.get("caption", "")}
                )

        try:
            reply = self.brain.reply(
                memory.messages, speaker.name, speaker.role, images=images, on_event=on_event, session_id=session_id
            )
        except _MissionCancelled:
            return
        memory.add("assistant", reply)
        self.speaker.speak(reply)

    def _resolve_session_choice(self, text: str, speaker: Identity) -> None:
        """Interpret the answer to "pick up where we left off, or start fresh?" """
        normalized = text.lower().strip(" ,.!?")

        def matches(words: tuple[str, ...]) -> bool:
            return any(re.search(rf"\b{re.escape(word)}\b", normalized) for word in words)

        pending = self._session_pending.get(speaker.name, [])
        if matches(self.CONTINUE_WORDS):
            memory = ConversationMemory()
            memory.load(pending)
            self.memories[speaker.name] = memory
            self._session_pending.pop(speaker.name, None)
            self.speaker.speak("Picking up where we left off.")
        elif matches(self.FRESH_WORDS):
            self.memories[speaker.name] = ConversationMemory()
            self._session_pending.pop(speaker.name, None)
            self.speaker.speak("Starting fresh.")
        else:
            self.speaker.speak("Sorry — pick up where we left off, or start fresh?")
