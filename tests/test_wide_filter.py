from app.wide_filter import count_step_conflicts, passes_wide_filter


def summary(**overrides):
    modes = {
        "hand_count": "1",
        "movement": "left_right",
        "location": "signer_left_upper",
        "bimanual_relation": "single_hand",
        "dominant_shape": "no_gesture",
        "nondominant_shape": "no_hand",
    }
    modes.update(overrides)
    return {"field_modes": modes, "unknown_ratio": 0.0}


def step(**overrides):
    expected = {
        "hand_count": "1",
        "movement": "left_right",
        "location": "signer_left_lower",
        "bimanual_relation": "single_hand",
        "dominant_shape": "five",
        "nondominant_shape": "no_hand",
    }
    expected.update(overrides)
    return {"step_index": 1, "expected": expected}


def test_unknown_shape_does_not_reject() -> None:
    assert passes_wide_filter(summary(dominant_shape="no_gesture"), [step()])[0]


def test_individual_conflicts_count() -> None:
    assert count_step_conflicts(summary(hand_count="1"), step(hand_count="2")["expected"])[0] == 1
    assert count_step_conflicts(summary(movement="left_right"), step(movement="up_down")["expected"])[0] == 1
    assert count_step_conflicts(summary(bimanual_relation="single_hand"), step(bimanual_relation="dual_hand")["expected"])[0] == 1


def test_conflicts_threshold() -> None:
    ok, conflicts = passes_wide_filter(summary(hand_count="2"), [step(hand_count="1")])
    assert ok and conflicts == ["hand_count"]
    ok, conflicts = passes_wide_filter(
        summary(hand_count="2", movement="up_down", bimanual_relation="dual_hand"),
        [step(hand_count="1", movement="left_right", bimanual_relation="single_hand")],
    )
    assert not ok
    assert len(conflicts) > 1

