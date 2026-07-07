import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_batch(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def clone_with_timestamps(payload: dict, session_id: str, base_prefix: str) -> dict:
    cloned = json.loads(json.dumps(payload))
    cloned["session_id"] = session_id
    for index, frame in enumerate(cloned["frames"], start=1):
        frame["timestamp"] = f"{base_prefix}-{index:03d}"
    return cloned


def hold_payload() -> dict:
    return {
        "hand_count": 1,
        "dominant_side": "signer_right",
        "location": "signer_right_upper",
        "movement": "hold",
        "relative_motion": "hold",
        "bimanual_relation": "single_hand",
        "dominant_shape": "no_gesture",
        "nondominant_shape": "no_hand",
    }


def test_batch_clean_left_right_can_confirm() -> None:
    payload = load_batch("stream_batch_left_right_upper.json")
    with TestClient(app) as client:
        client.post(f"/api/v1/debug/reset/{payload['session_id']}")
        response = client.post("/api/v1/stream/frames", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"
    assert data["result"] is not None
    assert data["result"]["word_base"] == "鍘曟墍"
    assert data["sentence"]["text"] == "鍘曟墍"


def test_batch_unknown_location_is_allowed_and_not_blocking() -> None:
    payload = load_batch("stream_batch_left_right_unknown_location.json")
    with TestClient(app) as client:
        client.post(f"/api/v1/debug/reset/{payload['session_id']}")
        response = client.post("/api/v1/stream/frames", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"
    assert data["result"] is not None
    assert data["result"]["word_base"] == "鍘曟墍"


def test_batch_debug_returns_frame_results_and_preserves_mid_batch_confirmed_result() -> None:
    payload = load_batch("stream_batch_left_right_upper.json")
    payload["debug"] = True
    payload["frames"].append(
        {
            "client_seq": 99,
            "timestamp": "260702-000013-099",
            "primitive": hold_payload(),
        }
    )
    with TestClient(app) as client:
        client.post(f"/api/v1/debug/reset/{payload['session_id']}")
        response = client.post("/api/v1/stream/frames", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"
    assert data["result"] is not None
    assert data["result"]["word_base"] == "鍘曟墍"
    assert data["sentence"]["text"] == "鍘曟墍"
    assert isinstance(data["debug"], dict)
    assert "frame_results" in data["debug"]
    assert any(item["status"] == "confirmed" and item.get("word_base") == "鍘曟墍" for item in data["debug"]["frame_results"])
    assert any("reason" in item for item in data["debug"]["frame_results"])


def test_batch_noisy_shape_unknown_can_still_confirm() -> None:
    payload = load_batch("stream_batch_noisy_shape_with_cached_five.json")
    with TestClient(app) as client:
        client.post(f"/api/v1/debug/reset/{payload['session_id']}")
        response = client.post("/api/v1/stream/frames", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"
    assert data["result"] is not None
    assert data["result"]["word_base"] == "鍘曟墍"


def test_batch_board_like_unknown_location_and_hold_noise_confirms() -> None:
    payload = load_batch("stream_batch_board_like_left_right_unknown.json")
    payload["debug"] = True
    with TestClient(app) as client:
        client.post(f"/api/v1/debug/reset/{payload['session_id']}")
        response = client.post("/api/v1/stream/frames", json=payload)
        session_debug = client.get(f"/api/v1/debug/session/{payload['session_id']}").json()
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"
    assert data["result"] is not None
    assert data["sentence"]["text"]
    assert any(item["status"] == "confirmed" for item in data["debug"]["frame_results"])
    assert session_debug["top_candidates"]
    assert any(frame.get("client_seq") == 12 for frame in session_debug["buffer"])
    assert session_debug["buffer_summary"]["input_bucket"] in {"ideal_input", "ideal_input_with_hold_noise"}
    top = session_debug["top_candidates"][0]
    assert top["movement_match"] == "matched"
    assert top["shape_match"] == "matched"
    assert top["location_match"] == "weak_unknown"
    assert top["relative_motion_match"] in {"matched", "direction_family", "not_expected"}
    assert "matched_span" in top
    assert "reject_reasons" in top
    assert "unknown_count" in top
    assert "conflict_count" in top


def test_batch_same_word_continuous_does_not_repeat_sentence_append() -> None:
    payload = {
        "session_id": "fixture-batch-continuous",
        "debug": True,
        "frames": [],
    }
    def hold_frame(seq: int, timestamp: str) -> dict:
        return {
            "client_seq": seq,
            "timestamp": timestamp,
            "primitive": {
                "hand_count": 1,
                "dominant_side": "signer_right",
                "location": "signer_right_lower",
                "movement": "hold",
                "relative_motion": "hold",
                "bimanual_relation": "single_hand",
                "dominant_shape": "five",
                "nondominant_shape": "no_hand",
            },
        }
    def active_frame(seq: int, timestamp: str, relative_motion: str) -> dict:
        return {
            "client_seq": seq,
            "timestamp": timestamp,
            "primitive": {
                "hand_count": 1,
                "dominant_side": "signer_right",
                "location": "unknown",
                "movement": "left_right",
                "relative_motion": relative_motion,
                "bimanual_relation": "single_hand",
                "dominant_shape": "five",
                "nondominant_shape": "no_hand",
            },
        }
    timestamps = [f"260704-130000-{i:03d}" for i in range(1, 25)]
    payload["frames"].extend([hold_frame(1, timestamps[0]), hold_frame(2, timestamps[1])])
    for index in range(3, 23):
        rel = "left_to_right" if index % 2 else "right_to_left"
        payload["frames"].append(active_frame(index, timestamps[index - 1], rel))
    payload["frames"].extend([hold_frame(23, timestamps[22]), hold_frame(24, timestamps[23])])
    with TestClient(app) as client:
        client.post("/api/v1/debug/reset/fixture-batch-continuous")
        response = client.post("/api/v1/stream/frames", json=payload)
        session_debug = client.get("/api/v1/debug/session/fixture-batch-continuous").json()
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"
    assert data["result"] is not None
    assert data["sentence"]["text"] == data["result"]["word_base"]
    confirmed = [item for item in data["debug"]["frame_results"] if item["status"] == "confirmed"]
    assert len(confirmed) == 1
    assert session_debug["pending_analysis"]["primary_reason"] == "suppress"
    assert session_debug["top_candidates"][0]["suppress_reason"] in {"same_word_continuous", "overlap_iou"}


def test_batch_same_word_can_reconfirm_after_gap() -> None:
    payload = load_batch("stream_batch_left_right_unknown_location.json")
    first_payload = clone_with_timestamps(payload, "fixture-batch-repeat-gap", "260702-000014")
    second_payload = clone_with_timestamps(payload, "fixture-batch-repeat-gap", "260702-000120")
    with TestClient(app) as client:
        client.post("/api/v1/debug/reset/fixture-batch-repeat-gap")
        first = client.post("/api/v1/stream/frames", json=first_payload).json()
        second = client.post("/api/v1/stream/frames", json=second_payload).json()
    assert first["status"] == "confirmed"
    assert second["status"] == "confirmed"
    assert first["result"] is not None
    assert second["result"] is not None
    assert second["result"]["word_base"] == first["result"]["word_base"]


def test_reset_then_collecting_does_not_leak_last_sentence() -> None:
    payload = load_batch("stream_batch_left_right_upper.json")
    with TestClient(app) as client:
        client.post(f"/api/v1/debug/reset/{payload['session_id']}")
        confirmed = client.post("/api/v1/stream/frames", json=payload).json()
        assert confirmed["result"]["word_base"] == "鍘曟墍"
        client.post(f"/api/v1/debug/reset/{payload['session_id']}")
        collecting = client.post(
            "/api/v1/stream/frame",
            json={
                "session_id": payload["session_id"],
                "timestamp": "260702-000016-001",
                "primitive": hold_payload(),
                "debug": False,
            },
        ).json()
    assert collecting["status"] == "collecting"
    assert collecting["sentence"] is None
    assert collecting["last_confirmed"] is None

