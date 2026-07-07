from app.schemas import StreamFrameRequest
from app.stream_decoder import StreamDecoder
from app.stream_models import StreamFrame


def primitive(**overrides):
    data = {
        "hand_count": 1,
        "dominant_side": "signer_right",
        "location": "signer_center_upper",
        "movement": "left_right",
        "bimanual_relation": "single_hand",
        "dominant_shape": "five",
        "nondominant_shape": "no_hand",
    }
    data.update(overrides)
    return data


def request(seq: int, session: str = "s", **overrides) -> StreamFrameRequest:
    return StreamFrameRequest(session_id=session, timestamp=f"260701-143012-{seq:03d}", primitive=primitive(**overrides), debug=True)


def decode(decoder: StreamDecoder, seq: int, session: str = "s", **overrides):
    return decoder.decode(StreamFrame.from_request(request(seq, session, **overrides)), include_debug=True)


def test_collecting_then_pending_then_confirmed() -> None:
    decoder = StreamDecoder()
    assert decode(decoder, 1)["status"] == "collecting"
    assert decode(decoder, 2)["status"] == "collecting"
    statuses = [decode(decoder, i)["status"] for i in range(3, 8)]
    assert "pending" in statuses
    assert "confirmed" in statuses


def test_reset_session_clears_buffer() -> None:
    decoder = StreamDecoder()
    decode(decoder, 1, session="r")
    decoder.reset("r")
    assert decoder.store.get("r").frames == []


def test_decode_batch_preserves_mid_batch_confirmed_result() -> None:
    decoder = StreamDecoder()
    frames = [
        StreamFrame.from_request(request(i, session="batch-preserve"))
        for i in range(1, 7)
    ]
    frames.append(StreamFrame.from_request(request(99, session="batch-preserve", movement="hold", relative_motion="hold", location="signer_right_upper", dominant_shape="no_gesture")))
    response = decoder.decode_batch(frames, include_debug=True)
    assert response["result"] is not None
    assert response["result"]["word_base"] == "鍘曟墍"
    assert any(item["status"] == "confirmed" for item in response["debug"]["frame_results"])

