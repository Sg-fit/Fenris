import asyncio
import tempfile
import threading
from pathlib import Path

import pyttsx3

from config import Config


class Speaker:
    """Speaks replies aloud, preferring a neural voice with an offline fallback."""

    def __init__(self, hud=None):
        self.hud = hud
        self._engine = None
        self._neural_enabled = Config.TTS_ENGINE == "edge"
        self._neural_failures = 0
        # Mission progress narration can come from a background thread while
        # the main loop (or another mission) is also speaking; serialize so
        # utterances never overlap.
        self._lock = threading.Lock()

    # -- offline Windows voice (pyttsx3) --------------------------------
    def _engine_instance(self):
        if self._engine is None:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", Config.VOICE_RATE)
            self._engine.setProperty("volume", Config.VOICE_VOLUME)
            self._select_voice()
        return self._engine

    def _select_voice(self) -> None:
        """Use the configured Windows voice, otherwise preserve the system default."""
        if not Config.VOICE_NAME:
            return

        wanted = Config.VOICE_NAME.lower()
        for voice in self._engine.getProperty("voices"):
            if wanted in voice.name.lower() or wanted == voice.id.lower():
                self._engine.setProperty("voice", voice.id)
                return
        print(f"Voice '{Config.VOICE_NAME}' was not found; using the Windows default.")

    def available_voices(self) -> list[tuple[str, str]]:
        engine = self._engine_instance()
        return [(voice.name, voice.id) for voice in engine.getProperty("voices")]

    # -- neural voice (edge-tts) ----------------------------------------
    def _speak_neural(self, text: str) -> None:
        import edge_tts
        import sounddevice as sd
        import soundfile as sf

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reply.mp3"
            communicate = edge_tts.Communicate(text, Config.EDGE_VOICE, rate=Config.EDGE_RATE)
            asyncio.run(communicate.save(str(path)))
            data, samplerate = sf.read(str(path), dtype="float32")
        sd.play(data, samplerate)
        sd.wait()

    # -- public API ------------------------------------------------------
    def speak(self, text: str):
        with self._lock:
            print(f"[Fenris] {text}")
            self._publish({"type": "fenris", "text": text})
            self._publish({"type": "state", "value": "speaking"})
            try:
                if self._neural_enabled:
                    try:
                        self._speak_neural(text)
                        self._neural_failures = 0
                        return
                    except Exception as error:
                        self._neural_failures += 1
                        print(f"[Voice] Neural voice unavailable ({error}); using the Windows voice.")
                        if self._neural_failures >= 3:
                            self._neural_enabled = False
                            print("[Voice] Staying on the offline Windows voice for this session.")
                engine = self._engine_instance()
                engine.say(text)
                engine.runAndWait()
            finally:
                self._publish({"type": "state", "value": "idle"})

    def _publish(self, event: dict) -> None:
        if self.hud is not None:
            self.hud.publish(event)
