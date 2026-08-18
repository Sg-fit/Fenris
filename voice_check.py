"""Run this before Fenris to verify Windows microphone and speaker settings."""

from voice.listener import Listener
from voice.speaker import Speaker


def main() -> None:
    print("Microphones:")
    microphones = Listener.available_microphones()
    if not microphones:
        print("  No microphones detected.")
    for index, name in enumerate(microphones):
        print(f"  [{index}] {name}")

    speaker = Speaker()
    print("\nInstalled speech voices:")
    for name, voice_id in speaker.available_voices():
        print(f"  {name} ({voice_id})")

    speaker.speak("Fenris voice test successful.")
    print("\nIf you heard that message, your output voice is ready.")
    print("Set MICROPHONE_INDEX or VOICE_NAME in .env only if you want a non-default device or voice.")


if __name__ == "__main__":
    main()
