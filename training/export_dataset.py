#!/usr/bin/env python
"""Export Fenris conversation history into chat-format JSONL for fine-tuning.

Groups messages by (owner, session_id) and emits one JSON object per session:
{"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}, ...]}

This captures voice and conversational style — NOT tool-call traces, since
MemoryStore only stores final message text, not the intermediate tool calls
that produced it. See training/README.md for what that means for what this
dataset can and can't teach.

Usage:
    python training/export_dataset.py --min-turns 3 --out training/dataset.jsonl
    python training/export_dataset.py --owner loki --dry-run
"""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

# Allow running as `python training/export_dataset.py` from the project root
# without needing -m or an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.brain.prompt import SYSTEM_PROMPT  # noqa: E402

DEFAULT_DB = Path("data") / "fenris_memory.sqlite3"


def _is_degenerate(text: str) -> bool:
    """Drop empty or too-short turns — noise, not signal, for training."""
    return not text or not text.strip() or len(text.strip()) < 2


def load_sessions(database_path: Path, owner: str | None) -> dict[tuple[str, str], list[tuple[str, str]]]:
    with closing(sqlite3.connect(database_path)) as connection:
        if owner:
            rows = connection.execute(
                "SELECT owner, session_id, role, content FROM messages "
                "WHERE owner = ? AND session_id != '' ORDER BY owner, session_id, id",
                (owner,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT owner, session_id, role, content FROM messages "
                "WHERE session_id != '' ORDER BY owner, session_id, id"
            ).fetchall()

    sessions: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for owner_name, session_id, role, content in rows:
        if _is_degenerate(content):
            continue
        sessions.setdefault((owner_name, session_id), []).append((role, content))
    return sessions


def to_examples(sessions: dict, min_turns: int):
    for (owner, session_id), turns in sessions.items():
        exchange_count = sum(1 for role, _ in turns if role == "assistant")
        if exchange_count < min_turns:
            continue
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend({"role": role, "content": content} for role, content in turns)
        yield {"messages": messages, "owner": owner, "session_id": session_id}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to fenris_memory.sqlite3")
    parser.add_argument("--owner", type=str, default=None, help="Only export this person's conversations")
    parser.add_argument("--min-turns", type=int, default=2, help="Minimum assistant turns per session to include it")
    parser.add_argument("--out", type=Path, default=Path("training") / "dataset.jsonl")
    parser.add_argument("--dry-run", action="store_true", help="Print stats only, don't write the file")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"No database found at {args.db}")

    sessions = load_sessions(args.db, args.owner)
    examples = list(to_examples(sessions, args.min_turns))

    print(f"Sessions found: {len(sessions)}")
    print(f"Examples after filtering (min {args.min_turns} assistant turns): {len(examples)}")

    if args.dry_run:
        return

    if not examples:
        print("Nothing to write — no session met --min-turns.")
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps({"messages": example["messages"]}, ensure_ascii=False) + "\n")
    print(f"Wrote {len(examples)} examples to {args.out}")


if __name__ == "__main__":
    main()
