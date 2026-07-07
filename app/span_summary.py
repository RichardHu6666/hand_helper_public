from __future__ import annotations

from collections import Counter
from typing import Any

from app.smoothing import active_movements, is_weak_unknown
from app.stream_models import Span


SUMMARY_FIELDS = [
    "hand_count",
    "movement",
    "relative_motion",
    "location",
    "bimanual_relation",
    "dominant_shape",
    "nondominant_shape",
]


def summarize_span(span: Span) -> dict[str, Any]:
    field_modes: dict[str, Any] = {}
    field_supports: dict[str, float] = {}
    unknown_count = 0
    total_count = 0
    supports = []
    for field in SUMMARY_FIELDS:
        values = [getattr(frame.primitive, field) for frame in span.frames]
        counts = Counter(values)
        mode, count = counts.most_common(1)[0]
        field_modes[field] = str(mode)
        support = count / max(len(values), 1)
        field_supports[field] = round(support, 4)
        supports.append(support)
        for frame, value in zip(span.frames, values):
            total_count += 1
            if field == "nondominant_shape" and value == "no_hand" and frame.primitive.hand_count == 1:
                continue
            if is_weak_unknown(field, value):
                unknown_count += 1
    return {
        "field_modes": field_modes,
        "field_supports": field_supports,
        "active_movements": active_movements(span.frames),
        "unknown_ratio": round(unknown_count / max(total_count, 1), 4),
        "stability_score": round(sum(supports) / max(len(supports), 1), 4),
    }

