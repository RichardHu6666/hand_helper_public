from __future__ import annotations

from app.config import CONFIG
from app.rolling_buffer import SessionState


INACTIVE_REPEAT_GAP_MS = 1200


def span_iou(a: dict, b: dict) -> float:
    start = max(a["start_ms"], b["start_ms"])
    end = min(a["end_ms"], b["end_ms"])
    overlap = max(0, end - start)
    union = max(a["end_ms"], b["end_ms"]) - min(a["start_ms"], b["start_ms"])
    return overlap / max(union, 1)


def _is_inactive_frame(frame) -> bool:
    primitive = frame.primitive
    movement = str(getattr(primitive, "movement", "unknown") or "unknown")
    hand_count = int(getattr(primitive, "hand_count", 0) or 0)
    dominant_shape = str(getattr(primitive, "dominant_shape", "unknown") or "unknown")
    return movement == "hold" or hand_count == 0 or dominant_shape in {"no_gesture", "no_hand", "unknown"}


def _update_repeat_gap_state(state: SessionState) -> None:
    if not state.frames:
        return
    latest = state.frames[-1]
    latest_ms = latest.timestamp_ms
    previous_ms = state.last_frame_timestamp_ms
    if previous_ms is not None and latest_ms <= previous_ms:
        return

    if state.last_confirmed_id is not None and previous_ms is not None and latest_ms - previous_ms >= INACTIVE_REPEAT_GAP_MS:
        state.repeat_gap_ready = True

    if _is_inactive_frame(latest):
        if state.inactive_streak_start_ms is None:
            state.inactive_streak_start_ms = latest_ms
        if latest_ms - state.inactive_streak_start_ms >= INACTIVE_REPEAT_GAP_MS:
            state.repeat_gap_ready = True
    else:
        state.inactive_streak_start_ms = None

    state.last_frame_timestamp_ms = latest_ms


def decide_output(state: SessionState, candidates: list[dict], now_ms: int) -> dict:
    state.suppressed_candidates = []
    _update_repeat_gap_state(state)
    if not candidates:
        state.stable_candidate_id = None
        state.stable_count = 0
        return {"status": "collecting", "selected": None, "reason": ["no_candidate"], "suppressed": []}
    top = candidates[0]
    if state.last_confirmed_id is not None and top["id"] != state.last_confirmed_id:
        state.candidate_changed_since_confirm = True
    if state.stable_candidate_id == top["id"]:
        state.stable_count += 1
    else:
        state.stable_candidate_id = top["id"]
        state.stable_count = 1
    margin = top["score"] - (candidates[1]["score"] if len(candidates) > 1 else 0.0)
    suppressed = []
    latest_confirm = state.confirmed_history[-1] if state.confirmed_history else None
    for item in candidates:
        span = {"start_ms": item["start_ms"], "end_ms": item["end_ms"]}
        latest_same_confirm = next(
            (old for old in reversed(state.confirmed_history) if item["id"] == old["id"]),
            None,
        )
        for old in state.confirmed_history:
            if item["id"] == old["id"] and span_iou(span, old) > float(CONFIG["OVERLAP_IOU_THRESHOLD"]):
                suppressed.append({**item, "reason": "overlap_iou"})
                break
            if item["id"] == old["id"] and now_ms - old["confirmed_ms"] < int(CONFIG["SAME_WORD_SUPPRESS_MS"]):
                suppressed.append({**item, "reason": "same_word_suppress_ms"})
                break
        else:
            if (
                latest_confirm is not None
                and item["id"] == latest_confirm["id"]
                and latest_same_confirm is not None
                and not state.repeat_gap_ready
            ):
                suppressed.append({**item, "reason": "same_word_continuous"})
    selected_suppressed_item = next((item for item in suppressed if item["id"] == top["id"]), None)
    selected_suppressed = selected_suppressed_item is not None
    reasons = []
    if top["score"] >= float(CONFIG["CONFIRM_SCORE_THRESHOLD"]):
        reasons.append("score_above_threshold")
    if margin >= float(CONFIG["TOP_MARGIN_THRESHOLD"]):
        reasons.append("top_margin")
    if state.stable_count >= int(CONFIG["STABLE_N"]):
        reasons.append(f"stable_for_{CONFIG['STABLE_N']}_frames")
    if now_ms < state.cooldown_until_ms:
        reasons.append("cooldown")
    if selected_suppressed:
        reasons.append("suppressed")
    can_confirm = (
        top["score"] >= float(CONFIG["CONFIRM_SCORE_THRESHOLD"])
        and margin >= float(CONFIG["TOP_MARGIN_THRESHOLD"])
        and state.stable_count >= int(CONFIG["STABLE_N"])
        and now_ms >= state.cooldown_until_ms
        and not selected_suppressed
        and top["complete"]
    )
    if can_confirm:
        state.cooldown_until_ms = now_ms + int(CONFIG["COOLDOWN_MS"])
        state.confirmed_history.append(
            {
                "id": top["id"],
                "start_ms": top["start_ms"],
                "end_ms": top["end_ms"],
                "confirmed_ms": now_ms,
            }
        )
        state.last_confirmed_id = top["id"]
        state.candidate_changed_since_confirm = False
        state.repeat_gap_ready = False
        state.inactive_streak_start_ms = None
        decision = {"status": "confirmed", "selected": top, "reason": reasons, "suppressed": suppressed}
    elif top["score"] >= float(CONFIG["PENDING_SCORE_THRESHOLD"]):
        pending_reasons = []
        if top["score"] < float(CONFIG["CONFIRM_SCORE_THRESHOLD"]):
            pending_reasons.append("score_below_confirm_threshold")
        if margin < float(CONFIG["TOP_MARGIN_THRESHOLD"]):
            pending_reasons.append("top_margin_below_threshold")
        if state.stable_count < int(CONFIG["STABLE_N"]):
            pending_reasons.append("not_stable_enough")
        if not top["complete"]:
            pending_reasons.append("partial_step_alignment")
        if now_ms < state.cooldown_until_ms:
            pending_reasons.append("cooldown")
        if selected_suppressed:
            pending_reasons.append(f"suppressed_by_{selected_suppressed_item.get('reason', 'unknown')}")
        top["reason_pending"] = pending_reasons or ["awaiting_confirmation"]
        decision = {"status": "pending", "selected": top, "reason": pending_reasons, "suppressed": suppressed}
    else:
        decision = {"status": "collecting", "selected": None, "reason": ["score_below_pending_threshold"], "suppressed": suppressed}
    decision["margin"] = round(margin, 4)
    decision["stable_count"] = state.stable_count
    decision["cooldown_until_ms"] = state.cooldown_until_ms
    state.suppressed_candidates = suppressed
    return decision

