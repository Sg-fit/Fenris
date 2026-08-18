from dotenv import load_dotenv
import os

load_dotenv()


class Config:
    APP_NAME = "Fenris"

    # The assistant remains usable without a model key: it will explain how to
    # configure one rather than failing during startup.
    ASSISTANT_NAME = "Fenris"
    # "auto" enables online conversation only when ANTHROPIC_API_KEY exists.
    # Set to "offline" to keep Fenris local even when a key is configured.
    ASSISTANT_MODE = os.getenv("ASSISTANT_MODE", "auto").lower()
    BACKEND_URL = os.getenv("FENRIS_BACKEND_URL", "http://127.0.0.1:8000")
    # A live session (app open to close) is never trimmed by this — it's only
    # a hard safety ceiling for the "read memory" voice command and for
    # fetching a previous session's full history when offering to resume it.
    MAX_HISTORY_MESSAGES = 500

    VOICE_RATE = 270
    VOICE_VOLUME = 1.0
    # Spoken output: "edge" uses free Microsoft neural voices (internet) and
    # falls back to the offline Windows voice automatically; "offline" keeps
    # the Windows voice only.
    TTS_ENGINE = os.getenv("TTS_ENGINE", "edge").lower()
    EDGE_VOICE = os.getenv("EDGE_VOICE", "en-GB-RyanNeural")
    EDGE_RATE = os.getenv("EDGE_RATE", "+50%")

    # Visual HUD served locally to the browser.
    HUD_ENABLED = os.getenv("HUD_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    HUD_PORT = int(os.getenv("HUD_PORT", "8765"))
    HUD_AUTO_OPEN = os.getenv("HUD_AUTO_OPEN", "true").lower() in {"1", "true", "yes", "on"}

    # Typed input and file/image uploads from the HUD are attributed to this
    # person when no voice has been recognized yet in the session. Match it to an
    # enrolled admin profile name so typed and spoken memory stay together. When
    # empty, the first enrolled admin profile (or "owner") is used.
    OWNER_NAME = os.getenv("OWNER_NAME", "").strip()
    # Extracted document text is truncated to this many characters per file to
    # stay within the model's per-message limit.
    ATTACH_MAX_DOC_CHARS = int(os.getenv("ATTACH_MAX_DOC_CHARS", "8000"))
    # "google" is the quickest option; "whisper" runs recognition locally once
    # its model has been downloaded. Select either in .env with VOICE_INPUT_MODE.
    VOICE_INPUT_MODE = os.getenv("VOICE_INPUT_MODE", "google").lower()
    VOICE_NAME = os.getenv("VOICE_NAME")
    MICROPHONE_INDEX = (
        int(os.getenv("MICROPHONE_INDEX"))
        if os.getenv("MICROPHONE_INDEX") is not None
        else None
    )
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
    VOICE_PROFILE_THRESHOLD = float(os.getenv("VOICE_PROFILE_THRESHOLD", "0.88"))
    # Path to a password-hash file stored outside this project (for example, on
    # an encrypted removable drive). Fenris never stores the password itself.
    ADDON_CREATOR_AUTH_FILE = os.getenv("FENRIS_ADDON_CREATOR_AUTH_FILE")

    LISTEN_TIMEOUT = 5
    PHRASE_TIME_LIMIT = 10

    # Wake word ("Fenris, ...") settings. WAKE_WORDS is a comma-separated list of
    # accepted spellings, since speech recognition may transcribe names oddly.
    WAKE_WORD_ENABLED = os.getenv("WAKE_WORD_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    WAKE_WORDS = tuple(
        word.strip().lower()
        for word in os.getenv(
            "WAKE_WORDS",
            "fenris,fenriss,fenrys,fen ris,fenrir,fenriz,venris,fenres,phineas",
        ).split(",")
        if word.strip()
    )
    # How long Fenris stays awake (seconds) after each interaction before it
    # requires the wake word again.
    WAKE_ACTIVE_SECONDS = float(os.getenv("WAKE_ACTIVE_SECONDS", "45"))
    # Fuzzy wake-word match threshold (0-1). Lower catches more mishearings but
    # wakes on more unrelated words; 0.8 accepts "Fenrir" but not "fairies".
    WAKE_SENSITIVITY = float(os.getenv("WAKE_SENSITIVITY", "0.8"))

    # Proactive delivery: Fenris speaking unprompted (reminders coming due),
    # without the wake word. False fully disables the background poll thread.
    PROACTIVE_ENABLED = os.getenv("PROACTIVE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    PROACTIVE_POLL_SECONDS = float(os.getenv("PROACTIVE_POLL_SECONDS", "30"))
    # Local HH:MM window during which proactive speech is suppressed entirely.
    PROACTIVE_QUIET_START = os.getenv("PROACTIVE_QUIET_START", "22:00")
    PROACTIVE_QUIET_END = os.getenv("PROACTIVE_QUIET_END", "08:00")

