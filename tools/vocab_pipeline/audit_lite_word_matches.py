from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from common import add_config_arg, load_config, main_guard


DEFAULT_WORD_LIST = Path(__file__).resolve().with_name("lite_word_list.txt")
DEFAULT_ALIAS_MAP = Path(__file__).resolve().with_name("lite_alias_map.json")


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


def candidate_words(all_words: list[str], target: str) -> list[str]:
    return [word for word in all_words if target in word or word in target][:12]


def audit(config_path: str, word_list_path: str | None, alias_map_path: str | None, output_path: str | None = None) -> None:
    cfg = load_config(config_path)
    db_path = cfg.output_dir / "hand_language_vocabulary.sqlite3"
    if not db_path.exists():
        raise FileNotFoundError(f"source db not found: {db_path}")

    word_list = load_word_list(Path(word_list_path).expanduser().resolve() if word_list_path else DEFAULT_WORD_LIST)
    alias_map = load_alias_map(Path(alias_map_path).expanduser().resolve() if alias_map_path else DEFAULT_ALIAS_MAP)

    con = sqlite3.connect(db_path)
    try:
        db_words = [row[0] for row in con.execute("SELECT word_base FROM hand_language_vocabulary ORDER BY word_base")]
    finally:
        con.close()

    db_word_set = set(db_words)
    matched = 0
    alias_hit = 0
    missing: list[tuple[str, str | None, list[str]]] = []
    for word in word_list:
        if word in db_word_set:
            matched += 1
            continue
        alias = alias_map.get(word)
        if alias and alias in db_word_set:
            matched += 1
            alias_hit += 1
            continue
        missing.append((word, alias, candidate_words(db_words, word)))

    lines = [f"[audit] source_words={len(word_list)} matched={matched} alias_hit={alias_hit} missing={len(missing)}"]
    for word, alias, candidates in missing:
        lines.append(f"{word}\talias={alias or '-'}\tcandidates={','.join(candidates) if candidates else '-'}")
    text = "\n".join(lines) + "\n"
    if output_path:
        out = Path(output_path).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    parser.add_argument("--word-list", default=None)
    parser.add_argument("--alias-map", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    audit(args.config, args.word_list, args.alias_map, args.output)


if __name__ == "__main__":
    main()

