#!/usr/bin/env python
"""Merge the hand-written style seed and the corrected real-usage export into
one shuffled training file (training/dataset.jsonl).

Inputs (either may be missing — you can start with just one):
    training/seed.jsonl   <- from build_seed.py       (route 3: style seed)
    training/real.jsonl   <- from export_dataset.py   (route 1: corrected usage)

Deduplicates identical lines, shuffles with a fixed seed so runs are
reproducible, and reports how many examples came from each source so you can
see the balance (let the real corrected usage grow to be the bulk over time).

Usage (from the project root):
    python training/combine_dataset.py
    python training/combine_dataset.py --inputs training/seed.jsonl training/real.jsonl --out training/dataset.jsonl
"""
import argparse
import json
import random
from pathlib import Path


def load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            json.loads(raw)  # keep only valid JSONL rows
        except json.JSONDecodeError:
            print(f"  [warn] skipping a malformed line in {path}")
            continue
        lines.append(raw)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--inputs",
        type=Path,
        nargs="+",
        default=[Path("training") / "seed.jsonl", Path("training") / "real.jsonl"],
    )
    parser.add_argument("--out", type=Path, default=Path("training") / "dataset.jsonl")
    parser.add_argument("--seed", type=int, default=0, help="Shuffle seed (reproducible).")
    args = parser.parse_args()

    combined: list[str] = []
    seen: set[str] = set()
    total_before_dedup = 0
    for path in args.inputs:
        lines = load_lines(path)
        total_before_dedup += len(lines)
        kept = 0
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            combined.append(line)
            kept += 1
        print(f"  {path}: {len(lines)} examples ({kept} new after dedup)")

    if not combined:
        raise SystemExit(
            "No examples found. Run build_seed.py and/or export_dataset.py first "
            "so training/seed.jsonl and/or training/real.jsonl exist."
        )

    random.seed(args.seed)
    random.shuffle(combined)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(combined) + "\n", encoding="utf-8")

    duplicates = total_before_dedup - len(combined)
    print(f"\nWrote {len(combined)} examples to {args.out}"
          + (f" ({duplicates} duplicate(s) removed)" if duplicates else ""))
    print(f"Next: python training/train_lora.py --dataset {args.out} "
          f"--base-model Qwen/Qwen2.5-7B-Instruct --output-dir training/output/fenris-lora")


if __name__ == "__main__":
    main()
