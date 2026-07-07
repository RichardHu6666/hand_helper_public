#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = PROJECT_ROOT / "tests/fixtures/stream_repeat_same_word.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / "reports/http_stream_stress.md"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            frames.append(json.loads(line))
    if not frames:
        raise ValueError(f"fixture has no frames: {path}")
    return frames


def timestamp(index: int) -> str:
    seconds = 143000 + (index // 1000)
    millis = index % 1000
    return f"260702-{seconds:06d}-{millis:03d}"


def reset(client: httpx.Client, session_id: str) -> None:
    response = client.post(f"/api/v1/debug/reset/{session_id}")
    if response.status_code != 200:
        raise RuntimeError(f"reset failed session={session_id} http={response.status_code} body={response.text}")


def post_frame(client: httpx.Client, session_id: str, frame: dict[str, Any], index: int, debug: bool = False) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "timestamp": timestamp(index),
        "primitive": frame["primitive"],
        "debug": debug,
    }
    response = client.post("/api/v1/stream/frame", json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"POST frame failed http={response.status_code} body={response.text}")
    data = response.json()
    if not isinstance(data.get("sentence"), dict):
        raise RuntimeError("stream response missing sentence object")
    return data


def summarize(responses: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed = [
        item["result"]["word_base"]
        for item in responses
        if item.get("status") == "confirmed" and item.get("result")
    ]
    return {
        "frames": len(responses),
        "confirmed_count": len(confirmed),
        "confirmed_words": confirmed,
        "repeated_confirmed_suppressed": len(confirmed) == len(set(confirmed)),
        "final_status": responses[-1].get("status") if responses else None,
        "final_sentence_status": (responses[-1].get("sentence") or {}).get("status") if responses else None,
    }


def run_single_session(client: httpx.Client, frames: list[dict[str, Any]], count: int) -> dict[str, Any]:
    session_id = "stress-single"
    reset(client, session_id)
    responses = [
        post_frame(client, session_id, frames[index % len(frames)], index + 1, debug=False)
        for index in range(count)
    ]
    return summarize(responses)


def run_interleaved_sessions(client: httpx.Client, frames: list[dict[str, Any]], count: int) -> dict[str, Any]:
    sessions = ["stress-a", "stress-b"]
    for session_id in sessions:
        reset(client, session_id)
    responses_by_session: dict[str, list[dict[str, Any]]] = {session_id: [] for session_id in sessions}
    for index in range(count):
        session_id = sessions[index % len(sessions)]
        responses_by_session[session_id].append(
            post_frame(client, session_id, frames[index % len(frames)], index + 1, debug=False)
        )
    summary = {session_id: summarize(responses) for session_id, responses in responses_by_session.items()}
    return {
        "frames": sum(item["frames"] for item in summary.values()),
        "sessions": summary,
        "repeated_confirmed_suppressed": all(item["repeated_confirmed_suppressed"] for item in summary.values()),
    }


def run_reset_and_resend(client: httpx.Client, frames: list[dict[str, Any]]) -> dict[str, Any]:
    session_id = "stress-reset"
    first: list[dict[str, Any]] = []
    second: list[dict[str, Any]] = []
    reset(client, session_id)
    for index, frame in enumerate(frames, start=1):
        first.append(post_frame(client, session_id, frame, index, debug=True))
    reset(client, session_id)
    for index, frame in enumerate(frames, start=1):
        second.append(post_frame(client, session_id, frame, index + 1000, debug=True))
    first_summary = summarize(first)
    second_summary = summarize(second)
    return {
        "first": first_summary,
        "second": second_summary,
        "same_confirmed_words_after_reset": first_summary["confirmed_words"] == second_summary["confirmed_words"],
    }


def render_report(results: dict[str, Any], url: str, fixture: Path) -> str:
    single = results["single_session_100"]
    inter = results["interleaved_sessions"]
    reset_result = results["reset_and_resend"]
    lines = [
        "# HTTP Stream Stress Report",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"URL: `{url}`",
        f"Fixture: `{fixture}`",
        "",
        "## Summary",
        "",
        "| scenario | frames | confirmed_count | confirmed_words | repeated_suppressed | notes |",
        "|---|---:|---:|---|---|---|",
        f"| single_session_100 | {single['frames']} | {single['confirmed_count']} | {', '.join(single['confirmed_words'])} | {str(single['repeated_confirmed_suppressed']).lower()} | final={single['final_status']} sentence={single['final_sentence_status']} |",
        f"| interleaved_sessions | {inter['frames']} |  |  | {str(inter['repeated_confirmed_suppressed']).lower()} | sessions={len(inter['sessions'])} |",
        f"| reset_and_resend | {reset_result['first']['frames'] + reset_result['second']['frames']} | {reset_result['first']['confirmed_count']} / {reset_result['second']['confirmed_count']} | {', '.join(reset_result['second']['confirmed_words'])} | {str(reset_result['second']['repeated_confirmed_suppressed']).lower()} | same_after_reset={str(reset_result['same_confirmed_words_after_reset']).lower()} |",
        "",
        "## Raw JSON",
        "",
        "```json",
        json.dumps(results, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:6666")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--output-md", default=str(DEFAULT_REPORT))
    parser.add_argument("--sleep-ms", type=int, default=0)
    args = parser.parse_args()

    fixture = Path(args.fixture)
    frames = load_jsonl(fixture)
    results: dict[str, Any] = {}
    started = time.time()
    try:
        with httpx.Client(base_url=args.url.rstrip("/"), timeout=10, trust_env=False) as client:
            results["single_session_100"] = run_single_session(client, frames, args.frames)
            if args.sleep_ms:
                time.sleep(args.sleep_ms / 1000)
            results["interleaved_sessions"] = run_interleaved_sessions(client, frames, args.frames)
            results["reset_and_resend"] = run_reset_and_resend(client, frames)
            health = client.get("/health")
            if health.status_code != 200:
                raise RuntimeError(f"health failed http={health.status_code} body={health.text}")
            results["health"] = health.json()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    results["elapsed_sec"] = round(time.time() - started, 3)
    report = Path(args.output_md)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(results, args.url, fixture), encoding="utf-8")
    print(f"wrote {report}")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

