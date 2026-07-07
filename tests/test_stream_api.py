from fastapi.testclient import TestClient

from app.main import app


def primitive() -> dict:
    return {
        "hand_count": 1,
        "dominant_side": "signer_right",
        "location": "signer_center_upper",
        "movement": "left_right",
        "bimanual_relation": "single_hand",
        "dominant_shape": "five",
        "nondominant_shape": "no_hand",
    }


def test_health_stream_vocab() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["vocab"]["rows"] == 109
    assert data["vocab"]["loaded"] is True


def test_stream_frame_and_reset() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/stream/frame", json={"session_id": "api", "timestamp": "260701-143012-001", "primitive": primitive(), "debug": True})
        assert response.status_code == 200
        assert response.json()["buffer_frames"] == 1
        reset = client.post("/api/v1/debug/reset/api")
        assert reset.json() == {"ok": True, "session_id": "api", "reset": True}


def test_invalid_timestamp_returns_422() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/stream/frame", json={"session_id": "bad", "timestamp": "bad", "primitive": primitive()})
    assert response.status_code == 422


def test_invalid_enum_returns_422() -> None:
    data = primitive()
    data["movement"] = "diagonal"
    with TestClient(app) as client:
        response = client.post("/api/v1/stream/frame", json={"session_id": "bad", "timestamp": "260701-143012-001", "primitive": data})
    assert response.status_code == 422


def test_stream_frames_batch_endpoint() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/stream/frames",
            json={
                "session_id": "api-batch",
                "debug": True,
                "frames": [
                    {
                        "client_seq": 2,
                        "timestamp": "260701-143012-002",
                        "primitive": primitive(),
                    },
                    {
                        "client_seq": 1,
                        "timestamp": "260701-143012-001",
                        "primitive": primitive(),
                    },
                ],
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["buffer_frames"] == 2
    assert isinstance(data["debug"], dict)
    assert len(data["debug"]["frame_results"]) == 2


def test_websocket_ping_echo() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws/ping") as websocket:
            websocket.send_text("ping")
            assert websocket.receive_text() == "ping"

