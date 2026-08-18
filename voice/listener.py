import speech_recognition as sr
import sounddevice as sd

from config import Config


class _SoundDeviceMicrophone(sr.AudioSource):
    """AudioSource adapter used when PyAudio is unavailable."""

    def __init__(self, device_index: int | None = None, chunk_size: int = 1024):
        device = sd.query_devices(device_index, "input")
        self.device_index = device_index
        self.SAMPLE_RATE = int(device["default_samplerate"])
        self.SAMPLE_WIDTH = 2
        self.CHUNK = chunk_size
        self.stream = None

    def __enter__(self):
        if self.stream is not None:
            raise RuntimeError("This audio source is already in use.")
        stream = sd.RawInputStream(
            samplerate=self.SAMPLE_RATE,
            blocksize=self.CHUNK,
            device=self.device_index,
            channels=1,
            dtype="int16",
        )
        stream.start()
        self.stream = _SoundDeviceStream(stream)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class _SoundDeviceStream:
    def __init__(self, stream):
        self._stream = stream

    def read(self, size: int) -> bytes:
        data, _overflowed = self._stream.read(size)
        return bytes(data)

    def close(self) -> None:
        self._stream.close()


class Listener:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.microphone = self._create_microphone()
        self._calibrated = False

    @staticmethod
    def _create_microphone():
        try:
            import pyaudio  # noqa: F401
        except ImportError:
            return _SoundDeviceMicrophone(device_index=Config.MICROPHONE_INDEX)
        return sr.Microphone(device_index=Config.MICROPHONE_INDEX)

    @staticmethod
    def available_microphones() -> list[str]:
        try:
            import pyaudio  # noqa: F401
        except ImportError:
            devices = sd.query_devices()
            return [device["name"] for device in devices if device["max_input_channels"] > 0]
        return sr.Microphone.list_microphone_names()

    def capture(self, timeout: float | None = None, quiet: bool = False):
        """Capture a single utterance for both transcription and speaker matching."""
        try:
            with self.microphone as source:
                if not self._calibrated:
                    # Calibrate once at startup; dynamic energy adjustment keeps
                    # tracking the room afterwards without a 1-second pause per loop.
                    self.recognizer.adjust_for_ambient_noise(source, duration=1)
                    self._calibrated = True
                if not quiet:
                    print("Listening...")
                return self.recognizer.listen(
                    source,
                    timeout=timeout if timeout is not None else Config.LISTEN_TIMEOUT,
                    phrase_time_limit=Config.PHRASE_TIME_LIMIT,
                )
        except sr.WaitTimeoutError:
            return None

    def transcribe(self, audio, quiet: bool = False):
        try:
            if Config.VOICE_INPUT_MODE == "whisper":
                if not quiet:
                    print("Transcribing locally with Whisper...")
                text = self.recognizer.recognize_whisper(audio, model=Config.WHISPER_MODEL)
            else:
                text = self.recognizer.recognize_google(audio)
            if not quiet:
                print(f"[You] {text}")
            return text
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            print("Speech recognition is unavailable. Check your internet connection or use VOICE_INPUT_MODE=whisper.")
            return None
        except Exception as error:
            print(f"Speech recognition failed: {error}")
            return None

    def listen(self):
        audio = self.capture()
        return self.transcribe(audio) if audio else None
