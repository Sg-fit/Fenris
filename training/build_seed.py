#!/usr/bin/env python
"""Turn a hand-written style seed (training/seed_pairs.json) into chat-format
JSONL (training/seed.jsonl) that the training pipeline can consume.

Each entry in seed_pairs.json becomes one training example, with the shared
Fenris SYSTEM_PROMPT prepended so it matches exactly what the model sees at
runtime and what export_dataset.py emits for real conversations. That
consistency matters — train and inference must use the same system prompt.

Entry formats (see training/seed_pairs.json for live examples):
    {"user": "...", "assistant": "..."}                      # single turn
    {"turns": [["user","..."], ["assistant","..."], ...]}    # multi-turn
Any entry containing a "_comment" key is skipped, so you can leave yourself
notes in the file.

Usage (from the project root):
    python training/build_seed.py
    python training/build_seed.py --in training/seed_pairs.json --out training/seed.jsonl
"""
import argparse
import json
import sys
from pathlib import Path

# Let this run as `python training/build_seed.py` from the project root without
# needing the package installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.brain.prompt import SYSTEM_PROMPT  # noqa: E402


def entry_to_messages(entry: dict, index: int) -> list[dict] | None:
    """Convert one seed entry to a chat message list, or None to skip it.
    Validates that turns alternate user/assistant starting with user and
    ending with assistant, so every example is a clean input -> ideal-reply
    pair (or a clean multi-turn conversation)."""
    if "_comment" in entry:
        return None

    if "turns" in entry:
        turns = entry["turns"]
        if not isinstance(turns, list) or not turns:
            print(f"  [skip] entry {index}: 'turns' must be a non-empty list.")
            return None
        messages = []
        for pair in turns:
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                print(f"  [skip] entry {index}: each turn must be [role, text].")
                return None
            role, content = pair
            if role not in ("user", "assistant") or not str(content).strip():
                print(f"  [skip] entry {index}: bad role or empty text in a turn.")
                return None
            messages.append({"role": role, "content": str(content)})
    else:
        user = str(entry.get("user", "")).strip()
        assistant = str(entry.get("assistant", "")).strip()
        if not user or not assistant:
            print(f"  [skip] entry {index}: needs non-empty 'user' and 'assistant'.")
            return None
        messages = [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]

    # Must start with user, alternate, and end with assistant (the thing we train the model to say).
    roles = [m["role"] for m in messages]
    if roles[0] != "user" or roles[-1] != "assistant":
        print(f"  [skip] entry {index}: must start with a user turn and end with an assistant turn.")
        return None
    if any(roles[i] == roles[i + 1] for i in range(len(roles) - 1)):
        print(f"  [skip] entry {index}: turns must alternate user/assistant.")
        return None

    return [{"role": "system", "content": SYSTEM_PROMPT}] + messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="in_path", type=Path, default=Path("training") / "seed_pairs.json")
    parser.add_argument("--out", type=Path, default=Path("training") / "seed.jsonl")
    args = parser.parse_args()

    if not args.in_path.exists():
        raise SystemExit(f"Seed file not found: {args.in_path}")

    try:
        entries = json.load(open(args.in_path, encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"{args.in_path} isn't valid JSON: {error}")
    if not isinstance(entries, list):
        raise SystemExit("seed_pairs.json must be a JSON list of entries.")

    written = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as out:
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                print(f"  [skip] entry {index}: not an object.")
                continue
            messages = entry_to_messages(entry, index)
            if messages is None:
                continue
            out.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
            written += 1

    print(f"Wrote {written} seed examples to {args.out}")
    if written == 0:
        print("Nothing written — check the skips above (or you only have the _comment entry).")


if __name__ == "__main__":
    main()
