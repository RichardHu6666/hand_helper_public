from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def base_primitive() -> dict:
    return {
        "hand_count": 1,
        "dominant_side": "signer_right",
        "location": "signer_right_upper",
        "movement": "left_right",
        "bimanual_relation": "single_hand",
        "dominant_shape": "no_gesture",
        "nondominant_shape": "no_hand",
        "duration_ms": 600,
        "repeat_count": 1,
    }


def test_match_primitive_left_right_single_hand() -> None:
    response = client.post(
        "/api/v1/match/primitive",
        json={"primitive": base_primitive(), "top_k": 5, "debug": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["query_text"]
    assert len(data["candidates"]) > 0
    assert data["debug"]["method"] == "rule_text_score_v1"


def test_top_k_one_returns_one_candidate() -> None:
    response = client.post(
        "/api/v1/match/primitive",
        json={"primitive": base_primitive(), "top_k": 1},
    )

    assert response.status_code == 200
    assert len(response.json()["candidates"]) == 1


def test_shape_no_gesture_still_returns_candidates() -> None:
    primitive = base_primitive()
    primitive["dominant_shape"] = "no_gesture"
    primitive["nondominant_shape"] = "no_hand"

    response = client.post(
        "/api/v1/match/primitive",
        json={"primitive": primitive, "top_k": 5},
    )

    assert response.status_code == 200
    assert response.json()["candidates"]


def test_invalid_movement_returns_422() -> None:
    primitive = base_primitive()
    primitive["movement"] = "diagonal"

    response = client.post(
        "/api/v1/match/primitive",
        json={"primitive": primitive, "top_k": 5},
    )

    assert response.status_code == 422


def test_top_k_zero_returns_422() -> None:
    response = client.post(
        "/api/v1/match/primitive",
        json={"primitive": base_primitive(), "top_k": 0},
    )

    assert response.status_code == 422

