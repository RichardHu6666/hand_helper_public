from __future__ import annotations

import argparse

from common import add_config_arg, load_config, log, main_guard, open_db


SCHEMA = """
CREATE TABLE IF NOT EXISTS hand_word_table (
    id INTEGER PRIMARY KEY,
    word TEXT NOT NULL,
    word_base TEXT NOT NULL DEFAULT '',
    word_variant TEXT NOT NULL DEFAULT '',
    word_description TEXT NOT NULL DEFAULT '',
    action_description TEXT NOT NULL,
    retrieval_text TEXT NOT NULL DEFAULT '',
    pinyin_section TEXT NOT NULL DEFAULT '',
    source_xhtml TEXT NOT NULL DEFAULT '',
    source_anchor TEXT NOT NULL DEFAULT '',
    image_refs_json TEXT NOT NULL DEFAULT '[]',
    parse_status TEXT NOT NULL DEFAULT 'ok',
    parse_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS word_primitive_tag_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    method TEXT NOT NULL DEFAULT 'rule_v1',
    step_index INTEGER,
    FOREIGN KEY(word_id) REFERENCES hand_word_table(id)
);

CREATE TABLE IF NOT EXISTS word_primitive_llm_review_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    review_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(word_id) REFERENCES hand_word_table(id)
);

CREATE TABLE IF NOT EXISTS word_primitive_final_tag_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    source TEXT NOT NULL,
    step_index INTEGER,
    FOREIGN KEY(word_id) REFERENCES hand_word_table(id)
);

CREATE INDEX IF NOT EXISTS idx_hand_word_word ON hand_word_table(word);
CREATE INDEX IF NOT EXISTS idx_hand_word_base ON hand_word_table(word_base);
CREATE INDEX IF NOT EXISTS idx_rule_tag_word ON word_primitive_tag_table(word_id);
CREATE INDEX IF NOT EXISTS idx_rule_tag_field_value ON word_primitive_tag_table(field, value);
CREATE INDEX IF NOT EXISTS idx_final_tag_word ON word_primitive_final_tag_table(word_id);
CREATE INDEX IF NOT EXISTS idx_final_tag_field_value ON word_primitive_final_tag_table(field, value);
"""


def init_db(config_path: str, reset: bool = False) -> None:
    cfg = load_config(config_path)
    log(f"[db] sqlite={cfg.sqlite_path}")
    with open_db(cfg) as con:
        if reset:
            log("[db] reset existing tables")
            con.executescript(
                """
                DROP TABLE IF EXISTS word_primitive_final_tag_table;
                DROP TABLE IF EXISTS word_primitive_llm_review_table;
                DROP TABLE IF EXISTS word_primitive_tag_table;
                DROP TABLE IF EXISTS hand_word_table;
                """
            )
        con.executescript(SCHEMA)
        con.commit()
    log("[db] schema ready")


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all pipeline tables.")
    args = parser.parse_args()
    init_db(args.config, reset=args.reset)


if __name__ == "__main__":
    main()

