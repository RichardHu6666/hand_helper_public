from __future__ import annotations

import re
from typing import Any


FIELDS = [
    "hand_count",
    "dominant_shape",
    "nondominant_shape",
    "movement",
    "relative_motion",
    "location",
    "bimanual_relation",
]

STEP_RE = re.compile(r"^\s*step(?P<index>\d+)\b(?P<body>.*)$")
PAIR_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>[^\s|]+)")


def parse_primitive_text(text: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for raw_part in (text or "").split("|"):
        part = raw_part.strip()
        if not part:
            continue
        match = STEP_RE.match(part)
        if not match:
            continue
        expected = {field: "unknown" for field in FIELDS}
        for pair in PAIR_RE.finditer(match.group("body")):
            key = pair.group("key")
            if key in expected:
                expected[key] = pair.group("value")
        steps.append({"step_index": int(match.group("index")), "expected": expected})
    steps.sort(key=lambda item: item["step_index"])
    return steps

