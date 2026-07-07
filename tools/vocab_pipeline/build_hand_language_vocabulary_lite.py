from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from common import add_config_arg, load_config, main_guard


DEFAULT_WORD_LIST = Path(__file__).resolve().with_name("lite_word_list.txt")
DEFAULT_ALIAS_MAP = Path(__file__).resolve().with_name("lite_alias_map.json")
DEFAULT_EXCLUDE_WORDS = Path(__file__).resolve().with_name("lite_exclude_words.txt")
DEFAULT_OUTPUT_DB = "hand_language_vocabulary_lite.sqlite3"

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


def load_word_list(path: Path) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if not word or word.startswith("#"):
            continue
        if word in seen:
            continue
        seen.add(word)
        words.append(word)
    return words


def load_alias_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_exclude_words(path: Path) -> set[str]:
    if not path.exists():
        return set()
    words: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        word = line.split("#", 1)[0].strip()
        if word:
            words.add(word)
    return words


def export_lite_db(config_path: str, word_list_path: str | None, alias_map_path: str | None, exclude_words_path: str | None, output_db: str | None) -> None:
    cfg = load_config(config_path)
    source_db = cfg.output_dir / "hand_language_vocabulary.sqlite3"
    if not source_db.exists():
        raise FileNotFoundError(f"source db not found: {source_db}")

    list_path = Path(word_list_path).expanduser().resolve() if word_list_path else DEFAULT_WORD_LIST
    if not list_path.exists():
        raise FileNotFoundError(f"word list not found: {list_path}")
    words = load_word_list(list_path)
    alias_map = load_alias_map(Path(alias_map_path).expanduser().resolve() if alias_map_path else DEFAULT_ALIAS_MAP)
    exclude_words = load_exclude_words(Path(exclude_words_path).expanduser().resolve() if exclude_words_path else DEFAULT_EXCLUDE_WORDS)
    filtered_words = [word for word in words if word not in exclude_words]
    excluded_requested = [word for word in words if word in exclude_words]
    output_path = Path(output_db).expanduser().resolve() if output_db else (cfg.output_dir / DEFAULT_OUTPUT_DB)

    src = sqlite3.connect(source_db)
    try:
        rows = src.execute(
            """
            SELECT id, word_base, action_description, retrieval_text, primitive_text
            FROM hand_language_vocabulary
            ORDER BY id
            """
        ).fetchall()
    finally:
        src.close()

    row_by_word = {row[1]: row for row in rows}
    selected_rows = []
    selected_words: set[str] = set()
    missing: list[str] = []
    alias_hit = 0
    for word in filtered_words:
        row = row_by_word.get(word)
        if row is None:
            alias = alias_map.get(word)
            if alias:
                row = row_by_word.get(alias)
                if row is not None:
                    alias_hit += 1
        if row is None:
            missing.append(word)
            continue
        if row[1] in selected_words:
            continue
        selected_words.add(row[1])
        selected_rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    out = sqlite3.connect(output_path)
    try:
        out.executescript(TABLE_SQL)
        out.executemany(
            """
            INSERT INTO hand_language_vocabulary
            (id, word_base, action_description, retrieval_text, primitive_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            selected_rows,
        )
        out.commit()
    finally:
        out.close()

    print(
        f"[lite] source_words={len(words)} excluded_words={len(excluded_requested)} "
        f"matched_rows={len(selected_rows)} alias_hit={alias_hit} missing={len(missing)}"
    )
    print(f"[lite] db={output_path}")
    if excluded_requested:
        print("[lite] excluded words:")
        for word in excluded_requested:
            print(word)
    if missing:
        print("[lite] missing words:")
        for word in missing:
            print(word)


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    parser.add_argument("--word-list", default=None, help=f"Optional word list path. Default: {DEFAULT_WORD_LIST}")
    parser.add_argument("--alias-map", default=None, help=f"Optional alias map path. Default: {DEFAULT_ALIAS_MAP}")
    parser.add_argument("--exclude-words", default=None, help=f"Optional exclude word list path. Default: {DEFAULT_EXCLUDE_WORDS}")
    parser.add_argument("--output-db", default=None, help=f"Optional output SQLite path. Default: data/vocab_pipeline/{DEFAULT_OUTPUT_DB}")
    args = parser.parse_args()
    export_lite_db(args.config, args.word_list, args.alias_map, args.exclude_words, args.output_db)


if __name__ == "__main__":
    main()

