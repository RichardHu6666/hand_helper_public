from __future__ import annotations

from typing import Any

from app.config import CONFIG


MOVEMENTS = {"left_right", "up_down", "toward_away", "open_close", "repeat"}
DUAL_RELATIONS = {"dual_hand", "same_shape", "different_shape"}


def coarse_side(location: str) -> str:
    if location.startswith("signer_left"):
        return "left"
    if location.startswith("signer_right"):
        return "right"
    if location.startswith("signer_center"):
        return "center"
    return "unknown"


def count_step_conflicts(summary: dict[str, Any], expected: dict[str, str]) -> tuple[int, list[str]]:
    modes = summary["field_modes"]
    conflicts: list[str] = []
    if expected.get("hand_count") in {"1", "2"} and str(modes.get("hand_count")) in {"1", "2"}:
        if str(modes["hand_count"]) != expected["hand_count"]:
            conflicts.append("hand_count")
    observed_movement = str(modes.get("movement", "unknown"))
    expected_movement = expected.get("movement", "unknown")
    if observed_movement in MOVEMENTS and expected_movement in MOVEMENTS and observed_movement != expected_movement:
        conflicts.append("movement")
    observed_relation = str(modes.get("bimanual_relation", "unknown"))
    expected_relation = expected.get("bimanual_relation", "unknown")
    if observed_relation == "single_hand" and expected_relation in DUAL_RELATIONS:
        conflicts.append("bimanual_relation")
    elif observed_relation in DUAL_RELATIONS and expected_relation == "single_hand":
        conflicts.append("bimanual_relation")
    return len(conflicts), conflicts


def passes_wide_filter(summary: dict[str, Any], steps: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    if summary.get("unknown_ratio", 0.0) > float(CONFIG["MAX_UNKNOWN_RATIO"]):
        return False, ["unknown_ratio"]
    best_conflicts: list[str] | None = None
    for step in steps:
        _, conflicts = count_step_conflicts(summary, step["expected"])
        if best_conflicts is None or len(conflicts) < len(best_conflicts):
            best_conflicts = conflicts
        if len(conflicts) <= int(CONFIG["WIDE_FILTER_MAX_CONFLICTS"]):
            return True, conflicts
    return False, best_conflicts or []

