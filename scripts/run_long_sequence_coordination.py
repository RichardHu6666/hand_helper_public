#!/usr/bin/env python
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


BASE_URL = "http://127.0.0.1:6000"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "reports" / "long_sequence_coordination_20260704.json"
START_TIME = datetime(2026, 7, 4, 12, 0, 0)
FRAME_STEP_MS = 250


@dataclass
class FrameSpec:
    movement: str
    relative_motion: str
    dominant_shape: str = "five"
    location: str = "unknown"
    hand_count: int = 1
    bimanual_relation: str = "single_hand"
    nondominant_shape: str = "no_hand"
    dominant_side: str = "signer_right"


HOLD_FIVE = FrameSpec("hold", "hold", dominant_shape="five", location="signer_right_lower")
HOLD_NO_HAND = FrameSpec(
    "hold",
    "hold",
    dominant_shape="no_gesture",
    location="signer_right_lower",
    hand_count=0,
    nondominant_shape="no_hand",
)


def format_ts(base: datetime, index: int) -> str:
    moment = base + timedelta(milliseconds=FRAME_STEP_MS * (index - 1))
    return f"{moment.strftime('%y%m%d-%H%M%S')}-{index:03d}"


def to_frame(index: int, base: datetime, spec: FrameSpec) -> dict[str, Any]:
    return {
        "client_seq": index,
        "timestamp": format_ts(base, index),
        "primitive": {
            "hand_count": spec.hand_count,
            "dominant_side": spec.dominant_side,
            "location": spec.location,
            "movement": spec.movement,
            "relative_motion": spec.relative_motion,
            "bimanual_relation": spec.bimanual_relation,
            "dominant_shape": spec.dominant_shape,
            "nondominant_shape": spec.nondominant_shape,
        },
    }


def alternating_motion(name: str, count: int, directions: tuple[str, str]) -> list[FrameSpec]:
    return [
        FrameSpec(name, directions[(i - 1) % len(directions)])
        for i in range(1, count + 1)
    ]


def repeat(frame: FrameSpec, count: int) -> list[FrameSpec]:
    return [deepcopy(frame) for _ in range(count)]


def scenario_single_word() -> list[FrameSpec]:
    return repeat(HOLD_FIVE, 3) + alternating_motion("left_right", 7, ("left_to_right", "right_to_left")) + repeat(HOLD_FIVE, 2)


def scenario_same_word_continuous() -> list[FrameSpec]:
    return repeat(HOLD_FIVE, 2) + alternating_motion("left_right", 20, ("left_to_right", "right_to_left")) + repeat(HOLD_FIVE, 2)


def scenario_same_word_gap_repeat() -> list[FrameSpec]:
    return (
        alternating_motion("left_right", 7, ("left_to_right", "right_to_left"))
        + repeat(HOLD_FIVE, 2)
        + repeat(HOLD_NO_HAND, 8)
        + alternating_motion("left_right", 7, ("left_to_right", "right_to_left"))
    )


def scenario_two_motion_segments() -> list[FrameSpec]:
    return (
        alternating_motion("left_right", 7, ("left_to_right", "right_to_left"))
        + repeat(HOLD_NO_HAND, 6)
        + alternating_motion("up_down", 7, ("up_to_down", "down_to_up"))
    )


def scenario_shape_jitter() -> list[FrameSpec]:
    return (
        repeat(HOLD_FIVE, 2)
        + alternating_motion("up_down", 3, ("up_to_down", "down_to_up"))
        + [FrameSpec("up_down", "up_to_down", dominant_shape="two")]
        + alternating_motion("up_down", 3, ("down_to_up", "up_to_down"))
        + [FrameSpec("up_down", "down_to_up", dominant_shape="unknown")]
        + alternating_motion("up_down", 3, ("up_to_down", "down_to_up"))
        + repeat(HOLD_FIVE, 2)
    )


def make_payload(session_id: str, specs: list[FrameSpec], start_offset_minutes: int) -> dict[str, Any]:
    base = START_TIME + timedelta(minutes=start_offset_minutes)
    frames = [to_frame(index, base, spec) for index, spec in enumerate(specs, start=1)]
    return {"session_id": session_id, "debug": True, "frames": frames}


def top3(debug_session: dict[str, Any]) -> list[dict[str, Any]]:
    return list(debug_session.get("top_candidates") or [])[:3]


def frame_confirms(batch_response: dict[str, Any]) -> list[dict[str, Any]]:
    debug = batch_response.get("debug") or {}
    return [item for item in debug.get("frame_results", []) if item.get("status") == "confirmed"]


def summarize(session_id: str, batch_response: dict[str, Any], debug_session: dict[str, Any]) -> dict[str, Any]:
    confirmed_frames = frame_confirms(batch_response)
    sentence_text = ((batch_response.get("sentence") or {}).get("text") or "").strip()
    words = [word for word in sentence_text.split(" ") if word]
    repeated_sentence = len(words) != len(set(words)) if words else False
    return {
        "session_id": session_id,
        "http_ok": True,
        "response": {
            "status": batch_response.get("status"),
            "result": batch_response.get("result"),
            "sentence": batch_response.get("sentence"),
        },
        "confirmed_frames": confirmed_frames,
        "first_confirmed_frame": confirmed_frames[0] if confirmed_frames else None,
        "debug_session": {
            "buffer_summary": debug_session.get("buffer_summary"),
            "pending_analysis": debug_session.get("pending_analysis"),
            "top_candidates": top3(debug_session),
        },
        "long_sequence_conclusion": {
            "repeated_sentence_append": repeated_sentence,
            "confirmed_count_in_batch": len(confirmed_frames),
            "has_confirmed": bool(confirmed_frames),
        },
    }


def run_case(client: httpx.Client, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    reset = client.post(f"/api/v1/debug/reset/{session_id}")
    reset.raise_for_status()
    batch = client.post("/api/v1/stream/frames", json=payload)
    batch.raise_for_status()
    debug_session = client.get(f"/api/v1/debug/session/{session_id}")
    debug_session.raise_for_status()
    return summarize(session_id, batch.json(), debug_session.json())


def main() -> int:
    cases = [
        ("codex-seq-single-word", scenario_single_word(), 0),
        ("codex-seq-same-word-continuous", scenario_same_word_continuous(), 10),
        ("codex-seq-same-word-gap-repeat", scenario_same_word_gap_repeat(), 20),
        ("codex-seq-two-motion-segments", scenario_two_motion_segments(), 30),
        ("codex-seq-shape-jitter", scenario_shape_jitter(), 40),
    ]
    results = []
    with httpx.Client(base_url=BASE_URL, timeout=20, trust_env=False) as client:
        for session_id, specs, offset in cases:
            payload = make_payload(session_id, specs, offset)
            results.append(run_case(client, session_id, payload))
    REPORT_PATH.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

