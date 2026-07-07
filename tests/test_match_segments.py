from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_match_segments_two_segments() -> None:
    segments = [
        {
            "hand_count": 1,
            "dominant_side": "signer_right",
            "location": "signer_right_upper",
            "movement": "left_right",
            "bimanual_relation": "single_hand",
            "dominant_shape": "no_gesture",
            "nondominant_shape": "no_hand",
        },
        {
            "hand_count": 2,
            "dominant_side": "signer_right",
            "location": "signer_center_middle",
            "movement": "up_down",
            "bimanual_relation": "dual_hand",
            "dominant_shape": "no_gesture",
            "nondominant_shape": "no_gesture",
        },
    ]

    response = client.post(
        "/api/v1/match/segments",
        json={"segments": segments, "top_k": 3, "debug": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["results"]) == 2
    assert data["results"][0]["segment_index"] == 0
    assert data["results"][1]["segment_index"] == 1
    assert len(data["results"][0]["candidates"]) == 3

