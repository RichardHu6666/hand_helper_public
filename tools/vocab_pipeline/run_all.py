from __future__ import annotations

import argparse

from common import add_config_arg, load_config, log, main_guard
from extract_epub_words import parse_epub
from extract_primitive_tags_rule import run_rule_extract
from init_vocab_db import init_db
from merge_primitive_tags import run_merge
from review_primitives_with_deepseek import run_review
from validate_vocab_pipeline import run_validate


def cleanup_generated_outputs(cfg) -> None:
    paths = [
        cfg.raw_jsonl,
        cfg.rule_tags_jsonl,
        cfg.llm_review_jsonl,
        cfg.final_tags_jsonl,
        cfg.parse_report_json,
        cfg.primitive_report_json,
        cfg.low_confidence_jsonl,
        cfg.llm_failed_jsonl,
        cfg.flash_uncertain_jsonl,
        cfg.output_dir / "llm_pro_uncertain.jsonl",
    ]
    for path in paths:
        path.unlink(missing_ok=True)


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    parser.add_argument("--reset", action="store_true", help="Reset SQLite tables before running.")
    parser.add_argument("--skip-llm", action="store_true", help="Skip DeepSeek review even if configured.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.reset:
        cleanup_generated_outputs(cfg)
    log("[run_all] step 1/6 init db")
    init_db(args.config, reset=args.reset)
    log("[run_all] step 2/6 extract epub")
    parse_epub(args.config)
    log("[run_all] step 3/6 rule primitive extract")
    run_rule_extract(args.config)
    if args.skip_llm or not cfg.enable_llm_review or not cfg.deepseek_api_key:
        log("[run_all] step 4/6 llm review skipped")
    else:
        log("[run_all] step 4/6 deepseek flash review")
        run_review(args.config, "flash", None)
        log("[run_all] step 4b/6 deepseek pro review")
        run_review(args.config, "pro", str(cfg.flash_uncertain_jsonl))
    log("[run_all] step 5/6 merge tags")
    run_merge(args.config)
    log("[run_all] step 6/6 validate")
    run_validate(args.config)
    log("[run_all] done")


if __name__ == "__main__":
    main()

