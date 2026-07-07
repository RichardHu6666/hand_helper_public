from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from common import add_config_arg, load_config, main_guard


DEFAULT_DB_NAME = "hand_language_vocabulary_lite.sqlite3"
DEFAULT_OUTPUT_MD = "lite_v3_collision_audit.md"
DEFAULT_OUTPUT_JSON = "lite_v3_collision_audit.json"

CORE_KEEP_WORDS = {
    "鍘曟墍",
    "甯姪",
    "楂樺叴",
    "鍖婚櫌",
    "瀛︽牎",
    "姘?,
    "鎵嬫満",
    "鐢佃瘽",
    "璇?,
    "瀵逛笉璧?,
    "鍐嶈",
    "瀹夐潤",
    "瀹夊叏",
    "娆㈣繋",
    "閾惰",
    "鍟嗗簵",
}

PREFER_EXCLUDE_WORDS = {
    "涓嶆槸",
    "鍚?,
    "鏉?,
    "浠€涔?,
    "璋?,
    "涓?,
    "涓?,
    "鍓?,
    "宸?,
    "鍙?,
    "閭ｉ噷",
    "杩欓噷",
    "鎱?,
    "鍐烽潤",
    "鍚屼簨",
    "鍚屽",
}

MAX_STEP_GROUP_WARNING = 12
MAX_LOOSE_GROUP_WARNING = 12

FIELD_ORDER = [
    "hand_count",
    "dominant_shape",
    "nondominant_shape",
    "movement",
    "location",
    "bimanual_relation",
]


def parse_primitive_text(text: str) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for part in text.split("|"):
        fields = {field: "unknown" for field in FIELD_ORDER}
        for key, value in re.findall(r"(\w+)=([^\s|]+)", part):
            fields[key] = value
        if any(value != "unknown" for value in fields.values()):
            steps.append(fields)
    return steps or [{field: "unknown" for field in FIELD_ORDER}]


def step_signature(step: dict[str, str]) -> str:
    return "|".join(
        [
            step.get("hand_count", "unknown"),
            step.get("movement", "unknown"),
            step.get("location", "unknown"),
            step.get("bimanual_relation", "unknown"),
        ]
    )


def loose_signature(step: dict[str, str]) -> str:
    return "|".join(
        [
            step.get("hand_count", "unknown"),
            step.get("movement", "unknown"),
            step.get("bimanual_relation", "unknown"),
        ]
    )


def load_rows(db_path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT id, word_base, action_description, retrieval_text, primitive_text
            FROM hand_language_vocabulary
            ORDER BY id
            """
        ).fetchall()
    finally:
        con.close()
    result = []
    for word_id, word_base, action_description, retrieval_text, primitive_text in rows:
        steps = parse_primitive_text(str(primitive_text))
        result.append(
            {
                "id": int(word_id),
                "word_base": str(word_base),
                "action_description": str(action_description),
                "retrieval_text": str(retrieval_text),
                "primitive_text": str(primitive_text),
                "steps": steps,
            }
        )
    return result


def group_exact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["primitive_text"]].append(row)
    return sorted(
        [
            {
                "primitive_text": primitive_text,
                "count": len(items),
                "words": [{"id": item["id"], "word_base": item["word_base"]} for item in items],
            }
            for primitive_text, items in groups.items()
            if len(items) >= 2
        ],
        key=lambda item: (-item["count"], item["primitive_text"]),
    )


def group_by_step(rows: list[dict[str, Any]], *, loose: bool) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        seen_for_word: set[str] = set()
        for step in row["steps"]:
            signature = loose_signature(step) if loose else step_signature(step)
            if signature in seen_for_word:
                continue
            seen_for_word.add(signature)
            group = groups.setdefault(signature, {"signature": signature, "words": []})
            group["words"].append({"id": row["id"], "word_base": row["word_base"]})
    result = []
    for group in groups.values():
        if len(group["words"]) >= 2:
            group["count"] = len(group["words"])
            result.append(group)
    return sorted(result, key=lambda item: (-item["count"], item["signature"]))


def load_exclude_words(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    words: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if text:
            words.add(text)
    return words


def suggest_exclusions(step_groups: list[dict[str, Any]], loose_groups: list[dict[str, Any]], existing_excludes: set[str]) -> list[dict[str, Any]]:
    scores: Counter[str] = Counter()
    reasons: dict[str, set[str]] = defaultdict(set)

    for group in step_groups:
        count = int(group["count"])
        if count < 6:
            continue
        for word in group["words"]:
            word_base = word["word_base"]
            if word_base in CORE_KEEP_WORDS:
                continue
            scores[word_base] += count
            reasons[word_base].add(f"step:{group['signature']} count={count}")

    for group in loose_groups:
        count = int(group["count"])
        if count < 10:
            continue
        for word in group["words"]:
            word_base = word["word_base"]
            if word_base in CORE_KEEP_WORDS:
                continue
            scores[word_base] += count
            reasons[word_base].add(f"loose:{group['signature']} count={count}")

    for word in PREFER_EXCLUDE_WORDS:
        if word in scores:
            scores[word] += 100
            reasons[word].add("preferred_high_ambiguity")

    suggestions = []
    for word, score in scores.most_common():
        suggestions.append(
            {
                "word_base": word,
                "score": score,
                "already_excluded": word in existing_excludes,
                "reasons": sorted(reasons[word]),
            }
        )
    return suggestions


def build_report(db_path: Path, exclude_words_path: Path | None) -> dict[str, Any]:
    rows = load_rows(db_path)
    exact_groups = group_exact(rows)
    step_groups = group_by_step(rows, loose=False)
    loose_groups = group_by_step(rows, loose=True)
    existing_excludes = load_exclude_words(exclude_words_path)
    left_right_group = next(
        (group for group in loose_groups if group["signature"] == "1|left_right|single_hand"),
        {"signature": "1|left_right|single_hand", "count": 0, "words": []},
    )
    warnings: list[str] = []
    if step_groups and int(step_groups[0]["count"]) > MAX_STEP_GROUP_WARNING:
        warnings.append(
            f"max step signature group remains high: {step_groups[0]['signature']} count={step_groups[0]['count']}"
        )
    if loose_groups and int(loose_groups[0]["count"]) > MAX_LOOSE_GROUP_WARNING:
        warnings.append(
            f"max loose signature group remains high: {loose_groups[0]['signature']} count={loose_groups[0]['count']}"
        )

    report = {
        "db_path": str(db_path),
        "row_count": len(rows),
        "exact_duplicate_group_count": len(exact_groups),
        "max_step_signature_group": step_groups[0] if step_groups else None,
        "max_loose_signature_group": loose_groups[0] if loose_groups else None,
        "left_right_single_hand_group": left_right_group,
        "exact_duplicate_groups": exact_groups,
        "step_signature_groups": step_groups,
        "loose_signature_groups": loose_groups,
        "existing_exclude_words": sorted(existing_excludes),
        "suggested_exclusions": suggest_exclusions(step_groups, loose_groups, existing_excludes),
        "warnings": warnings,
    }
    return report


def write_markdown(path: Path, report: dict[str, Any], *, top_n: int) -> None:
    lines = [
        "# Lite v3 Primitive Collision Audit",
        "",
        f"- DB: `{report['db_path']}`",
        f"- Rows: {report['row_count']}",
        f"- Exact duplicate groups: {report['exact_duplicate_group_count']}",
    ]
    max_step = report.get("max_step_signature_group")
    if max_step:
        lines.append(f"- Max step signature group: `{max_step['signature']}` ({max_step['count']} words)")
    max_loose = report.get("max_loose_signature_group")
    if max_loose:
        lines.append(f"- Max loose signature group: `{max_loose['signature']}` ({max_loose['count']} words)")
    left_right = report["left_right_single_hand_group"]
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    lines.extend(
        [
            f"- `1|left_right|single_hand`: {left_right['count']} words",
            "",
            "## Left Right Single-Hand Group",
            "",
            ", ".join(word["word_base"] for word in left_right["words"]) or "-",
            "",
            "## Top Step Signature Groups",
            "",
            "| count | signature | words |",
            "|---:|---|---|",
        ]
    )
    for group in report["step_signature_groups"][:top_n]:
        words = ", ".join(word["word_base"] for word in group["words"])
        lines.append(f"| {group['count']} | `{group['signature']}` | {words} |")

    lines.extend(["", "## Top Loose Signature Groups", "", "| count | signature | words |", "|---:|---|---|"])
    for group in report["loose_signature_groups"][:top_n]:
        words = ", ".join(word["word_base"] for word in group["words"])
        lines.append(f"| {group['count']} | `{group['signature']}` | {words} |")

    lines.extend(["", "## Exact Duplicate Groups", "", "| count | words | primitive_text |", "|---:|---|---|"])
    for group in report["exact_duplicate_groups"][:top_n]:
        words = ", ".join(word["word_base"] for word in group["words"])
        primitive_text = group["primitive_text"].replace("|", "\\|")
        lines.append(f"| {group['count']} | {words} | `{primitive_text}` |")

    lines.extend(["", "## Suggested Exclusions", "", "| word | already excluded | reasons |", "|---|---|---|"])
    for item in report["suggested_exclusions"][:top_n * 3]:
        reasons = "; ".join(item["reasons"])
        lines.append(f"| {item['word_base']} | {item['already_excluded']} | {reasons} |")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit(config_path: str, db_path: str | None, output_md: str | None, output_json: str | None, exclude_words: str | None, top_n: int) -> None:
    cfg = load_config(config_path)
    resolved_db = Path(db_path).expanduser().resolve() if db_path else cfg.output_dir / DEFAULT_DB_NAME
    if not resolved_db.exists():
        raise FileNotFoundError(f"lite db not found: {resolved_db}")
    exclude_path = Path(exclude_words).expanduser().resolve() if exclude_words else Path(__file__).resolve().with_name("lite_exclude_words.txt")

    report = build_report(resolved_db, exclude_path)
    md_path = Path(output_md).expanduser().resolve() if output_md else cfg.output_dir / DEFAULT_OUTPUT_MD
    json_path = Path(output_json).expanduser().resolve() if output_json else cfg.output_dir / DEFAULT_OUTPUT_JSON

    write_markdown(md_path, report, top_n=top_n)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[lite-audit] rows={report['row_count']}")
    print(f"[lite-audit] exact_duplicate_groups={report['exact_duplicate_group_count']}")
    if report["max_step_signature_group"]:
        group = report["max_step_signature_group"]
        print(f"[lite-audit] max_step={group['signature']} count={group['count']}")
    if report["max_loose_signature_group"]:
        group = report["max_loose_signature_group"]
        print(f"[lite-audit] max_loose={group['signature']} count={group['count']}")
    print(f"[lite-audit] left_right_single_hand={report['left_right_single_hand_group']['count']}")
    print(f"[lite-audit] md={md_path}")
    print(f"[lite-audit] json={json_path}")


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    parser.add_argument("--db-path", default=None, help=f"Lite SQLite path. Default: data/vocab_pipeline/{DEFAULT_DB_NAME}")
    parser.add_argument("--output-md", default=None, help=f"Markdown report path. Default: data/vocab_pipeline/{DEFAULT_OUTPUT_MD}")
    parser.add_argument("--output-json", default=None, help=f"JSON report path. Default: data/vocab_pipeline/{DEFAULT_OUTPUT_JSON}")
    parser.add_argument("--exclude-words", default=None, help="Optional exclude word list for suggestion annotations.")
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args()
    audit(args.config, args.db_path, args.output_md, args.output_json, args.exclude_words, args.top_n)


if __name__ == "__main__":
    main()

