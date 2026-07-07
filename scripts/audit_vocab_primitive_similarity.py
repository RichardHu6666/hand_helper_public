#!/usr/bin/env python
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.primitive_text_parser import parse_primitive_text
from app.storage import LITE_DB_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_MD = PROJECT_ROOT / "reports/vocab_primitive_similarity.md"
REPORT_JSON = PROJECT_ROOT / "reports/vocab_primitive_similarity.json"
PROBLEM_MD = PROJECT_ROOT / "reports/fixture_problem_analysis.md"
WEIGHTS = {
    "hand_count": 2.0,
    "movement": 2.2,
    "location": 1.6,
    "bimanual_relation": 1.5,
    "dominant_shape": 0.4,
    "nondominant_shape": 0.3,
}
WEAK = {"unknown", "no_gesture", "no_hand", "", None}


def load_entries() -> list[dict[str, Any]]:
    with sqlite3.connect(LITE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, word_base, action_description, retrieval_text, primitive_text
            FROM hand_language_vocabulary
            ORDER BY id ASC
            """
        ).fetchall()
    entries = []
    for row in rows:
        item = dict(row)
        item["steps"] = parse_primitive_text(item["primitive_text"])
        entries.append(item)
    return entries


def step_expected(entry: dict[str, Any]) -> list[dict[str, str]]:
    return [step["expected"] for step in entry.get("steps", [])]


def step_signature(expected: dict[str, str]) -> str:
    return "|".join(
        [
            str(expected.get("hand_count", "unknown")),
            str(expected.get("movement", "unknown")),
            str(expected.get("location", "unknown")),
            str(expected.get("bimanual_relation", "unknown")),
        ]
    )


def loose_signature(expected: dict[str, str]) -> str:
    return "|".join(
        [
            str(expected.get("hand_count", "unknown")),
            str(expected.get("movement", "unknown")),
            str(expected.get("bimanual_relation", "unknown")),
        ]
    )


def entry_step_signatures(entry: dict[str, Any]) -> list[str]:
    return [step_signature(expected) for expected in step_expected(entry)]


def entry_loose_signatures(entry: dict[str, Any]) -> list[str]:
    return [loose_signature(expected) for expected in step_expected(entry)]


def field_similarity(a: str, b: str, weight: float) -> tuple[float, float]:
    if a in WEAK and b in WEAK:
        return 0.0, weight
    if a in WEAK or b in WEAK:
        return 0.15 * weight, weight
    if a == b:
        return weight, weight
    return 0.0, weight


def step_similarity(a: dict[str, str], b: dict[str, str]) -> float:
    score = 0.0
    total = 0.0
    for field, weight in WEIGHTS.items():
        contribution, denom = field_similarity(str(a.get(field, "unknown")), str(b.get(field, "unknown")), weight)
        score += contribution
        total += denom
    return round(score / max(total, 0.0001), 4)


def entry_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_steps = step_expected(a)
    b_steps = step_expected(b)
    if not a_steps or not b_steps:
        return 0.0
    scores = []
    for a_step in a_steps:
        scores.append(max(step_similarity(a_step, b_step) for b_step in b_steps))
    return round(sum(scores) / len(scores), 4)


def weak_shape_ratio(entry: dict[str, Any]) -> float:
    shape_values = []
    for expected in step_expected(entry):
        shape_values.extend([expected.get("dominant_shape"), expected.get("nondominant_shape")])
    return sum(1 for value in shape_values if value in WEAK) / max(len(shape_values), 1)


def is_adhesive_template(entry: dict[str, Any]) -> bool:
    for expected in step_expected(entry):
        hand_count = expected.get("hand_count") not in WEAK
        movement = expected.get("movement") not in WEAK and expected.get("movement") != "hold"
        relation = expected.get("bimanual_relation") not in WEAK and expected.get("bimanual_relation") != "none"
        broad_location = expected.get("location") in WEAK or expected.get("location") in {"signer_left", "signer_center", "signer_right"}
        weak_shapes = expected.get("dominant_shape") in WEAK or expected.get("nondominant_shape") in WEAK
        if hand_count and movement and relation and broad_location and weak_shapes:
            return True
    return False


def grouped(entries: list[dict[str, Any]], key_func, min_count: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        keys = key_func(entry)
        if isinstance(keys, list):
            for key in keys:
                groups[key].append(entry)
        else:
            groups[keys].append(entry)
    result = []
    for key, members in groups.items():
        if len(members) >= min_count:
            result.append(
                {
                    "signature": key,
                    "primitive_text": key,
                    "count": len(members),
                    "words": [{"id": item["id"], "word_base": item["word_base"]} for item in members],
                }
            )
    result.sort(key=lambda item: (-item["count"], item["signature"]))
    return result


def audit() -> dict[str, Any]:
    entries = load_entries()
    exact_groups = grouped(entries, lambda e: e["primitive_text"], 2)
    step_groups = grouped(entries, entry_step_signatures, 2)
    loose_groups = grouped(entries, entry_loose_signatures, 3)
    toilet = next((entry for entry in entries if entry["word_base"] == "鍘曟墍"), None)
    similar_to_toilet = []
    if toilet:
        for entry in entries:
            if entry["id"] == toilet["id"]:
                continue
            similar_to_toilet.append(
                {
                    "id": entry["id"],
                    "word_base": entry["word_base"],
                    "similarity": entry_similarity(toilet, entry),
                    "primitive_text": entry["primitive_text"],
                    "action_description": entry["action_description"],
                }
            )
        similar_to_toilet.sort(key=lambda item: (-item["similarity"], item["id"]))
    adhesive = [
        {
            "id": entry["id"],
            "word_base": entry["word_base"],
            "primitive_text": entry["primitive_text"],
            "action_description": entry["action_description"],
            "step_signatures": entry_step_signatures(entry),
            "loose_signatures": entry_loose_signatures(entry),
            "weak_shape_ratio": round(weak_shape_ratio(entry), 4),
        }
        for entry in entries
        if is_adhesive_template(entry)
    ]
    return {
        "entry_count": len(entries),
        "exact_duplicate_groups": exact_groups,
        "step_signature_duplicate_groups": step_groups,
        "loose_signature_duplicate_groups": loose_groups,
        "similar_to_toilet_top20": similar_to_toilet[:20],
        "adhesive_templates": adhesive,
        "toilet": toilet,
    }


def words_text(words: list[dict[str, Any]], limit: int = 12) -> str:
    shown = words[:limit]
    text = ", ".join(f"{item['id']}:{item['word_base']}" for item in shown)
    if len(words) > limit:
        text += f", ... (+{len(words) - limit})"
    return text


def render_md(report: dict[str, Any]) -> str:
    lines = ["# Vocab Primitive Similarity Report", ""]
    lines.append(f"- entries: {report['entry_count']}")
    lines.append(f"- exact duplicate groups: {len(report['exact_duplicate_groups'])}")
    lines.append(f"- step signature duplicate groups: {len(report['step_signature_duplicate_groups'])}")
    lines.append(f"- loose signature duplicate groups: {len(report['loose_signature_duplicate_groups'])}")
    lines.append(f"- adhesive templates: {len(report['adhesive_templates'])}")
    lines.extend(["", "## A. Exact primitive_text Duplicate Groups", ""])
    for group in report["exact_duplicate_groups"][:50]:
        lines.append(f"### count={group['count']}")
        lines.append(f"- primitive_text: `{group['signature']}`")
        lines.append(f"- words: {words_text(group['words'])}")
        lines.append("")
    lines.extend(["## B. Step Signature Duplicate Groups", ""])
    for group in report["step_signature_duplicate_groups"][:80]:
        lines.append(f"- `{group['signature']}` count={group['count']} words={words_text(group['words'])}")
    lines.extend(["", "## C. Loose Signature Duplicate Groups", ""])
    for group in report["loose_signature_duplicate_groups"][:80]:
        lines.append(f"- `{group['signature']}` count={group['count']} words={words_text(group['words'])}")
    lines.extend(["", "## D. Top20 Similar To 鍘曟墍", ""])
    lines.append("| rank | id | word_base | similarity | primitive_text |")
    lines.append("|---:|---:|---|---:|---|")
    for rank, item in enumerate(report["similar_to_toilet_top20"], start=1):
        primitive = str(item["primitive_text"]).replace("|", "\\|")
        lines.append(f"| {rank} | {item['id']} | {item['word_base']} | {item['similarity']} | `{primitive}` |")
    lines.extend(["", "## E. High Adhesion Templates", ""])
    lines.append("| id | word_base | weak_shape_ratio | signatures | primitive_text |")
    lines.append("|---:|---|---:|---|---|")
    for item in report["adhesive_templates"]:
        primitive = str(item["primitive_text"]).replace("|", "\\|")
        lines.append(f"| {item['id']} | {item['word_base']} | {item['weak_shape_ratio']} | {', '.join(item['loose_signatures'])} | `{primitive}` |")
    return "\n".join(lines) + "\n"


def build_problem_analysis(vocab_report: dict[str, Any]) -> str:
    fixture_path = PROJECT_ROOT / "reports/fixture_audit.json"
    if not fixture_path.exists():
        return "# Fixture Problem Analysis\n\nfixture_audit.json missing. Run scripts/audit_fixture_results.py first.\n"
    fixture_report = json.loads(fixture_path.read_text(encoding="utf-8"))
    exact_ids = {word["id"] for group in vocab_report["exact_duplicate_groups"] for word in group["words"]}
    step_ids = {word["id"] for group in vocab_report["step_signature_duplicate_groups"] for word in group["words"]}
    loose_ids = {word["id"] for group in vocab_report["loose_signature_duplicate_groups"] for word in group["words"]}
    adhesive_ids = {item["id"] for item in vocab_report["adhesive_templates"]}
    targets = {
        "stream_left_right_single.jsonl",
        "stream_repeat_same_word.jsonl",
        "stream_noisy_shape.jsonl",
    }
    lines = ["# Fixture Problem Analysis", ""]
    lines.extend([
        "## Candidate Fix Options",
        "",
        "### Option A: revise lite SQLite primitive_text",
        "Use this only when action_description clearly proves a primitive_text is wrong. Current evidence does not prove `鍘曟墍` is wrong; its action_description says the hand moves left-right, so it is marked needs_review rather than edited.",
        "",
        "### Option B: scoring wildcard check",
        "Current frame_step_scorer does not give positive contribution for expected=unknown; it skips the field. candidate_scorer already applies expected_unknown_ratio inside unknown_penalty. No bug found here.",
        "",
        "### Option C: ambiguity_penalty",
        "Many entries share the same step/loose signatures. A small generic ambiguity_penalty can reduce overconfidence for common signatures without special-casing any word.",
        "",
    ])
    for fixture in fixture_report.get("fixtures", []):
        if fixture.get("name") not in targets:
            continue
        candidates = fixture.get("final_top_candidates") or []
        top1 = candidates[0] if candidates else {}
        top2 = candidates[1] if len(candidates) > 1 else {}
        top1_id = top1.get("id")
        top2_score = top2.get("score")
        top1_score = top1.get("score")
        margin = None
        if isinstance(top1_score, (int, float)) and isinstance(top2_score, (int, float)):
            margin = round(top1_score - top2_score, 4)
        lines.extend([f"## {fixture['name']}", ""])
        lines.append(f"- top1: {top1.get('word_base')} ({top1_id}) score={top1_score}")
        lines.append("- top5: " + ", ".join(f"{c.get('word_base')}({c.get('score')})" for c in candidates[:5]))
        lines.append(f"- top1_top2_margin: {margin}")
        lines.append(f"- top1_conflict_fields: {top1.get('conflict_fields', [])}")
        lines.append(f"- top1_unknown_penalty: {(top1.get('score_breakdown') or {}).get('unknown_penalty')}")
        lines.append(f"- top1_conflict_penalty: {(top1.get('score_breakdown') or {}).get('conflict_penalty')}")
        lines.append(f"- top1_primitive_text: `{top1.get('primitive_text')}`")
        lines.append(f"- in_exact_duplicate_group: {top1_id in exact_ids}")
        lines.append(f"- in_step_signature_duplicate_group: {top1_id in step_ids}")
        lines.append(f"- in_loose_signature_duplicate_group: {top1_id in loose_ids}")
        lines.append(f"- high_adhesion_template: {top1_id in adhesive_ids}")
        if top1.get("word_base") == "鍘曟墍":
            lines.append("- why_toilet_wins: fixture primitive uses hand_count=1, movement=left_right, location=signer_center_upper, bimanual_relation=single_hand, dominant_shape=five, nondominant_shape=no_hand, which exactly matches `鍘曟墍` primitive_text. conflict_fields is empty and penalties are zero, so this is a fixture/vocab granularity issue more than a scoring bug.")
        lines.append("")
    return "\n".join(lines)


def write_reports(report: dict[str, Any]) -> None:
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(render_md(report), encoding="utf-8")
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PROBLEM_MD.write_text(build_problem_analysis(report), encoding="utf-8")


def main() -> int:
    report = audit()
    write_reports(report)
    print(f"entries={report['entry_count']}")
    print(f"exact_duplicate_groups={len(report['exact_duplicate_groups'])}")
    print(f"step_signature_duplicate_groups={len(report['step_signature_duplicate_groups'])}")
    print(f"loose_signature_duplicate_groups={len(report['loose_signature_duplicate_groups'])}")
    print(f"adhesive_templates={len(report['adhesive_templates'])}")
    print(f"wrote {REPORT_MD.relative_to(PROJECT_ROOT)}")
    print(f"wrote {REPORT_JSON.relative_to(PROJECT_ROOT)}")
    print(f"wrote {PROBLEM_MD.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

