from __future__ import annotations

from collections import Counter
from typing import Any

from app.stream_models import Span


def duration_score(span: Span) -> float:
    duration = span.actual_duration_ms
    if 400 <= duration <= 1600:
        return 1.0
    if duration < 400:
        return max(0.4, duration / 400)
    return max(0.4, 1.0 - (duration - 1600) / 1400)


def step_signature(expected: dict[str, str]) -> str:
    return "|".join(
        [
            str(expected.get("hand_count", "unknown")),
            str(expected.get("movement", "unknown")),
            str(expected.get("location", "unknown")),
            str(expected.get("bimanual_relation", "unknown")),
        ]
    )


def loose_signature(expected: dict[str, str]) -> str:
    return "|".join(
        [
            str(expected.get("hand_count", "unknown")),
            str(expected.get("movement", "unknown")),
            str(expected.get("bimanual_relation", "unknown")),
        ]
    )


def build_signature_counts(entries: list[Any]) -> tuple[Counter[str], Counter[str]]:
    step_counts: Counter[str] = Counter()
    loose_counts: Counter[str] = Counter()
    for entry in entries:
        for step in getattr(entry, "steps", []):
            expected = step["expected"]
            step_counts[step_signature(expected)] += 1
            loose_counts[loose_signature(expected)] += 1
    return step_counts, loose_counts


def ambiguity_penalty(
    steps: list[dict[str, Any]],
    step_signature_counts: Counter[str] | None = None,
    loose_signature_counts: Counter[str] | None = None,
) -> float:
    if not steps or step_signature_counts is None or loose_signature_counts is None:
        return 0.0
    penalties = []
    for step in steps:
        expected = step["expected"]
        step_count = max(0, step_signature_counts.get(step_signature(expected), 1) - 1)
        loose_count = max(0, loose_signature_counts.get(loose_signature(expected), 1) - 1)
        penalties.append(step_count * 0.01 + loose_count * 0.002)
    return round(min(0.06, max(penalties or [0.0])), 4)


def score_candidate(
    span: Span,
    summary: dict[str, Any],
    alignment: dict[str, Any],
    wide_conflicts: list[str],
    expected_unknown_ratio: float = 0.0,
    ambiguity: float = 0.0,
) -> dict[str, Any]:
    unknown_penalty = min(0.25, float(summary["unknown_ratio"]) * 0.25 + expected_unknown_ratio * 0.24)
    conflict_penalty = min(0.25, 0.03 * alignment.get("conflict_count", 0) + 0.05 * len(wide_conflicts))
    ambiguity = max(0.0, min(0.10, ambiguity))
    boundary_quality = 0.5
    dur_score = duration_score(span)
    final = (
        0.70 * float(alignment["score"])
        + 0.15 * float(summary["stability_score"])
        + 0.10 * dur_score
        + 0.05 * boundary_quality
        - unknown_penalty
        - conflict_penalty
        - ambiguity
    )
    final = max(0.0, min(1.0, final))
    return {
        "step_alignment_score": round(float(alignment["score"]), 4),
        "span_stability_score": round(float(summary["stability_score"]), 4),
        "duration_score": round(dur_score, 4),
        "boundary_quality_score": boundary_quality,
        "unknown_penalty": round(unknown_penalty, 4),
        "conflict_penalty": round(conflict_penalty, 4),
        "ambiguity_penalty": round(ambiguity, 4),
        "overlap_penalty": 0.0,
        "final_score": round(final, 4),
    }

