import json
from pathlib import Path

import pytest

from app.schemas import StreamFrameRequest
from app.stream_decoder import StreamDecoder
from app.stream_models import StreamFrame


FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURES = [
    "stream_left_right_single.jsonl",
    "stream_up_down_single.jsonl",
    "stream_toward_away_single.jsonl",
    "stream_dual_hand.jsonl",
    "stream_noisy_shape.jsonl",
    "stream_repeat_same_word.jsonl",
]


def load_fixture(name: str) -> list[dict]:
    frames = []
    for line in (FIXTURE_DIR / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            frames.append(json.loads(line))
    return frames


def run_fixture(name: str) -> list[dict]:
    decoder = StreamDecoder()
    responses = []
    for item in load_fixture(name):
        request = StreamFrameRequest(
            session_id=item["session_id"],
            timestamp=item["timestamp"],
            primitive=item["primitive"],
            debug=True,
        )
        responses.append(decoder.decode(StreamFrame.from_request(request), include_debug=True))
    return responses


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_runs_without_exception(name: str) -> None:
    responses = run_fixture(name)
    assert len(responses) >= 6
    assert all(response["ok"] is True for response in responses)
    assert all(response["status"] in {"collecting", "pending", "confirmed"} for response in responses)


def test_left_right_single_reaches_candidate_state() -> None:
    statuses = [response["status"] for response in run_fixture("stream_left_right_single.jsonl")]
    assert {"pending", "confirmed"} & set(statuses)


def test_repeat_same_word_does_not_confirm_same_word_multiple_times() -> None:
    confirmed_words = [
        response["result"]["word_base"]
        for response in run_fixture("stream_repeat_same_word.jsonl")
        if response["status"] == "confirmed" and response.get("result")
    ]
    assert len(confirmed_words) == len(set(confirmed_words))

