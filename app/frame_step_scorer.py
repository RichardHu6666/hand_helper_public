from __future__ import annotations

from typing import Any

from app.config import CONFIG
from app.smoothing import is_weak_unknown
from app.wide_filter import coarse_side


RELATIVE_MOTION_FAMILIES = {
    "left_right": {"left_right", "left_to_right", "right_to_left"},
    "up_down": {"up_down", "up_to_down", "down_to_up"},
    "toward_away": {"toward_away", "toward", "away"},
    "hold": {"hold"},
    "open_close": {"open_close"},
    "repeat": {"repeat"},
}


def compatible(field: str, observed: str, expected: str) -> bool:
    if field == "bimanual_relation":
        return {observed, expected} <= {"dual_hand", "same_shape", "different_shape"}
    if field == "location":
        return coarse_side(observed) == coarse_side(expected) and coarse_side(observed) != "unknown"
    return False


def movement_matches(observed_movement: str, observed_relative_motion: str, expected_movement: str) -> bool:
    if observed_movement == expected_movement:
        return True
    return observed_relative_motion in RELATIVE_MOTION_FAMILIES.get(expected_movement, set())


def relative_motion_match_score(
    observed_relative_motion: str,
    observed_movement: str,
    expected_relative_motion: str,
) -> float:
    if observed_relative_motion == expected_relative_motion:
        return 1.0
    for coarse_movement, family in RELATIVE_MOTION_FAMILIES.items():
        if expected_relative_motion not in family:
            continue
        if observed_relative_motion in family:
            return 0.8
        if observed_movement == coarse_movement:
            return 0.45
    return 0.0


def score_frame_step(primitive: Any, expected: dict[str, str]) -> dict[str, Any]:
    weighted = 0.0
    max_weight = 0.0
    matched: list[str] = []
    conflicts: list[str] = []
    unknown_fields: list[str] = []
    observed_relative_motion = str(getattr(primitive, "relative_motion", None) or "unknown")
    observed_movement = str(getattr(primitive, "movement", "unknown"))
    for field, weight in CONFIG["FIELD_WEIGHTS"].items():
        if weight <= 0 or field == "dominant_side":
            continue
        exp = str(expected.get(field, "unknown"))
        obs = str(getattr(primitive, field, "unknown"))
        if exp == "unknown":
            continue
        max_weight += float(weight)
        if obs == exp:
            contribution = float(weight)
            matched.append(field)
        elif field == "movement" and movement_matches(obs, observed_relative_motion, exp):
            contribution = 0.95 * float(weight)
            matched.append(field)
        elif field == "relative_motion":
            relative_score = relative_motion_match_score(obs, observed_movement, exp)
            if relative_score > 0:
                contribution = relative_score * float(weight)
                matched.append(field)
            elif observed_movement == "hold":
                contribution = -0.25 * float(weight)
                unknown_fields.append(field)
            elif is_weak_unknown(field, obs):
                contribution = -0.25 * float(weight)
                unknown_fields.append(field)
            else:
                contribution = -1.00 * float(weight)
                conflicts.append(field)
        elif field == "movement" and obs == "hold":
            contribution = -0.10 * float(weight)
            unknown_fields.append(field)
        elif field == "location":
            if is_weak_unknown(field, obs):
                contribution = -0.05 * float(weight)
                unknown_fields.append(field)
            elif compatible(field, obs, exp):
                contribution = 0.35 * float(weight)
                matched.append(field)
            else:
                contribution = 0.0
        elif is_weak_unknown(field, obs):
            contribution = -0.10 * float(weight)
            unknown_fields.append(field)
        elif compatible(field, obs, exp):
            contribution = 0.40 * float(weight)
            matched.append(field)
        else:
            contribution = -1.00 * float(weight)
            conflicts.append(field)
        weighted += contribution
    raw = weighted / max(max_weight, 0.0001)
    return {
        "score": max(-1.0, min(1.0, raw)),
        "matched_fields": matched,
        "conflict_fields": conflicts,
        "unknown_fields": unknown_fields,
    }

