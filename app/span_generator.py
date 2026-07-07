from __future__ import annotations

from app.config import CONFIG
from app.stream_models import Span, StreamFrame


def generate_spans(frames: list[StreamFrame]) -> list[Span]:
    if not frames:
        return []
    latest = frames[-1]
    spans: list[Span] = []
    for duration in CONFIG["WINDOW_DURATIONS_MS"]:
        selected = [
            frame
            for frame in frames
            if latest.timestamp_ms - frame.timestamp_ms <= int(duration)
        ]
        if len(selected) < int(CONFIG["MIN_FRAME_COUNT"]):
            continue
        actual_duration = selected[-1].timestamp_ms - selected[0].timestamp_ms
        if actual_duration < int(CONFIG["MIN_SPAN_MS"]):
            continue
        if actual_duration > int(CONFIG["MAX_SPAN_MS"]):
            continue
        spans.append(Span(duration_ms=int(duration), frames=selected))
    return spans

