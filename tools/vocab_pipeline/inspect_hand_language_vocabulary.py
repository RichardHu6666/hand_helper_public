from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from common import add_config_arg, load_config, main_guard, open_db


def inspect_table(config_path: str, db_path: str | None = None) -> None:
    cfg = load_config(config_path)
    if db_path:
        con = sqlite3.connect(Path(db_path).expanduser().resolve())
    else:
        con = open_db(cfg)
    with con:
        table_row = con.execute(
            """
            SELECT name, sql
            FROM sqlite_master
            WHERE type='table' AND name='hand_language_vocabulary'
            """
        ).fetchone()
        if not table_row:
            print("table missing")
            return
        print(table_row[0])
        print(table_row[1])
        print("count", con.execute("SELECT COUNT(1) FROM hand_language_vocabulary").fetchone()[0])
        print("cols", con.execute("PRAGMA table_info('hand_language_vocabulary')").fetchall())
        print("samples")
        for row in con.execute(
            """
            SELECT id, word_base, primitive_text
            FROM hand_language_vocabulary
            ORDER BY id
            LIMIT 5
            """
        ):
            print(row)
        print("focus")
        for row in con.execute(
            """
            SELECT id, word_base, action_description, primitive_text
            FROM hand_language_vocabulary
            WHERE id IN (1, 2, 156, 331, 716)
            ORDER BY id
            """
        ):
            print("ID", row[0], row[1])
            print("ACTION", row[2])
            print("PRIM", row[3])
            print()


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    parser.add_argument("--db-path", default=None, help="Optional SQLite path. Defaults to the pipeline main DB.")
    args = parser.parse_args()
    inspect_table(args.config, args.db_path)


if __name__ == "__main__":
    main()

