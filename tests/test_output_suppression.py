from app.schemas import StreamFrameRequest
from app.stream_decoder import StreamDecoder
from app.stream_models import StreamFrame


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


def send(decoder: StreamDecoder, seq: int):
    req = StreamFrameRequest(session_id="suppress", timestamp=f"260701-143012-{seq:03d}", primitive=primitive(), debug=True)
    return decoder.decode(StreamFrame.from_request(req), include_debug=True)


def test_same_word_not_confirmed_repeatedly_in_cooldown() -> None:
    decoder = StreamDecoder()
    statuses = [send(decoder, i)["status"] for i in range(1, 9)]
    assert statuses.count("confirmed") == 1


def test_same_word_not_confirmed_repeatedly_in_continuous_long_stream() -> None:
    decoder = StreamDecoder()
    statuses = [send(decoder, i)["status"] for i in range(1, 101)]
    assert statuses.count("confirmed") == 1

