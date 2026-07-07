#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.sentence_composer import ConfirmedWord, SentenceComposer, SessionSentenceState, state_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--words", nargs="*")
    parser.add_argument("--json")
    args = parser.parse_args()
    words = args.words or []
    if args.json:
        data = json.loads(Path(args.json).read_text(encoding="utf-8"))
        words = [item.get("word") or item.get("word_base") for item in data.get("confirmed_words", [])]
    state = SessionSentenceState()
    for idx, word in enumerate(words, start=1):
        state.confirmed_words.append(ConfirmedWord(id=idx, word_base=word, confidence=1.0, start_ts=str(idx), end_ts=str(idx), alternatives=[]))
    composer = SentenceComposer()
    composer.compose_state(state)
    print(json.dumps(state_payload("debug", state), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

