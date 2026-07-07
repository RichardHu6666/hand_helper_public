from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "tools" / "vocab_pipeline" / "config.local.toml"


@dataclass(frozen=True)
class PipelineConfig:
    epub_path: Path
    output_dir: Path
    sqlite_path: Path
    deepseek_api_key: str
    deepseek_base_url: str
    flash_model: str
    pro_model: str
    enable_llm_review: bool
    flash_max_concurrency: int
    pro_max_concurrency: int
    request_timeout_sec: int
    max_retries: int
    review_low_confidence_only: bool
    batch_size: int
    progress_every: int

    @property
    def raw_jsonl(self) -> Path:
        return self.output_dir / "sign_vocab_raw.jsonl"

    @property
    def rule_tags_jsonl(self) -> Path:
        return self.output_dir / "sign_vocab_rule_tags.jsonl"

    @property
    def llm_review_jsonl(self) -> Path:
        return self.output_dir / "sign_vocab_llm_review.jsonl"

    @property
    def final_tags_jsonl(self) -> Path:
        return self.output_dir / "sign_vocab_final_tags.jsonl"

    @property
    def parse_report_json(self) -> Path:
        return self.output_dir / "parse_report.json"

    @property
    def primitive_report_json(self) -> Path:
        return self.output_dir / "primitive_extract_report.json"

    @property
    def low_confidence_jsonl(self) -> Path:
        return self.output_dir / "low_confidence.jsonl"

    @property
    def llm_failed_jsonl(self) -> Path:
        return self.output_dir / "llm_failed.jsonl"

    @property
    def flash_uncertain_jsonl(self) -> Path:
        return self.output_dir / "llm_flash_uncertain.jsonl"


def _path_from_config(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _epub_path_from_config(value: str) -> Path:
    path = _path_from_config(value)
    if path.exists():
        return path
    candidates = sorted(REPO_ROOT.glob("*.epub"))
    if len(candidates) == 1:
        return candidates[0].resolve()
    return path


def load_config(config_path: str | os.PathLike[str] | None) -> PipelineConfig:
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    data = tomllib.loads(raw.decode("utf-8"))

    paths = data.get("paths", {})
    deepseek = data.get("deepseek", {})
    llm = data.get("llm", {})
    pipeline = data.get("pipeline", {})
    output_dir = _path_from_config(paths.get("output_dir", str(REPO_ROOT / "data" / "vocab_pipeline")))
    cfg = PipelineConfig(
        epub_path=_epub_path_from_config(paths.get("epub_path", str(REPO_ROOT / "鍥藉閫氱敤鎵嬭璇嶈〃.epub"))),
        output_dir=output_dir,
        sqlite_path=_path_from_config(paths.get("sqlite_path", str(output_dir / "sign_vocab.sqlite3"))),
        deepseek_api_key=str(deepseek.get("api_key", "")).strip(),
        deepseek_base_url=str(deepseek.get("base_url", "https://api.deepseek.com")).rstrip("/"),
        flash_model=str(deepseek.get("flash_model", "deepseek-v4-flash")),
        pro_model=str(deepseek.get("pro_model", "deepseek-v4-pro")),
        enable_llm_review=bool(llm.get("enable_llm_review", True)),
        flash_max_concurrency=int(llm.get("flash_max_concurrency", 32)),
        pro_max_concurrency=int(llm.get("pro_max_concurrency", 8)),
        request_timeout_sec=int(llm.get("request_timeout_sec", 60)),
        max_retries=int(llm.get("max_retries", 3)),
        review_low_confidence_only=bool(llm.get("review_low_confidence_only", True)),
        batch_size=int(pipeline.get("batch_size", 200)),
        progress_every=int(pipeline.get("progress_every", 50)),
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    cfg.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return cfg


def add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"Path to TOML config. Default: {DEFAULT_CONFIG}",
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid jsonl at {path}:{line_no}: {exc}") from exc
            rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def open_db(cfg: PipelineConfig) -> sqlite3.Connection:
    con = sqlite3.connect(cfg.sqlite_path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def log(message: str) -> None:
    print(message, flush=True)


def progress(prefix: str, done: int, total: int | None, start_time: float) -> None:
    elapsed = max(time.time() - start_time, 0.001)
    rate = done / elapsed
    if total:
        remain = max(total - done, 0)
        eta = remain / rate if rate > 0 else 0
        log(f"{prefix} {done}/{total} rate={rate:.1f}/s eta={eta:.1f}s")
    else:
        log(f"{prefix} {done} rate={rate:.1f}/s")


def ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main_guard(fn):
    def wrapper() -> None:
        ensure_utf8_stdout()
        try:
            fn()
        except KeyboardInterrupt:
            log("[abort] interrupted by user")
            raise SystemExit(130)
    return wrapper

