from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import sqlite3
from typing import Any

from common import add_config_arg, load_config, log, main_guard, open_db


PRIMITIVE_FIELDS = [
    "hand_count",
    "dominant_shape",
    "nondominant_shape",
    "movement",
    "location",
    "bimanual_relation",
]

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hand_language_vocabulary (
    id INTEGER PRIMARY KEY,
    word_base TEXT NOT NULL,
    action_description TEXT NOT NULL,
    retrieval_text TEXT NOT NULL,
    primitive_text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hlv_word_base ON hand_language_vocabulary(word_base);
"""


def default_step_fields(hand_count: str) -> dict[str, str]:
    fields = {
        "hand_count": hand_count or "unknown",
        "dominant_shape": "unknown",
        "nondominant_shape": "unknown",
        "movement": "unknown",
        "location": "unknown",
        "bimanual_relation": "unknown",
    }
    if hand_count == "1":
        fields["nondominant_shape"] = "no_hand"
        fields["bimanual_relation"] = "single_hand"
    elif hand_count == "2":
        fields["bimanual_relation"] = "dual_hand"
    return fields


def better_tag(current: dict[str, Any] | None, candidate: dict[str, Any]) -> bool:
    if current is None:
        return True
    current_score = float(current.get("confidence", 0.0))
    candidate_score = float(candidate.get("confidence", 0.0))
    if candidate_score != current_score:
        return candidate_score > current_score
    current_source = str(current.get("source", ""))
    candidate_source = str(candidate.get("source", ""))
    if candidate_source != current_source:
        return candidate_source > current_source
    return str(candidate.get("value", "")) < str(current.get("value", ""))


def build_primitive_text(word_id: int, tags: list[dict[str, Any]]) -> str:
    by_step: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    step_count = 1
    for tag in tags:
        field = str(tag.get("field", ""))
        if field == "step_count":
            try:
                step_count = max(step_count, int(str(tag.get("value", "1"))))
            except ValueError:
                step_count = max(step_count, 1)
            continue
        if field not in PRIMITIVE_FIELDS:
            continue
        raw_step = tag.get("step_index")
        step_index = int(raw_step) if raw_step is not None else 1
        current = by_step[step_index].get(field)
        if better_tag(current, tag):
            by_step[step_index][field] = tag
            step_count = max(step_count, step_index)

    parts: list[str] = []
    for step_index in range(1, step_count + 1):
        step_tags = by_step.get(step_index, {})
        hand_count = str(step_tags.get("hand_count", {}).get("value", "unknown"))
        values = default_step_fields(hand_count)
        for field, tag in step_tags.items():
            values[field] = str(tag.get("value", values[field]))
        step_text = " ".join(f"{field}={values[field]}" for field in PRIMITIVE_FIELDS)
        parts.append(f"step{step_index} {step_text}")
    if not parts:
        fallback = default_step_fields("unknown")
        parts.append("step1 " + " ".join(f"{field}={fallback[field]}" for field in PRIMITIVE_FIELDS))
    return " | ".join(parts)


def rebuild_table(config_path: str, output_db: str | None = None) -> None:
    cfg = load_config(config_path)
    output_path = Path(output_db).expanduser().resolve() if output_db else (cfg.output_dir / "hand_language_vocabulary.sqlite3")
    with open_db(cfg) as con:
        word_rows = con.execute(
            """
            SELECT id, word_base, action_description, retrieval_text
            FROM hand_word_table
            ORDER BY id
            """
        ).fetchall()
        tag_rows = con.execute(
            """
            SELECT word_id, field, value, confidence, source, step_index
            FROM word_primitive_final_tag_table
            ORDER BY word_id, step_index, field, confidence DESC
            """
        ).fetchall()

        tags_by_word: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for word_id, field, value, confidence, source, step_index in tag_rows:
            tags_by_word[int(word_id)].append(
                {
                    "field": field,
                    "value": value,
                    "confidence": confidence,
                    "source": source,
                    "step_index": step_index,
                }
            )

        out_rows = []
        for word_id, word_base, action_description, retrieval_text in word_rows:
            primitive_text = build_primitive_text(int(word_id), tags_by_word.get(int(word_id), []))
            out_rows.append((word_id, word_base, action_description, retrieval_text, primitive_text))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    out_con = sqlite3.connect(output_path)
    try:
        out_con.executescript(TABLE_SQL)
        out_con.executemany(
            """
            INSERT INTO hand_language_vocabulary
            (id, word_base, action_description, retrieval_text, primitive_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            out_rows,
        )
        out_con.commit()
    finally:
        out_con.close()

    log(f"[hlv] rebuilt hand_language_vocabulary rows={len(out_rows)} db={output_path}")


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    parser.add_argument("--output-db", default=None, help="Optional output SQLite path. Defaults to data/vocab_pipeline/hand_language_vocabulary.sqlite3.")
    args = parser.parse_args()
    rebuild_table(args.config, args.output_db)


if __name__ == "__main__":
    main()

