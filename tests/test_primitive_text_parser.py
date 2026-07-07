from app.primitive_text_parser import parse_primitive_text


def test_single_step_parse() -> None:
    steps = parse_primitive_text(
        "step1 hand_count=1 dominant_shape=five nondominant_shape=no_hand movement=left_right location=signer_right_upper bimanual_relation=single_hand"
    )
    assert steps[0]["step_index"] == 1
    assert steps[0]["expected"]["movement"] == "left_right"


def test_multi_step_parse() -> None:
    steps = parse_primitive_text("step1 hand_count=1 movement=left_right | step2 hand_count=2 movement=up_down")
    assert [step["step_index"] for step in steps] == [1, 2]
    assert steps[1]["expected"]["hand_count"] == "2"


def test_missing_fields_are_unknown() -> None:
    steps = parse_primitive_text("step1 hand_count=1")
    assert steps[0]["expected"]["location"] == "unknown"


def test_invalid_step_is_ignored() -> None:
    assert parse_primitive_text("bad data | step1 movement=hold")[0]["expected"]["movement"] == "hold"


def test_relative_motion_parse() -> None:
    steps = parse_primitive_text("step1 hand_count=1 movement=left_right relative_motion=right_to_left")
    assert steps[0]["expected"]["relative_motion"] == "right_to_left"

