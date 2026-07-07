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


def assert_sentence_contract(data: dict) -> None:
    assert "sentence" in data
    sentence = data["sentence"]
    if sentence is None:
        return
    assert isinstance(sentence, dict)
    assert isinstance(sentence.get("text"), str)
    assert sentence.get("status") in {"empty", "draft", "confirmed", "fallback"}
    assert isinstance(sentence.get("confirmed_words"), list)


def assert_last_confirmed_contract(data: dict) -> None:
    assert "last_confirmed" in data
    last_confirmed = data["last_confirmed"]
    if last_confirmed is None:
        return
    assert isinstance(last_confirmed.get("word_base"), str)
    assert isinstance(last_confirmed.get("sentence"), str)


def test_stream_frame_non_debug_contains_stable_sentence_contract() -> None:
    with TestClient(app) as client:
        client.post("/api/v1/debug/reset/contract-non-debug")
        response = client.post(
            "/api/v1/stream/frame",
            json={
                "session_id": "contract-non-debug",
                "timestamp": "260701-143012-001",
                "primitive": primitive(),
                "debug": False,
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["status"] in {"collecting", "pending", "confirmed"}
    assert "result" in data
    assert "partial_candidates" in data
    assert_sentence_contract(data)
    assert_last_confirmed_contract(data)


def test_stream_frame_debug_contains_rerank_and_sentence_debug() -> None:
    with TestClient(app) as client:
        client.post("/api/v1/debug/reset/contract-debug")
        response = client.post(
            "/api/v1/stream/frame",
            json={
                "session_id": "contract-debug",
                "timestamp": "260701-143012-001",
                "primitive": primitive(),
                "debug": True,
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert_sentence_contract(data)
    assert_last_confirmed_contract(data)
    assert isinstance(data.get("debug"), dict)
    assert "rerank" in data["debug"]
    assert "sentence" in data["debug"]
    assert "primitive_top_candidates" in data["debug"]
    assert "reranked_top_candidates" in data["debug"]


def test_stream_frame_collecting_does_not_leak_previous_confirmed_sentence() -> None:
    primitive = {
        "hand_count": 1,
        "dominant_side": "signer_right",
        "location": "signer_center_upper",
        "movement": "left_right",
        "bimanual_relation": "single_hand",
        "dominant_shape": "five",
        "nondominant_shape": "no_hand",
    }
    with TestClient(app) as client:
        client.post("/api/v1/debug/reset/contract-history")
        for i in range(1, 7):
            response = client.post(
                "/api/v1/stream/frame",
                json={
                    "session_id": "contract-history",
                    "timestamp": f"260701-143012-{i:03d}",
                    "primitive": primitive,
                    "debug": False,
                },
            )
        confirmed = response.json()
        assert confirmed["status"] == "confirmed"
        assert confirmed["result"]["word_base"] == "鍘曟墍"
        assert confirmed["sentence"]["text"] == "鍘曟墍"
        client.post("/api/v1/debug/reset/contract-history")
        collecting = client.post(
            "/api/v1/stream/frame",
            json={
                "session_id": "contract-history",
                "timestamp": "260701-143112-001",
                "primitive": {
                    "hand_count": 1,
                    "dominant_side": "signer_right",
                    "location": "signer_right_upper",
                    "movement": "hold",
                    "bimanual_relation": "single_hand",
                    "dominant_shape": "no_gesture",
                    "nondominant_shape": "no_hand",
                },
                "debug": False,
            },
        ).json()
    assert collecting["status"] == "collecting"
    assert collecting["result"] is None
    assert collecting["sentence"] is None
    assert collecting["last_confirmed"] is None



def hold_primitive() -> dict:
    return {
        "hand_count": 1,
        "dominant_side": "signer_right",
        "location": "signer_right_upper",
        "movement": "hold",
        "bimanual_relation": "single_hand",
        "dominant_shape": "no_gesture",
        "nondominant_shape": "no_hand",
    }


def test_stream_frame_collecting_with_static_hold_returns_null_result_and_sentence() -> None:
    with TestClient(app) as client:
        client.post("/api/v1/debug/reset/contract-static-hold")
        response = client.post(
            "/api/v1/stream/frame",
            json={
                "session_id": "contract-static-hold",
                "timestamp": "260702-160000-001",
                "primitive": hold_primitive(),
                "debug": False,
            },
        )
    data = response.json()
    assert data["status"] == "collecting"
    assert data["result"] is None
    assert data["sentence"] is None
    assert data["last_confirmed"] is None


def test_stream_frame_collecting_after_confirm_keeps_history_only_in_last_confirmed() -> None:
    with TestClient(app) as client:
        client.post("/api/v1/debug/reset/contract-post-confirm")
        for i in range(1, 7):
            confirmed_response = client.post(
                "/api/v1/stream/frame",
                json={
                    "session_id": "contract-post-confirm",
                    "timestamp": f"260702-160100-{i:03d}",
                    "primitive": primitive(),
                    "debug": False,
                },
            )
        confirmed = confirmed_response.json()
        assert confirmed["status"] == "confirmed"
        assert confirmed["result"]["word_base"] == "鍘曟墍"
        response = client.post(
            "/api/v1/stream/frame",
            json={
                "session_id": "contract-post-confirm",
                "timestamp": "260702-160200-001",
                "primitive": hold_primitive(),
                "debug": False,
            },
        )
    data = response.json()
    assert data["status"] == "collecting"
    assert data["result"] is None
    assert data["sentence"] is None
    assert data["last_confirmed"]["word_base"] == "鍘曟墍"
    assert data["last_confirmed"]["sentence"] == "鍘曟墍"


def test_stream_frame_repeated_same_word_does_not_emit_second_confirmed_result() -> None:
    with TestClient(app) as client:
        client.post("/api/v1/debug/reset/contract-repeat")
        responses = []
        for i in range(1, 11):
            responses.append(
                client.post(
                    "/api/v1/stream/frame",
                    json={
                        "session_id": "contract-repeat",
                        "timestamp": f"260702-160300-{i:03d}",
                        "primitive": primitive(),
                        "debug": False,
                    },
                ).json()
            )
    confirmed_words = [
        item["result"]["word_base"]
        for item in responses
        if item["status"] == "confirmed" and item.get("result")
    ]
    assert confirmed_words == ["鍘曟墍"]

