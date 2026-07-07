from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any

from common import add_config_arg, load_config, log, main_guard, open_db, read_jsonl, write_jsonl


def tag_key(tag: dict[str, Any]) -> tuple[int, str, str, int | None]:
    return (
        int(tag["word_id"]),
        str(tag["field"]),
        str(tag["value"]),
        tag.get("step_index"),
    )


def as_final_tag(tag: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "word_id": int(tag["word_id"]),
        "word": tag.get("word", ""),
        "field": str(tag["field"]),
        "value": str(tag["value"]),
        "evidence": str(tag.get("evidence", "")),
        "confidence": round(float(tag.get("confidence", 0.0)), 3),
        "source": source,
        "step_index": tag.get("step_index"),
    }


def run_merge(config_path: str) -> None:
    cfg = load_config(config_path)
    rule_rows = read_jsonl(cfg.rule_tags_jsonl)
    review_rows = read_jsonl(cfg.llm_review_jsonl)
    log(f"[merge] rule_tags={len(rule_rows)} llm_reviews={len(review_rows)}")
    final: dict[tuple[int, str, str, int | None], dict[str, Any]] = {}
    word_by_id = {int(r.get("word_id", 0)): r.get("word", "") for r in rule_rows}
    for row in rule_rows:
        item = as_final_tag(row, "rule_v1")
        final[tag_key(item)] = item

    add_count = 0
    remove_count = 0
    for review_row in review_rows:
        if not review_row.get("ok"):
            continue
        review = review_row.get("review", {})
        word_id = int(review.get("word_id", review_row.get("word_id", 0)))
        word = review_row.get("word") or word_by_id.get(word_id, "")
        for tag in review.get("remove_tags", []) or []:
            key = (word_id, str(tag.get("field")), str(tag.get("value")), tag.get("step_index"))
            existing = final.get(key)
            if existing and existing["confidence"] < 0.75:
                final.pop(key, None)
                remove_count += 1
        for tag in review.get("add_tags", []) or []:
            item = {
                "word_id": word_id,
                "word": word,
                "field": tag.get("field"),
                "value": str(tag.get("value")),
                "evidence": tag.get("evidence", ""),
                "confidence": float(tag.get("confidence", 0.0)),
                "source": review_row.get("model", "deepseek"),
                "step_index": tag.get("step_index"),
            }
            key = tag_key(item)
            if key not in final or item["confidence"] > final[key]["confidence"]:
                final[key] = as_final_tag(item, item["source"])
                add_count += 1

    final_rows = sorted(final.values(), key=lambda r: (r["word_id"], str(r.get("step_index")), r["field"], r["value"]))
    write_jsonl(cfg.final_tags_jsonl, final_rows)
    with open_db(cfg) as con:
        con.execute("DELETE FROM word_primitive_final_tag_table")
        con.executemany(
            """
            INSERT INTO word_primitive_final_tag_table
            (word_id, field, value, evidence, confidence, source, step_index)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["word_id"],
                    r["field"],
                    r["value"],
                    r.get("evidence", ""),
                    r.get("confidence", 0.0),
                    r.get("source", ""),
                    r.get("step_index"),
                )
                for r in final_rows
            ],
        )
        con.commit()
    log(f"[merge] done final_tags={len(final_rows)} llm_added={add_count} removed={remove_count}")


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    args = parser.parse_args()
    run_merge(args.config)


if __name__ == "__main__":
    main()

