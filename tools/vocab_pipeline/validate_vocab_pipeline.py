from __future__ import annotations

import argparse
import json
from collections import Counter

from common import add_config_arg, load_config, log, main_guard, open_db, read_jsonl, write_json


def count_db(con, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def run_validate(config_path: str) -> None:
    cfg = load_config(config_path)
    raw = read_jsonl(cfg.raw_jsonl)
    rule_tags = read_jsonl(cfg.rule_tags_jsonl)
    final_tags = read_jsonl(cfg.final_tags_jsonl)
    low_conf = read_jsonl(cfg.low_confidence_jsonl)
    llm_failed = read_jsonl(cfg.llm_failed_jsonl)
    parse_report = {}
    if cfg.parse_report_json.exists():
        parse_report = json.loads(cfg.parse_report_json.read_text(encoding="utf-8"))
    log(f"[validate] raw_words={len(raw)} rule_tags={len(rule_tags)} final_tags={len(final_tags)}")
    empty_desc = sum(1 for r in raw if not str(r.get("action_description", "")).strip())
    duplicate_entries = len(raw) - len({(r.get("word"), r.get("action_description")) for r in raw})
    rule_tagged_words = len({r["word_id"] for r in rule_tags})
    final_tagged_words = len({r["word_id"] for r in final_tags})
    final_field_counter = Counter(r["field"] for r in final_tags)
    final_value_counter = Counter((r["field"], r["value"]) for r in final_tags)
    with open_db(cfg) as con:
        db_words = count_db(con, "select count(*) from hand_word_table")
        db_rule = count_db(con, "select count(*) from word_primitive_tag_table")
        db_final = count_db(con, "select count(*) from word_primitive_final_tag_table")
    severe: list[str] = []
    h2_count = int(parse_report.get("h2_count") or 0)
    if len(raw) < 4000:
        severe.append("parsed word count below 4000")
    if h2_count and len(raw) / h2_count < 0.95:
        severe.append("parsed h2 coverage below 95%")
    if raw and empty_desc / len(raw) > 0.05:
        severe.append("empty action descriptions exceed 5%")
    if db_words != len(raw):
        severe.append("sqlite hand_word_table count mismatch")
    if final_tags and db_final != len(final_tags):
        severe.append("sqlite final tag count mismatch")
    report = {
        "word_count": len(raw),
        "h2_count": h2_count,
        "h2_coverage": (len(raw) / h2_count) if h2_count else None,
        "sqlite_word_count": db_words,
        "empty_action_description": empty_desc,
        "duplicated_word_entries": duplicate_entries,
        "rule_tag_count": len(rule_tags),
        "sqlite_rule_tag_count": db_rule,
        "rule_tagged_words": rule_tagged_words,
        "final_tag_count": len(final_tags),
        "sqlite_final_tag_count": db_final,
        "final_tagged_words": final_tagged_words,
        "low_confidence_count": len(low_conf),
        "llm_failed_count": len(llm_failed),
        "field_coverage": {
            field: len({r["word_id"] for r in final_tags if r["field"] == field}) / max(len(raw), 1)
            for field in sorted(final_field_counter)
        },
        "top_final_values": [
            {"field": k[0], "value": k[1], "count": v}
            for k, v in final_value_counter.most_common(40)
        ],
        "severe_failures": severe,
        "sqlite_ok": not severe,
        "jsonl_ok": True,
    }
    write_json(cfg.primitive_report_json, report)
    log(f"[validate] words={len(raw)}")
    log(f"[validate] empty_action_description={empty_desc}")
    log(f"[validate] duplicated_word_entries={duplicate_entries}")
    log(f"[validate] rule_tagged_words={rule_tagged_words}")
    log(f"[validate] final_tagged_words={final_tagged_words}")
    log(f"[validate] low_confidence={len(low_conf)} llm_failed={len(llm_failed)}")
    log(f"[validate] sqlite_words={db_words} sqlite_rule_tags={db_rule} sqlite_final_tags={db_final}")
    if severe:
        log("[validate] severe_failures=" + "; ".join(severe))
    else:
        log("[validate] sqlite_ok=true jsonl_ok=true")


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    args = parser.parse_args()
    run_validate(args.config)


if __name__ == "__main__":
    main()

