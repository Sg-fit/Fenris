"""Create a local voice profile. Run while alone in a quiet room."""
import sys

from security.identity import VoiceIdentity
from backend.audit import AuditLog
from voice.listener import Listener


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in {"admin", "user"}:
        raise SystemExit("Usage: python enroll_voice.py <name> <admin|user>")
    name, role = sys.argv[1], sys.argv[2]
    listener, samples = Listener(), []
    print("Record 4 samples. Say a different full sentence each time.")
    for number in range(1, 5):
        input(f"Press Enter for sample {number}, then speak... ")
        audio = listener.capture()
        if audio:
            samples.append(audio)
    VoiceIdentity().enroll(name, role, samples)
    AuditLog().record("voice_profile_enrolled", name, role, name, {"samples": len(samples)})
    print(f"Saved local {role} profile for {name}.")


if __name__ == "__main__":
    main()
