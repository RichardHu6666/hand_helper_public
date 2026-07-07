from __future__ import annotations

import argparse
import re
import time
from collections import Counter, defaultdict
from typing import Any

from common import (
    add_config_arg,
    load_config,
    log,
    main_guard,
    open_db,
    progress,
    read_jsonl,
    write_json,
    write_jsonl,
)


Tag = dict[str, Any]


PATTERNS: dict[str, list[tuple[str, str, float]]] = {
    "dominant_shape": [
        ("one", r"浼搁鎸噟椋熸寚鐩寸珛|椋熸寚妯几|椋熸寚鎸囧皷|浼稿嚭椋熸寚", 0.78),
        ("two", r"椋焄銆佸拰銆佷腑]*涓寚|椋熸寚鍜屼腑鎸噟椋熴€佷腑鎸囧垎寮€|椋熴€佷腑鎸囩洿绔?, 0.78),
        ("three", r"浼搁銆佷腑銆佹棤鍚嶆寚|椋熴€佷腑銆佹棤鍚嶆寚", 0.74),
        ("four", r"椋熴€佷腑銆佹棤鍚嶃€佸皬鎸?, 0.74),
        ("five", r"浜旀寚寮犲紑|浜旀寚骞舵嫝|浜旀寚寰洸|鎵嬫帉|鎺屽績|骞充几|妯几|鐩寸珛", 0.62),
        ("like", r"浼告媷鎸噟鎷囨寚鐩寸珛", 0.72),
        ("ok", r"鎷囥€侀鎸囨崗鎴愬渾褰鎷囨寚鍜岄鎸囨崗鎴愬渾褰鎷囥€侀鎸囨垚.*鍦嗗舰|鎴愬渾褰?, 0.76),
        ("call", r"浼告媷銆佸皬鎸噟鎷囥€佸皬鎸囦几鍑簗鎷囥€佸皬鎸囩洿绔?, 0.82),
        ("dislike", r"鎷囨寚灏栨湞涓媩鎷囨寚鍚戜笅", 0.80),
    ],
    "movement": [
        ("left_right", r"宸﹀彸|浠庡乏鍚戝彸|浠庡彸鍚戝乏|妯悜|鎽嗗姩|鎸ュ姩|鍒掕繃|妯几.*绉诲姩", 0.82),
        ("up_down", r"鍚戜笂|鍚戜笅|涓婁笅|涓婄Щ|涓嬬Щ|鎶捣|鎸変笅|涓€鎸墊涓嬫寜|鍚戜笅涓€?椤?, 0.80),
        ("toward_away", r"鍚戝墠|鍚戝|鍚戝唴|鎺ㄥ嚭|绉诲悜|闈犺繎|杩滅|鍓嶅悗|浠?*绉诲嚭|鍚?*绉诲叆", 0.78),
        ("open_close", r"寮犲紑|鎾悎|鎹忓悎|骞舵嫝|寮€鍚坾鎻℃嫵|寮洸|铚锋洸", 0.74),
        ("repeat", r"涓や笅|鍑犱笅|杩炵画|鍙嶅|浜ゆ浛|鏉ュ洖|涓€椤夸竴椤縷寰檭|鏅冨姩|杞姩.*鍦?, 0.78),
        ("hold", r"缃簬|璐翠簬|鎸変簬|鎶典簬|鏀惧湪|鎼垚|鎴?*褰?, 0.52),
    ],
    "body_anchor_hint": [
        ("head", r"澶磡鍓嶉|棰潀澶槼绌磡澶撮《", 0.82),
        ("face", r"鑴竱闈㈤儴|鐪紎鑰硘榧粅鍢磡鍙棰弢涓嬪反|棰?, 0.80),
        ("eye", r"鐪紎鐪肩潧|鐪奸儴", 0.84),
        ("ear", r"鑰硘鑰虫湹|鑰抽儴", 0.84),
        ("mouth", r"鍢磡鍙鍞噟鍠墊鍜藉枆", 0.82),
        ("chin", r"棰弢涓嬪反", 0.84),
        ("neck", r"棰坾鍠墊鍜藉枆", 0.82),
        ("shoulder", r"鑲﹟宸﹁偐|鍙宠偐", 0.80),
        ("chest", r"鑳竱鑳搁儴|宸﹁兏|鍙宠兏", 0.82),
        ("abdomen", r"鑵箌鑳億鑵归儴", 0.82),
        ("waist", r"鑵皘鑵伴儴", 0.82),
        ("hand", r"宸︽墜|鍙虫墜|鎵嬭儗|鎵嬫帉|鎺屽績|鑵?, 0.65),
        ("neutral_space", r"韬綋涓€渚韬墠|闈㈠墠|韬綋鍓嶆柟|鍓嶆柟", 0.62),
    ],
}


LOCATION_BY_ANCHOR = {
    "head": "signer_center_upper",
    "face": "signer_center_upper",
    "eye": "signer_center_upper",
    "ear": "signer_center_upper",
    "mouth": "signer_center_upper",
    "chin": "signer_center_upper",
    "neck": "signer_center_upper",
    "shoulder": "signer_center_lower",
    "chest": "signer_center_lower",
    "abdomen": "signer_center_lower",
    "waist": "signer_center_lower",
}


STEP_MARKER_RE = re.compile(r"锛?[涓€浜屼笁鍥涗簲鍏竷鍏節鍗乚+)锛?)


def make_tag(field: str, value: str, evidence: str, confidence: float, step_index: int | None) -> Tag:
    return {
        "field": field,
        "value": value,
        "evidence": evidence[:80],
        "confidence": round(confidence, 3),
        "method": "rule_v1",
        "step_index": step_index,
    }


def first_match(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    if not m:
        return None
    return m.group(0)


def split_steps(text: str) -> list[tuple[int | None, str]]:
    matches = list(STEP_MARKER_RE.finditer(text))
    if not matches:
        return [(None, text)]
    steps: list[tuple[int | None, str]] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        step_text = text[start:end].strip()
        if step_text:
            steps.append((idx + 1, step_text))
    return steps or [(None, text)]


def extract_hand_count(text: str, step_index: int | None) -> list[Tag]:
    tags: list[Tag] = []
    optional = first_match(r"涓€鎵嬫垨鍙屾墜|鍙屾墜锛堟垨涓€鎵嬶級|鍙屾墜锛堟垨鍗曟墜锛墊鍙屾墜鎴栦竴鎵?, text)
    if optional:
        tags.append(make_tag("hand_count", "1", optional, 0.70, step_index))
        tags.append(make_tag("hand_count", "2", optional, 0.70, step_index))
        return tags
    dual = first_match(r"鍙屾墜|涓ゆ墜|宸︽墜.*鍙虫墜|鍙虫墜.*宸︽墜", text)
    if dual:
        tags.append(make_tag("hand_count", "2", dual, 0.90, step_index))
        return tags
    single = first_match(r"涓€鎵媩鍙虫墜|宸︽墜", text)
    if single:
        tags.append(make_tag("hand_count", "1", single, 0.85, step_index))
    return tags


def extract_bimanual(text: str, hand_tags: list[Tag], shape_tags: list[Tag], step_index: int | None) -> list[Tag]:
    values = {t["value"] for t in hand_tags}
    tags: list[Tag] = []
    if "1" in values and "2" not in values:
        tags.append(make_tag("bimanual_relation", "single_hand", "hand_count=1", 0.82, step_index))
    if "2" in values:
        evidence = first_match(r"鍙屾墜|涓ゆ墜|宸︽墜.*鍙虫墜|鍙虫墜.*宸︽墜", text) or "hand_count=2"
        tags.append(make_tag("bimanual_relation", "dual_hand", evidence, 0.84, step_index))
        if first_match(r"鍙屾墜(浜旀寚|浼告媷鎸噟鎻℃嫵|椋熴€佷腑鎸噟骞充几|鐩寸珛)", text):
            tags.append(make_tag("bimanual_relation", "same_shape", evidence, 0.62, step_index))
        elif first_match(r"宸︽墜.*鍙虫墜|鍙虫墜.*宸︽墜", text) and len({t["value"] for t in shape_tags}) >= 2:
            tags.append(make_tag("bimanual_relation", "different_shape", evidence, 0.58, step_index))
    return tags


def extract_pattern_tags(text: str, field: str, step_index: int | None) -> list[Tag]:
    tags: list[Tag] = []
    seen: set[tuple[str, str]] = set()
    for value, pattern, conf in PATTERNS[field]:
        evidence = first_match(pattern, text)
        if evidence and (field, value) not in seen:
            tags.append(make_tag(field, value, evidence, conf, step_index))
            seen.add((field, value))
    return tags


def extract_location(anchor_tags: list[Tag], step_index: int | None) -> list[Tag]:
    tags: list[Tag] = []
    seen: set[str] = set()
    for tag in anchor_tags:
        loc = LOCATION_BY_ANCHOR.get(tag["value"])
        if loc and loc not in seen:
            tags.append(make_tag("location", loc, tag["evidence"], min(tag["confidence"], 0.72), step_index))
            seen.add(loc)
    return tags


def dedupe_tags(tags: list[Tag]) -> list[Tag]:
    best: dict[tuple[str, str, int | None], Tag] = {}
    for tag in tags:
        key = (tag["field"], tag["value"], tag.get("step_index"))
        if key not in best or tag["confidence"] > best[key]["confidence"]:
            best[key] = tag
    return sorted(best.values(), key=lambda t: (str(t.get("step_index")), t["field"], -t["confidence"], t["value"]))


def extract_tags_for_word(row: dict[str, Any]) -> tuple[list[Tag], float, list[str]]:
    all_tags: list[Tag] = []
    warnings: list[str] = []
    text = row.get("action_description", "")
    steps = split_steps(text)
    all_tags.append(make_tag("step_count", str(len(steps)), "step markers" if len(steps) > 1 else "single step", 0.90, None))
    for step_index, step_text in steps:
        hand_tags = extract_hand_count(step_text, step_index)
        shape_tags = extract_pattern_tags(step_text, "dominant_shape", step_index)
        movement_tags = extract_pattern_tags(step_text, "movement", step_index)
        anchor_tags = extract_pattern_tags(step_text, "body_anchor_hint", step_index)
        location_tags = extract_location(anchor_tags, step_index)
        bimanual_tags = extract_bimanual(step_text, hand_tags, shape_tags, step_index)
        all_tags.extend(hand_tags + shape_tags + movement_tags + anchor_tags + location_tags + bimanual_tags)
        if not hand_tags:
            warnings.append(f"step {step_index}: missing hand_count")
        if not movement_tags:
            warnings.append(f"step {step_index}: missing movement")
    all_tags = dedupe_tags(all_tags)
    fields = {t["field"] for t in all_tags}
    required = {"hand_count", "movement", "bimanual_relation"}
    coverage = len(fields & required) / len(required)
    avg_conf = sum(t["confidence"] for t in all_tags) / max(len(all_tags), 1)
    primitive_confidence = round((coverage * 0.7) + (avg_conf * 0.3), 3)
    return all_tags, primitive_confidence, warnings


def run_rule_extract(config_path: str) -> None:
    cfg = load_config(config_path)
    rows = read_jsonl(cfg.raw_jsonl)
    if not rows:
        raise FileNotFoundError(f"raw jsonl is empty or missing: {cfg.raw_jsonl}")
    log(f"[rule] loaded words={len(rows)}")
    start = time.time()
    tag_rows: list[dict[str, Any]] = []
    low_rows: list[dict[str, Any]] = []
    field_counter: Counter[str] = Counter()
    value_counter: Counter[tuple[str, str]] = Counter()

    for idx, row in enumerate(rows, 1):
        tags, primitive_confidence, warnings = extract_tags_for_word(row)
        for tag in tags:
            out = {
                "word_id": row["id"],
                "word": row["word"],
                **tag,
            }
            tag_rows.append(out)
            field_counter[tag["field"]] += 1
            value_counter[(tag["field"], tag["value"])] += 1
        if primitive_confidence < 0.65 or warnings:
            low_rows.append(
                {
                    "word_id": row["id"],
                    "word": row["word"],
                    "action_description": row["action_description"],
                    "primitive_confidence": primitive_confidence,
                    "warnings": warnings,
                    "rule_tags": tags,
                }
            )
        if idx == 1 or idx % cfg.progress_every == 0 or idx == len(rows):
            progress("[rule] processed", idx, len(rows), start)
            log(f"[rule] tags={len(tag_rows)} low_confidence={len(low_rows)}")

    write_jsonl(cfg.rule_tags_jsonl, tag_rows)
    write_jsonl(cfg.low_confidence_jsonl, low_rows)
    with open_db(cfg) as con:
        con.execute("DELETE FROM word_primitive_tag_table")
        con.executemany(
            """
            INSERT INTO word_primitive_tag_table
            (word_id, field, value, evidence, confidence, method, step_index)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["word_id"],
                    r["field"],
                    r["value"],
                    r.get("evidence", ""),
                    r.get("confidence", 0.0),
                    r.get("method", "rule_v1"),
                    r.get("step_index"),
                )
                for r in tag_rows
            ],
        )
        con.commit()

    field_coverage = {
        field: len({r["word_id"] for r in tag_rows if r["field"] == field}) / len(rows)
        for field in sorted(field_counter)
    }
    report = {
        "word_count": len(rows),
        "rule_tag_count": len(tag_rows),
        "rule_tagged_word_count": len({r["word_id"] for r in tag_rows}),
        "low_confidence_count": len(low_rows),
        "field_counts": dict(field_counter),
        "top_values": [
            {"field": k[0], "value": k[1], "count": v}
            for k, v in value_counter.most_common(40)
        ],
        "field_coverage": field_coverage,
    }
    write_json(cfg.primitive_report_json, report)
    log(f"[rule] done tags={len(tag_rows)} low_confidence={len(low_rows)}")


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    args = parser.parse_args()
    run_rule_extract(args.config)


if __name__ == "__main__":
    main()

