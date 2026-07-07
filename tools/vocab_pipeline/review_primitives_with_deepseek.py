from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import (
    add_config_arg,
    append_jsonl,
    load_config,
    log,
    main_guard,
    open_db,
    progress,
    read_jsonl,
    write_jsonl,
)


ALLOWED_FIELDS = {
    "hand_count",
    "dominant_shape",
    "nondominant_shape",
    "movement",
    "location",
    "bimanual_relation",
    "body_anchor_hint",
    "step_count",
}

ALLOWED_VALUES = {
    "hand_count": {"0", "1", "2", "unknown"},
    "dominant_shape": {"one", "two", "three", "four", "five", "like", "ok", "call", "dislike", "no_gesture", "no_hand", "unknown"},
    "nondominant_shape": {"one", "two", "three", "four", "five", "like", "ok", "call", "dislike", "no_gesture", "no_hand", "unknown"},
    "movement": {"hold", "left_right", "up_down", "toward_away", "open_close", "repeat", "unknown"},
    "location": {"signer_left_upper", "signer_left_lower", "signer_right_upper", "signer_right_lower", "signer_center_upper", "signer_center_middle", "signer_center_lower", "unknown"},
    "bimanual_relation": {"single_hand", "dual_hand", "same_shape", "different_shape", "unknown"},
    "body_anchor_hint": {"head", "face", "eye", "ear", "mouth", "chin", "neck", "shoulder", "chest", "abdomen", "waist", "hand", "neutral_space", "unknown"},
    "step_count": {str(i) for i in range(0, 20)},
}


def build_prompt(item: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "浣犳槸涓浗鎵嬭鍔ㄤ綔鎻忚堪鐨勭粨鏋勫寲瀹℃煡鍣ㄣ€?
        "浣犲繀椤诲彧杈撳嚭涓€涓悎娉?JSON object锛屼笉瑕佽緭鍑?Markdown 鎴栬嚜鐒惰瑷€銆?
        "浠诲姟鏄鏌ヨ鍒欐娊鍙栫殑鍔ㄤ綔鍩哄厓鏍囩锛屽苟浠?json patch 褰㈠紡琛ュ厖鎴栨彁绀洪棶棰樸€?
        "涓嶈鍑┖鎵╁睍鏋氫妇锛涘彧鑳戒娇鐢ㄧ敤鎴风粰鍑虹殑 allowed_fields 鍜?allowed_values銆?
    )
    user_payload = {
        "instruction": "Return json only. Review rule_tags and suggest add/remove primitive tags.",
        "output_schema": {
            "word_id": 123,
            "status": "patch_suggested",
            "add_tags": [
                {
                    "field": "movement",
                    "value": "repeat",
                    "evidence": "涓や笅",
                    "confidence": 0.72,
                    "reason": "鎻忚堪涓嚭鐜颁袱涓嬶紝琛ㄧず閲嶅鍔ㄤ綔",
                }
            ],
            "remove_tags": [],
            "warnings": ["location is ambiguous; keep unknown"],
            "review_confidence": 0.78,
        },
        "allowed_status": ["ok", "patch_suggested", "uncertain", "invalid_input"],
        "allowed_fields": sorted(ALLOWED_FIELDS),
        "allowed_values": {k: sorted(v) for k, v in ALLOWED_VALUES.items()},
        "item": {
            "word_id": item.get("word_id"),
            "word": item.get("word"),
            "action_description": item.get("action_description"),
            "rule_tags": item.get("rule_tags", []),
            "rule_warnings": item.get("warnings", []),
        },
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def call_deepseek(cfg, model: str, item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": build_prompt(item),
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{cfg.deepseek_base_url}/chat/completions"
    last_error = ""
    for attempt in range(1, cfg.max_retries + 1):
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Authorization": f"Bearer {cfg.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=cfg.request_timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            content = data["choices"][0]["message"].get("content") or ""
            if not content.strip():
                raise ValueError("empty content")
            review = parse_json_content(content)
            validate_review(item, review)
            return {
                "word_id": item["word_id"],
                "word": item.get("word", ""),
                "model": model,
                "ok": True,
                "review": review,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            KeyError,
            ValueError,
            http.client.IncompleteRead,
            ConnectionError,
            OSError,
        ) as exc:
            last_error = repr(exc)
            time.sleep(min(2 ** attempt, 10))
    return {
        "word_id": item.get("word_id"),
        "word": item.get("word", ""),
        "model": model,
        "ok": False,
        "error": last_error,
        "input_item": item,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("content json is not object")
    return obj


def validate_review(item: dict[str, Any], review: dict[str, Any]) -> None:
    if not isinstance(review, dict):
        raise ValueError("review is not object")
    if review.get("word_id") != item.get("word_id"):
        raise ValueError("word_id mismatch")
    if review.get("status") not in {"ok", "patch_suggested", "uncertain", "invalid_input"}:
        raise ValueError("invalid status")
    for key in ("add_tags", "remove_tags"):
        if not isinstance(review.get(key, []), list):
            raise ValueError(f"{key} must be list")
        for tag in review.get(key, []):
            field = tag.get("field")
            value = str(tag.get("value", ""))
            if field not in ALLOWED_FIELDS:
                raise ValueError(f"invalid field: {field}")
            if value not in ALLOWED_VALUES.get(field, set()):
                raise ValueError(f"invalid value for {field}: {value}")
            conf = tag.get("confidence", 0.0)
            if not isinstance(conf, (int, float)) or conf < 0.0 or conf > 1.0:
                raise ValueError("confidence out of range")


def select_input(cfg, input_path: str | None) -> list[dict[str, Any]]:
    path = Path(input_path) if input_path else cfg.low_confidence_jsonl
    rows = read_jsonl(path)
    normalized: list[dict[str, Any]] = []
    seen_word_ids: set[int] = set()
    for row in rows:
        item: dict[str, Any] | None = None
        if isinstance(row.get("input_item"), dict):
            item = row["input_item"]
        elif "action_description" in row and "rule_tags" in row:
            item = row
        if not item:
            continue
        word_id = int(item.get("word_id", 0))
        if word_id in seen_word_ids:
            continue
        seen_word_ids.add(word_id)
        normalized.append(item)
    return normalized


def write_reviews_to_db(cfg, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with open_db(cfg) as con:
        con.executemany(
            """
            INSERT INTO word_primitive_llm_review_table
            (word_id, model, status, review_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    r["word_id"],
                    r["model"],
                    r["review"].get("status", "ok") if r.get("ok") else "failed",
                    json.dumps(r.get("review", {"error": r.get("error", "")}), ensure_ascii=False),
                    r.get("created_at", ""),
                )
                for r in rows
            ],
        )
        con.commit()


def run_review(
    config_path: str,
    model_kind: str,
    input_path: str | None,
    concurrency_override: int | None = None,
    progress_every_override: int | None = None,
) -> None:
    cfg = load_config(config_path)
    if not cfg.enable_llm_review:
        log("[llm] skipped: enable_llm_review=false")
        return
    if not cfg.deepseek_api_key:
        log("[llm] skipped: deepseek api_key is empty in config.local.toml")
        return
    model = cfg.flash_model if model_kind == "flash" else cfg.pro_model
    concurrency = concurrency_override or (cfg.flash_max_concurrency if model_kind == "flash" else cfg.pro_max_concurrency)
    progress_every = progress_every_override or cfg.progress_every
    rows = select_input(cfg, input_path)
    if not rows:
        log("[llm] no input rows")
        return
    out_path = cfg.llm_review_jsonl
    if model_kind == "flash":
        uncertain_path = cfg.flash_uncertain_jsonl
    else:
        uncertain_path = cfg.output_dir / "llm_pro_uncertain.jsonl"
    cfg.llm_failed_jsonl.unlink(missing_ok=True)
    uncertain_path.unlink(missing_ok=True)
    log(f"[llm:{model_kind}] queue={len(rows)} model={model} concurrency={concurrency}")
    start = time.time()
    ok_rows: list[dict[str, Any]] = []
    failed = 0
    uncertain: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        future_to_row = {pool.submit(call_deepseek, cfg, model, row): row for row in rows}
        futures = list(future_to_row)
        for idx, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                result = fut.result()
            except Exception as exc:
                input_item = future_to_row.get(fut)
                result = {
                    "word_id": input_item.get("word_id") if input_item else None,
                    "word": input_item.get("word", "") if input_item else "",
                    "model": model,
                    "ok": False,
                    "error": f"worker_crash: {exc!r}",
                    "input_item": input_item,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            if result.get("ok"):
                ok_rows.append(result)
                append_jsonl(out_path, result)
                if result["review"].get("status") == "uncertain":
                    uncertain.append(result)
            else:
                failed += 1
                append_jsonl(cfg.llm_failed_jsonl, result)
            if idx == 1 or idx % progress_every == 0 or idx == len(futures):
                progress(f"[llm:{model_kind}] done", idx, len(futures), start)
                log(f"[llm:{model_kind}] ok={len(ok_rows)} failed={failed} uncertain={len(uncertain)}")
    write_reviews_to_db(cfg, ok_rows)
    write_jsonl(uncertain_path, uncertain)
    log(f"[llm:{model_kind}] done ok={len(ok_rows)} failed={failed} uncertain={len(uncertain)}")


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    parser.add_argument("--model", choices=["flash", "pro"], default="flash")
    parser.add_argument("--input", default=None, help="Optional JSONL input. Defaults to low_confidence.jsonl.")
    parser.add_argument("--concurrency", type=int, default=None, help="Optional worker override for this run.")
    parser.add_argument("--progress-every", type=int, default=None, help="Optional progress print interval override.")
    args = parser.parse_args()
    run_review(args.config, args.model, args.input, args.concurrency, args.progress_every)


if __name__ == "__main__":
    main()

