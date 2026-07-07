from __future__ import annotations

from collections import Counter
from typing import Any

from app.frame_step_scorer import RELATIVE_MOTION_FAMILIES
from app.smoothing import ACTIVE_MOVEMENTS, is_weak_unknown
from app.stream_models import StreamFrame


def _as_text(value: Any) -> str:
    if value in {None, ""}:
        return "unknown"
    return str(value)


def _ordered_counts(values: list[str]) -> dict[str, int]:
    return dict(Counter(values).most_common())


def build_buffer_summary(frames: list[StreamFrame], limit: int = 60) -> dict[str, Any]:
    recent = frames[-limit:]
    if not recent:
        return {
            "frame_count": 0,
            "active_frame_count": 0,
            "hold_frame_count": 0,
            "movement_counts": {},
            "relative_motion_counts": {},
            "dominant_shape_counts": {},
            "location_counts": {},
            "bimanual_relation_counts": {},
            "ideal_input_frames": 0,
            "active_unknown_shape_frames": 0,
            "movement_jitter_frames": 0,
            "input_bucket": "no_frames",
            "dominant_active_movement": None,
        }

    movement_values = [_as_text(frame.primitive.movement) for frame in recent]
    relative_motion_values = [_as_text(getattr(frame.primitive, "relative_motion", "unknown")) for frame in recent]
    dominant_shape_values = [_as_text(frame.primitive.dominant_shape) for frame in recent]
    location_values = [_as_text(frame.primitive.location) for frame in recent]
    relation_values = [_as_text(frame.primitive.bimanual_relation) for frame in recent]

    active_frames = [frame for frame in recent if _as_text(frame.primitive.movement) in ACTIVE_MOVEMENTS]
    hold_frame_count = sum(1 for frame in recent if _as_text(frame.primitive.movement) == "hold")
    active_movement_counts = Counter(_as_text(frame.primitive.movement) for frame in active_frames)
    dominant_active_movement = active_movement_counts.most_common(1)[0][0] if active_movement_counts else None

    ideal_input_frames = sum(
        1
        for frame in active_frames
        if frame.primitive.hand_count == 1
        and _as_text(frame.primitive.dominant_shape) == "five"
        and _as_text(frame.primitive.location) == "unknown"
        and _as_text(frame.primitive.bimanual_relation) == "single_hand"
    )
    active_unknown_shape_frames = sum(
        1
        for frame in active_frames
        if is_weak_unknown("dominant_shape", _as_text(frame.primitive.dominant_shape))
    )
    movement_jitter_frames = sum(
        1
        for frame in recent
        if _as_text(frame.primitive.movement) == "hold"
        or (
            dominant_active_movement is not None
            and _as_text(frame.primitive.movement) in ACTIVE_MOVEMENTS
            and _as_text(frame.primitive.movement) != dominant_active_movement
        )
    )

    if not active_frames:
        input_bucket = "no_active_movement"
    elif active_unknown_shape_frames > 0:
        input_bucket = "shape_unknown_active"
    elif ideal_input_frames >= 3 and movement_jitter_frames == 0:
        input_bucket = "ideal_input"
    elif ideal_input_frames >= 3:
        input_bucket = "ideal_input_with_hold_noise"
    elif movement_jitter_frames > 0:
        input_bucket = "movement_jitter"
    else:
        input_bucket = "mixed_active_input"

    return {
        "frame_count": len(recent),
        "active_frame_count": len(active_frames),
        "hold_frame_count": hold_frame_count,
        "movement_counts": _ordered_counts(movement_values),
        "relative_motion_counts": _ordered_counts(relative_motion_values),
        "dominant_shape_counts": _ordered_counts(dominant_shape_values),
        "location_counts": _ordered_counts(location_values),
        "bimanual_relation_counts": _ordered_counts(relation_values),
        "ideal_input_frames": ideal_input_frames,
        "active_unknown_shape_frames": active_unknown_shape_frames,
        "movement_jitter_frames": movement_jitter_frames,
        "input_bucket": input_bucket,
        "dominant_active_movement": dominant_active_movement,
    }


def _field_match_status(candidate: dict[str, Any], field: str) -> str:
    step_alignment = candidate.get("step_alignment", [])
    matched_fields = {value for step in step_alignment for value in step.get("matched_fields", [])}
    conflict_fields = {value for step in step_alignment for value in step.get("conflict_fields", [])}
    field_modes = candidate.get("span_summary", {}).get("field_modes", {})
    observed = _as_text(field_modes.get(field, "unknown"))

    if field in matched_fields:
        return "matched"
    if field in conflict_fields:
        return "conflict"
    if field == "relative_motion":
        movement = _as_text(field_modes.get("movement", "unknown"))
        if observed in RELATIVE_MOTION_FAMILIES.get(movement, set()):
            return "direction_family"
    if is_weak_unknown(field, observed):
        return "weak_unknown"
    return "not_expected"


def enrich_candidate(candidate: dict[str, Any], suppressed_lookup: dict[int, str] | None = None) -> dict[str, Any]:
    enriched = dict(candidate)
    step_alignment = enriched.get("step_alignment", [])
    suppress_reason = (suppressed_lookup or {}).get(enriched.get("id"))
    reason_pending = list(enriched.get("reason_pending") or [])
    unknown_count = sum(int(step.get("unknown_frames", 0)) for step in step_alignment)
    conflict_count = sum(len(step.get("conflict_fields", [])) for step in step_alignment)
    reject_reasons = list(reason_pending)
    if suppress_reason is not None:
        reject_reasons.append(f"suppressed_by_{suppress_reason}")
    for conflict in enriched.get("wide_conflicts", []):
        reject_reasons.append(f"wide_filter_{conflict}")
    if not reject_reasons and conflict_count > 0:
        reject_reasons.append("field_conflicts")

    reject_reasons = list(dict.fromkeys(reject_reasons))
    enriched["matched_span"] = {
        "start_ts": enriched.get("start_ts"),
        "end_ts": enriched.get("end_ts"),
    }
    enriched["suppress_reason"] = suppress_reason
    enriched["reject_reasons"] = reject_reasons
    enriched["shape_match"] = _field_match_status(enriched, "dominant_shape")
    enriched["movement_match"] = _field_match_status(enriched, "movement")
    enriched["relative_motion_match"] = _field_match_status(enriched, "relative_motion")
    enriched["location_match"] = _field_match_status(enriched, "location")
    enriched["unknown_count"] = unknown_count
    enriched["conflict_count"] = conflict_count
    return enriched


def enrich_candidates(candidates: list[dict[str, Any]], suppressed_candidates: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    suppressed_lookup = {
        int(item["id"]): str(item["reason"])
        for item in (suppressed_candidates or [])
        if item.get("id") is not None and item.get("reason") is not None
    }
    return [enrich_candidate(candidate, suppressed_lookup) for candidate in candidates]


def build_pending_analysis(
    frames: list[StreamFrame],
    last_decision: dict[str, Any] | None,
    top_candidates: list[dict[str, Any]],
    suppressed_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    buffer_summary = build_buffer_summary(frames)
    reasons = list((last_decision or {}).get("reason") or [])
    reason_buckets: list[str] = []

    if any(reason.startswith("suppressed_by_") for reason in reasons):
        reason_buckets.append("suppress")
    if "cooldown" in reasons:
        reason_buckets.append("cooldown")
    if any(reason in {"score_below_confirm_threshold", "top_margin_below_threshold", "not_stable_enough", "partial_step_alignment"} for reason in reasons):
        reason_buckets.append("score_margin_or_stability")
    if buffer_summary["active_unknown_shape_frames"] > 0:
        reason_buckets.append("shape_unknown_active")
    if buffer_summary["movement_jitter_frames"] > 0:
        reason_buckets.append("movement_jitter")
    if buffer_summary["ideal_input_frames"] >= 3:
        reason_buckets.append("ideal_input_present")

    if "suppress" in reason_buckets:
        primary_reason = "suppress"
    elif "cooldown" in reason_buckets:
        primary_reason = "cooldown"
    elif "shape_unknown_active" in reason_buckets:
        primary_reason = "shape_unknown_active"
    elif "score_margin_or_stability" in reason_buckets:
        primary_reason = "score_margin_or_stability"
    elif "movement_jitter" in reason_buckets:
        primary_reason = "movement_jitter"
    elif reason_buckets:
        primary_reason = reason_buckets[0]
    else:
        primary_reason = "none"

    selected_id = (last_decision or {}).get("selected_id")
    enriched_top = enrich_candidates(top_candidates[:1], suppressed_candidates)
    return {
        "status": (last_decision or {}).get("status"),
        "input_bucket": buffer_summary["input_bucket"],
        "primary_reason": primary_reason,
        "reason_buckets": reason_buckets,
        "decision_reasons": reasons,
        "selected_id": selected_id,
        "selected_candidate": enriched_top[0] if enriched_top else None,
    }

