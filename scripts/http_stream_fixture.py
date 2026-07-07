#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx


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


def print_frame(index: int, status_code: int, data: dict[str, Any]) -> None:
    prefix = f"[frame {index:03d}] http={status_code} status={data.get('status')}"
    if data.get("status") == "confirmed" and data.get("result"):
        result = data["result"]
        print(f"{prefix} word={result['word_base']} score={result['confidence']:.2f}")
    elif data.get("status") == "pending" and data.get("partial_candidates"):
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:6666")
    parser.add_argument("--jsonl", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--sleep-ms", type=int, default=0)
    args = parser.parse_args()

    frames = load_jsonl(args.jsonl)
    if not frames:
        print("jsonl contains no frames", file=sys.stderr)
        return 2
    session_id = args.session_id or frames[0].get("session_id") or "http-stream-fixture"
    responses: list[dict[str, Any]] = []

    with httpx.Client(base_url=args.url.rstrip("/"), timeout=10, trust_env=False) as client:
        reset = client.post(f"/api/v1/debug/reset/{session_id}")
        if reset.status_code != 200:
            print(reset.text, file=sys.stderr)
            return 1
        for index, item in enumerate(frames, start=1):
            payload = {
                "session_id": args.session_id or item.get("session_id") or session_id,
                "timestamp": item.get("timestamp") or f"260701-143012-{index:03d}",
                "primitive": item["primitive"],
                "debug": args.debug,
            }
            response = client.post("/api/v1/stream/frame", json=payload)
            if response.status_code != 200:
                print(response.text, file=sys.stderr)
                return 1
            data = response.json()
            responses.append(data)
            print_frame(index, response.status_code, data)
            if args.sleep_ms > 0:
                time.sleep(args.sleep_ms / 1000)

    print_summary(build_summary(responses))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

