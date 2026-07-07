from app.schemas import Primitive
from app.step_aligner import align_span_to_steps
from app.stream_models import Span, StreamFrame


def frame(seq: int, **overrides) -> StreamFrame:
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
    return StreamFrame("s", f"260701-143012-{seq:03d}", 1782916212000 + seq * 100, seq, Primitive(**data))


def step(index: int, **overrides):
    expected = {
        "hand_count": "1",
        "dominant_shape": "five",
        "nondominant_shape": "no_hand",
        "movement": "left_right",
        "location": "signer_center_upper",
        "bimanual_relation": "single_hand",
    }
    expected.update(overrides)
    return {"step_index": index, "expected": expected}


def test_single_step_scores_high() -> None:
    result = align_span_to_steps(Span(500, [frame(i) for i in range(1, 5)]), [step(1)])
    assert result["complete"] is True
    assert result["score"] > 0.8


def test_two_step_left_to_right_path() -> None:
    frames = [frame(1), frame(2), frame(3, hand_count=2, movement="up_down", bimanual_relation="dual_hand", nondominant_shape="unknown"), frame(4, hand_count=2, movement="up_down", bimanual_relation="dual_hand", nondominant_shape="unknown")]
    result = align_span_to_steps(Span(500, frames), [step(1), step(2, hand_count="2", movement="up_down", bimanual_relation="dual_hand", nondominant_shape="unknown")])
    assert result["complete"] is True
    assert [item["step_index"] for item in result["path"]] == [1, 2]


def test_partial_is_not_complete() -> None:
    result = align_span_to_steps(Span(500, [frame(i) for i in range(1, 4)]), [step(1), step(2, movement="up_down")])
    assert result["complete"] is False


def test_no_gesture_shape_does_not_fail() -> None:
    result = align_span_to_steps(Span(500, [frame(i, dominant_shape="no_gesture") for i in range(1, 4)]), [step(1)])
    assert result["score"] > 0.6


def test_nondominant_no_hand_matches() -> None:
    result = align_span_to_steps(Span(500, [frame(i, nondominant_shape="no_hand") for i in range(1, 4)]), [step(1, nondominant_shape="no_hand")])
    assert "nondominant_shape" in result["path"][0]["matched_fields"]

