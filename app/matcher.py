from __future__ import annotations

from dataclasses import dataclass

from app.schemas import Candidate, Primitive
from app.storage import list_words


METHOD = "rule_text_score_v1"


HAND_COUNT_TEXT = {
    0: "娌℃湁妫€娴嬪埌鎵?,
    1: "鍗曟墜",
    2: "鍙屾墜",
}

DOMINANT_SIDE_TEXT = {
    "signer_right": "涓绘墜涓烘墜璇€呭彸鎵?,
    "signer_left": "涓绘墜涓烘墜璇€呭乏鎵?,
}

LOCATION_TEXT = {
    "signer_right_upper": "涓绘墜鍦ㄦ墜璇€呭彸涓婃柟",
    "signer_right_lower": "涓绘墜鍦ㄦ墜璇€呭彸涓嬫柟",
    "signer_left_upper": "涓绘墜鍦ㄦ墜璇€呭乏涓婃柟",
    "signer_left_lower": "涓绘墜鍦ㄦ墜璇€呭乏涓嬫柟",
    "signer_left_middle": "涓绘墜鍦ㄦ墜璇€呭乏涓儴",
    "signer_center_middle": "涓绘墜鍦ㄦ墜璇€呬腑闂?,
    "signer_right_middle": "涓绘墜鍦ㄦ墜璇€呭彸涓儴",
    "signer_center_upper": "涓绘墜鍦ㄦ墜璇€呮涓婃柟",
    "signer_center_lower": "涓绘墜鍦ㄦ墜璇€呮涓嬫柟",
}

MOVEMENT_TEXT = {
    "hold": "淇濇寔涓嶅姩",
    "left_right": "宸﹀彸绉诲姩",
    "up_down": "涓婁笅绉诲姩",
    "toward_away": "闈犺繎鎴栬繙绂绘憚鍍忓ご",
    "open_close": "寮犲紑鎴栧悎鎷?,
    "repeat": "閲嶅鍔ㄤ綔",
}
RELATIVE_MOTION_TEXT = {
    "hold": "鐩稿闈欐",
    "left_right": "鐩稿宸﹀彸绉诲姩",
    "left_to_right": "鐩稿浠庡乏鍚戝彸绉诲姩",
    "right_to_left": "鐩稿浠庡彸鍚戝乏绉诲姩",
    "up_down": "鐩稿涓婁笅绉诲姩",
    "up_to_down": "鐩稿浠庝笂鍚戜笅绉诲姩",
    "down_to_up": "鐩稿浠庝笅鍚戜笂绉诲姩",
    "toward_away": "鐩稿鍓嶅悗绉诲姩",
    "toward": "鐩稿鏈濆悜鎽勫儚澶?,
    "away": "鐩稿杩滅鎽勫儚澶?,
    "open_close": "鐩稿寮€鍚?,
    "repeat": "鐩稿閲嶅鍔ㄤ綔",
}

BIMANUAL_TEXT = {
    "single_hand": "鍗曟墜鍔ㄤ綔",
    "dual_hand": "鍙屾墜鍔ㄤ綔",
    "same_shape": "鍙屾墜鍚屾墜鍨?,
    "different_shape": "鍙屾墜涓嶅悓鎵嬪瀷",
}

UNKNOWN_SHAPES = {"no_gesture", "no_hand", "unknown"}


@dataclass
class Score:
    value: float
    reasons: list[str]


def primitive_to_text(primitive: Primitive) -> str:
    parts = [HAND_COUNT_TEXT[primitive.hand_count]]

    if primitive.dominant_side in DOMINANT_SIDE_TEXT:
        parts.append(DOMINANT_SIDE_TEXT[primitive.dominant_side])
    if primitive.location in LOCATION_TEXT:
        parts.append(LOCATION_TEXT[primitive.location])
    if primitive.movement in MOVEMENT_TEXT:
        parts.append(MOVEMENT_TEXT[primitive.movement])
    if primitive.relative_motion in RELATIVE_MOTION_TEXT:
        parts.append(RELATIVE_MOTION_TEXT[primitive.relative_motion])
    if primitive.bimanual_relation in BIMANUAL_TEXT:
        parts.append(BIMANUAL_TEXT[primitive.bimanual_relation])

    if primitive.dominant_shape in UNKNOWN_SHAPES:
        parts.append("涓绘墜鎵嬪瀷鏈煡")
    else:
        parts.append(f"涓绘墜鎵嬪瀷 {primitive.dominant_shape}")

    return "锛?.join(parts) + "銆?


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _add(score: Score, amount: float, reason: str) -> None:
    score.value += amount
    score.reasons.append(reason)


def _score_word(primitive: Primitive, word: dict) -> Score:
    text = f"{word['word_description']} {word['action_description']}".lower()
    score = Score(value=0.0, reasons=[])

    if primitive.hand_count == 1 and _contains_any(text, ["鍗曟墜", "涓€鎵?]):
        _add(score, 0.20, "hand_count:1 matched")
    elif primitive.hand_count == 2 and _contains_any(text, ["鍙屾墜", "涓ゆ墜"]):
        _add(score, 0.20, "hand_count:2 matched")

    if primitive.movement == "left_right" and _contains_any(
        text, ["宸﹀彸", "鎽嗗姩", "鎸ュ姩", "妯悜"]
    ):
        _add(score, 0.22, "movement:left_right matched")
    elif primitive.movement == "up_down" and _contains_any(
        text, ["涓婁笅", "鍚戜笂", "鍚戜笅", "涓嬬Щ", "涓婄Щ"]
    ):
        _add(score, 0.22, "movement:up_down matched")
    elif primitive.movement == "toward_away" and _contains_any(
        text, ["鍚戝墠", "鍚戝", "鍚戝唴", "闈犺繎", "杩滅", "鎺ㄥ嚭"]
    ):
        _add(score, 0.22, "movement:toward_away matched")
    elif primitive.movement == "hold" and _contains_any(
        text, ["鍋?, "缃簬", "璐翠簬", "鏀惧湪"]
    ):
        _add(score, 0.12, "movement:hold matched")

    if primitive.bimanual_relation == "single_hand" and _contains_any(
        text, ["鍗曟墜", "涓€鎵?]
    ):
        _add(score, 0.12, "bimanual_relation:single_hand matched")
    elif primitive.bimanual_relation in {"dual_hand", "same_shape", "different_shape"}:
        if _contains_any(text, ["鍙屾墜", "涓ゆ墜"]):
            _add(score, 0.12, f"bimanual_relation:{primitive.bimanual_relation} matched")

    shape = primitive.dominant_shape
    if shape == "five" and _contains_any(text, ["浜旀寚", "寮犲紑", "鎺?]):
        _add(score, 0.12, "shape:five matched")
    elif shape == "one" and _contains_any(text, ["椋熸寚", "涓€鎸?]):
        _add(score, 0.12, "shape:one matched")
    elif shape == "like" and _contains_any(text, ["鎷囨寚", "璧?]):
        _add(score, 0.12, "shape:like matched")
    elif shape == "ok" and _contains_any(text, ["鎷囥€侀鎸?, "鎷囨寚鍜岄鎸?, "鍦?]):
        _add(score, 0.12, "shape:ok matched")
    elif shape == "two" and _contains_any(text, ["浜屾寚", "涓ゆ寚", "椋熸寚鍜屼腑鎸?]):
        _add(score, 0.08, "shape:two matched")
    elif shape == "three" and _contains_any(text, ["涓夋寚"]):
        _add(score, 0.08, "shape:three matched")
    elif shape == "four" and _contains_any(text, ["鍥涙寚"]):
        _add(score, 0.08, "shape:four matched")
    elif shape == "call" and _contains_any(text, ["鐢佃瘽", "鎷囨寚鍜屽皬鎸?]):
        _add(score, 0.08, "shape:call matched")
    elif shape == "dislike" and _contains_any(text, ["鍚戜笅", "涓嶅ソ"]):
        _add(score, 0.08, "shape:dislike matched")

    if "upper" in primitive.location and _contains_any(text, ["澶?, "鑴?, "棰?, "鑰?]):
        _add(score, 0.08, "location:upper matched")
    elif "lower" in primitive.location and _contains_any(
        text, ["鑳?, "鑵?, "鑵?, "涓嬫柟"]
    ):
        _add(score, 0.08, "location:lower matched")

    score.value = max(0.0, min(1.0, score.value))
    return score


def match_primitive(primitive: Primitive, top_k: int) -> list[Candidate]:
    candidates = []
    for word in list_words():
        score = _score_word(primitive, word)
        candidates.append(
            Candidate(
                id=word["id"],
                word=word["word"],
                score=round(score.value, 4),
                reason="; ".join(score.reasons) if score.reasons else "no rule matched",
                word_description=word["word_description"],
                action_description=word["action_description"],
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.id))
    return candidates[:top_k]

