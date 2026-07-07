#!/usr/bin/env python
from __future__ import annotations

from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.storage import lite_vocab_entries, load_lite_vocab, lite_vocab_status


def main() -> None:
    entries = load_lite_vocab()
    step_counts = Counter(len(entry.steps) for entry in entries)
    print(lite_vocab_status())
    print("step_distribution", dict(sorted(step_counts.items())))
    for entry in entries[:5]:
        print(entry.id, entry.word_base, entry.primitive_text)


if __name__ == "__main__":
    main()

