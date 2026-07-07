import sqlite3

from app.storage import LITE_DB_PATH, LITE_TABLE, load_lite_vocab


def test_lite_vocab_loads() -> None:
    entries = load_lite_vocab()
    assert len(entries) == 109
    assert all(entry.steps and entry.steps[0]["step_index"] == 1 for entry in entries)


def test_lite_vocab_schema() -> None:
    with sqlite3.connect(LITE_DB_PATH) as conn:
        columns = conn.execute(f"pragma table_info({LITE_TABLE})").fetchall()
    assert [column[1] for column in columns] == [
        "id",
        "word_base",
        "action_description",
        "retrieval_text",
        "primitive_text",
    ]

