#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app


BASE_TS = "260701-143012"
DEFAULT_SESSION_ID = "debug-stream"


def primitive(**overrides: Any) -> dict[str, Any]:
    value = {
        "hand_count": 1,
        "dominant_side": "signer_right",
        "location": "signer_center_upper",
        "movement": "left_right",
        "bimanual_relation": "single_hand",
        "dominant_shape": "five",
        "nondominant_shape": "no_hand",
    }
    value.update(overrides)
    return value


def preset_frames(name: str) -> list[dict[str, Any]]:
    if name == "left_right_single":
        return [{"primitive": primitive()} for _ in range(6)]
    if name == "dual_repeat":
        return [
            {
                "primitive": primitive(
                    hand_count=2,
                    location="signer_center_lower",
                    movement="left_right",
                    bimanual_relation="dual_hand",
                    dominant_shape="five",
                    nondominant_shape="unknown",
                )
            }
            for _ in range(6)
        ]
    if name == "noisy_shape":
        shapes = ["no_gesture", "five", "no_gesture", "five", "unknown", "five"]
        return [{"primitive": primitive(dominant_shape=shape)} for shape in shapes]
    raise SystemExit(f"unknown preset: {name}")


def load_jsonl(path: str) -> list[dict[str, Any]]:
    frames = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if "primitive" not in item:
            item = {"primitive": item}
        frames.append(item)
    return frames


def normalized_payload(item: dict[str, Any], index: int, default_session_id: str, debug: bool) -> dict[str, Any]:
    return {
        "session_id": item.get("session_id") or default_session_id,
        "timestamp": item.get("timestamp") or f"{BASE_TS}-{index:03d}",
        "primitive": item["primitive"],
        "debug": debug,
    }


def print_response(index: int, data: dict[str, Any]) -> None:
    prefix = f"[frame {index:03d}] status={data['status']} buffer={data['buffer_frames']}"
    if data["status"] == "confirmed" and data.get("result"):
        result = data["result"]
        print(
            f"{prefix} word={result['word_base']} score={result['confidence']:.2f} "
            f"span={result['start_ts']}..{result['end_ts']}"
        )
    elif data["status"] == "pending" and data.get("partial_candidates"):
        top = data["partial_candidates"][0]
        print(f"{prefix} top={top['word_base']} score={top['score']:.2f}")
    else:
        print(prefix)


def build_summary(responses: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed_words = [
        data["result"]["word_base"]
        for data in responses
        if data.get("status") == "confirmed" and data.get("result")
    ]
    return {
        "frames": len(responses),
        "confirmed_count": len(confirmed_words),
        "confirmed_words": confirmed_words,
        "repeated_confirmed_suppressed": len(confirmed_words) == len(set(confirmed_words)),
    }


def print_summary(summary: dict[str, Any]) -> None:
    print("summary:")
    print(f"frames={summary['frames']}")
    print(f"confirmed_count={summary['confirmed_count']}")
    print(f"confirmed_words={json.dumps(summary['confirmed_words'], ensure_ascii=False)}")
    print(f"repeated_confirmed_suppressed={str(summary['repeated_confirmed_suppressed']).lower()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", choices=["left_right_single", "dual_repeat", "noisy_shape"], default="left_right_single")
    parser.add_argument("--jsonl")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    frames = load_jsonl(args.jsonl) if args.jsonl else preset_frames(args.preset)
    session_id = (frames[0].get("session_id") if frames else None) or DEFAULT_SESSION_ID
    responses: list[dict[str, Any]] = []

    with TestClient(app) as client:
        client.post(f"/api/v1/debug/reset/{session_id}")
        for index, item in enumerate(frames, start=1):
            payload = normalized_payload(item, index, session_id, args.debug)
            response = client.post("/api/v1/stream/frame", json=payload)
            response.raise_for_status()
            data = response.json()
            responses.append(data)
            print_response(index, data)

    print_summary(build_summary(responses))


if __name__ == "__main__":
    main()

