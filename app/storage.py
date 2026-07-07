from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.seed_data import SEED_WORDS


PROJECT_ROOT = Path("/root/sign_cloud_v1")
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "hand_words.sqlite3"
LITE_DB_PATH = DATA_DIR / "hand_language_vocabulary_lite.sqlite3"
LITE_TABLE = "hand_language_vocabulary"
SEED_JSON_PATH = DATA_DIR / "vocab_seed.json"


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hand_word_table (
    id INTEGER PRIMARY KEY,
    word TEXT NOT NULL,
    word_description TEXT NOT NULL DEFAULT '',
    action_description TEXT NOT NULL DEFAULT '',
    embedded_action_description TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_seed_json() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SEED_JSON_PATH.exists():
        SEED_JSON_PATH.write_text(
            json.dumps(SEED_WORDS, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def load_seed_words() -> list[dict[str, Any]]:
    ensure_seed_json()
    return json.loads(SEED_JSON_PATH.read_text(encoding="utf-8"))


def init_db() -> None:
    ensure_seed_json()
    with get_connection() as conn:
        conn.execute(CREATE_TABLE_SQL)
        row = conn.execute("SELECT COUNT(*) AS count FROM hand_word_table").fetchone()
        if int(row["count"]) == 0:
            for item in load_seed_words():
                conn.execute(
                    """
                    INSERT INTO hand_word_table (
                        id, word, word_description, action_description, embedded_action_description
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        item["id"],
                        item["word"],
                        item.get("word_description", ""),
                        item.get("action_description", ""),
                        item.get("embedded_action_description"),
                    ),
                )
        conn.commit()


def list_words() -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, word, word_description, action_description, embedded_action_description
            FROM hand_word_table
            ORDER BY id ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def vocab_size() -> int:
    init_db()
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM hand_word_table").fetchone()
    return int(row["count"])


@dataclass(frozen=True)
class LiteVocabEntry:
    id: int
    word_base: str
    action_description: str
    retrieval_text: str
    primitive_text: str
    steps: list[dict[str, Any]]


_lite_entries: list[LiteVocabEntry] = []
_lite_loaded_at: str | None = None
_lite_error: str | None = None


def load_lite_vocab() -> list[LiteVocabEntry]:
    from app.primitive_text_parser import parse_primitive_text

    global _lite_entries, _lite_loaded_at, _lite_error
    try:
        with sqlite3.connect(LITE_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT id, word_base, action_description, retrieval_text, primitive_text
                FROM {LITE_TABLE}
                ORDER BY id ASC
                """
            ).fetchall()
        _lite_entries = [
            LiteVocabEntry(
                id=int(row["id"]),
                word_base=str(row["word_base"]),
                action_description=str(row["action_description"]),
                retrieval_text=str(row["retrieval_text"]),
                primitive_text=str(row["primitive_text"]),
                steps=parse_primitive_text(str(row["primitive_text"])),
            )
            for row in rows
        ]
        _lite_loaded_at = datetime.now(timezone.utc).isoformat()
        _lite_error = None
    except Exception as exc:  # surfaced by /health
        _lite_entries = []
        _lite_loaded_at = None
        _lite_error = str(exc)
    return _lite_entries


def lite_vocab_entries() -> list[LiteVocabEntry]:
    if not _lite_entries and _lite_error is None:
        load_lite_vocab()
    return _lite_entries


def lite_vocab_status() -> dict[str, Any]:
    return {
        "path": str(LITE_DB_PATH),
        "table": LITE_TABLE,
        "rows": len(_lite_entries),
        "loaded": bool(_lite_entries),
        "loaded_at": _lite_loaded_at,
        "error": _lite_error,
    }

