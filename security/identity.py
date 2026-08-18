import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from config import Config


PROFILE_PATH = Path("data") / "voice_profiles.json"


@dataclass(frozen=True)
class Identity:
    name: str = "guest"
    role: str = "guest"
    confidence: float = 0.0


class VoiceIdentity:
    """Local speaker-profile matching. Treat results as a convenience, not proof."""

    def __init__(self, profile_path: Path = PROFILE_PATH):
        self.profile_path = profile_path
        self.profiles = self._load()

    def _load(self) -> dict:
        if not self.profile_path.exists():
            return {}
        try:
            return json.loads(self.profile_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print("[Security] Profile file is invalid; treating speakers as guests.")
            return {}

    @staticmethod
    def embedding(audio) -> np.ndarray:
        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        signal = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if signal.size < 2048:
            raise ValueError("Voice sample is too short.")
        frames = np.array_split(signal, max(2, signal.size // 512))
        spectra = [np.log1p(np.abs(np.fft.rfft(frame * np.hanning(frame.size))[:64])) for frame in frames if frame.size >= 64]
        features = np.asarray(spectra)
        vector = np.concatenate((features.mean(axis=0), features.std(axis=0)))
        norm = np.linalg.norm(vector)
        if norm == 0:
            raise ValueError("Voice sample had no usable audio.")
        return vector / norm

    def identify(self, audio) -> Identity:
        try:
            vector = self.embedding(audio)
        except ValueError:
            return Identity()
        best_name, best_profile, best_score = "guest", None, -1.0
        for name, profile in self.profiles.items():
            score = float(np.dot(vector, np.asarray(profile["embedding"], dtype=np.float32)))
            if score > best_score:
                best_name, best_profile, best_score = name, profile, score
        if best_profile and best_score >= Config.VOICE_PROFILE_THRESHOLD:
            return Identity(best_name, best_profile.get("role", "user"), best_score)
        return Identity(confidence=max(best_score, 0.0))

    def enroll(self, name: str, role: str, samples: list) -> None:
        vectors = [self.embedding(sample) for sample in samples]
        if len(vectors) < 3:
            raise ValueError("At least three valid samples are required.")
        average = np.mean(vectors, axis=0)
        average /= np.linalg.norm(average)
        self.profiles[name] = {"role": role, "embedding": average.tolist()}
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(json.dumps(self.profiles, indent=2), encoding="utf-8")
