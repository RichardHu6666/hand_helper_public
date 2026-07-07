from __future__ import annotations

from collections import Counter
from typing import Any

from app.stream_models import StreamFrame


WEAK_UNKNOWN = {None, "", "unknown", "no_gesture"}
ACTIVE_MOVEMENTS = {"left_right", "up_down", "toward_away", "open_close", "repeat"}


def is_weak_unknown(field: str, value: Any) -> bool:
    if field == "dominant_shape" and value in {"no_hand", "no_gesture", "unknown", None, ""}:
        return True
    return value in WEAK_UNKNOWN


def majority_value(frames: list[StreamFrame], field: str) -> Any:
    values = [getattr(frame.primitive, field) for frame in frames[-3:]]
    usable = [value for value in values if not is_weak_unknown(field, value)]
    if not usable:
        return values[-1] if values else "unknown"
    return Counter(usable).most_common(1)[0][0]


def active_movements(frames: list[StreamFrame]) -> list[str]:
    counts = Counter(frame.primitive.movement for frame in frames)
    return [
        movement
        for movement, count in counts.items()
        if movement in ACTIVE_MOVEMENTS and count / max(len(frames), 1) >= 0.25
    ]

