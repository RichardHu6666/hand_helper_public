#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx


def load_payload(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "frames" not in payload or not isinstance(payload["frames"], list):
        raise ValueError("batch fixture must contain a frames array")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:6666")
    parser.add_argument("--json", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    payload = load_payload(args.json)
    if args.session_id:
        payload["session_id"] = args.session_id
    if args.debug:
        payload["debug"] = True

    with httpx.Client(base_url=args.url.rstrip("/"), timeout=10, trust_env=False) as client:
        reset = client.post(f"/api/v1/debug/reset/{payload['session_id']}")
        if reset.status_code != 200:
            print(reset.text, file=sys.stderr)
            return 1
        response = client.post("/api/v1/stream/frames", json=payload)
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())

