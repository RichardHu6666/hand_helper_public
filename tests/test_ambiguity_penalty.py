from collections import Counter
from types import SimpleNamespace

from app.candidate_scorer import ambiguity_penalty, build_signature_counts, score_candidate
from app.frame_step_scorer import score_frame_step
from app.schemas import Primitive
from app.stream_models import Span, StreamFrame


def test_expected_unknown_does_not_add_positive_score() -> None:
    primitive = Primitive(
        hand_count=1,
        dominant_side="signer_right",
        location="signer_center_upper",
        movement="left_right",
        bimanual_relation="single_hand",
        dominant_shape="five",
        nondominant_shape="no_hand",
    )
    result = score_frame_step(
        primitive,
        {
            "hand_count": "unknown",
            "movement": "unknown",
            "location": "unknown",
            "bimanual_relation": "unknown",
            "dominant_shape": "unknown",
            "nondominant_shape": "unknown",
        },
    )
    assert result["score"] == 0.0
    assert result["matched_fields"] == []


def test_duplicate_signature_gets_ambiguity_penalty() -> None:
    steps = [
        {
            "step_index": 1,
            "expected": {
                "hand_count": "1",
                "movement": "left_right",
                "location": "signer_center_upper",
                "bimanual_relation": "single_hand",
                "dominant_shape": "five",
                "nondominant_shape": "no_hand",
            },
        }
    ]
    unique = ambiguity_penalty(steps, Counter({"1|left_right|signer_center_upper|single_hand": 1}), Counter({"1|left_right|single_hand": 1}))
    duplicate = ambiguity_penalty(steps, Counter({"1|left_right|signer_center_upper|single_hand": 4}), Counter({"1|left_right|single_hand": 10}))
    assert unique == 0.0
    assert duplicate > unique


def test_ambiguity_penalty_lowers_equal_candidate_score() -> None:
    frame = StreamFrame(
        session_id="s",
        timestamp="260701-143012-001",
        timestamp_ms=0,
        seq_in_second=1,
        primitive=Primitive(
            hand_count=1,
            dominant_side="signer_right",
            location="signer_center_upper",
            movement="left_right",
            bimanual_relation="single_hand",
            dominant_shape="five",
            nondominant_shape="no_hand",
        ),
    )
    span = Span(duration_ms=500, frames=[frame, frame, frame, frame])
    summary = {"unknown_ratio": 0.0, "stability_score": 1.0}
    alignment = {"score": 1.0, "conflict_count": 0}
    clear = score_candidate(span, summary, alignment, [], ambiguity=0.0)
    ambiguous = score_candidate(span, summary, alignment, [], ambiguity=0.05)
    assert ambiguous["final_score"] < clear["final_score"]
    assert ambiguous["ambiguity_penalty"] == 0.05


def test_build_signature_counts_counts_repeated_templates() -> None:
    entry = SimpleNamespace(
        steps=[
            {
                "expected": {
                    "hand_count": "1",
                    "movement": "left_right",
                    "location": "signer_center_upper",
                    "bimanual_relation": "single_hand",
                }
            }
        ]
    )
    step_counts, loose_counts = build_signature_counts([entry, entry])
    assert step_counts["1|left_right|signer_center_upper|single_hand"] == 2
    assert loose_counts["1|left_right|single_hand"] == 2

