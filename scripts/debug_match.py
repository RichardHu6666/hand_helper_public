#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.matcher import match_primitive, primitive_to_text  # noqa: E402
from app.schemas import Primitive  # noqa: E402
from app.storage import init_db  # noqa: E402


PRESETS = {
    "hello": {
        "hand_count": 1,
        "dominant_side": "signer_right",
        "location": "signer_right_upper",
        "movement": "left_right",
        "bimanual_relation": "single_hand",
        "dominant_shape": "no_gesture",
        "nondominant_shape": "no_hand",
        "duration_ms": 600,
        "repeat_count": 1,
    },
    "up_down": {
        "hand_count": 2,
        "dominant_side": "signer_right",
        "location": "signer_center_middle",
        "movement": "up_down",
        "bimanual_relation": "dual_hand",
        "dominant_shape": "no_gesture",
        "nondominant_shape": "no_gesture",
        "duration_ms": 700,
        "repeat_count": 1,
    },
    "dual": {
        "hand_count": 2,
        "dominant_side": "signer_right",
        "location": "signer_center_middle",
        "movement": "toward_away",
        "bimanual_relation": "same_shape",
        "dominant_shape": "five",
        "nondominant_shape": "five",
        "duration_ms": 800,
        "repeat_count": 1,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug primitive matching.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preset", choices=sorted(PRESETS))
    group.add_argument("--json", dest="json_text")
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.top_k <= 20:
        raise SystemExit("--top-k must be between 1 and 20")

    payload = PRESETS[args.preset] if args.preset else json.loads(args.json_text)
    primitive = Primitive(**payload)

    init_db()
    query_text = primitive_to_text(primitive)
    candidates = match_primitive(primitive, args.top_k)

    print("Query:")
    print(f"  {query_text}")
    print()
    print("Top candidates:")
    for index, candidate in enumerate(candidates, start=1):
        print(
            f"  {index}. {candidate.word} score={candidate.score:.2f} "
            f"reason={candidate.reason}"
        )


if __name__ == "__main__":
    main()

