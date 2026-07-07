from __future__ import annotations

import argparse
import json
import posixpath
import re
import time
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any

from common import add_config_arg, load_config, log, main_guard, open_db, progress, write_json, write_jsonl


TEXT_PREFIX = "OEBPS/Text/"


@dataclass
class WordEntry:
    word: str
    action_parts: list[str] = field(default_factory=list)
    pinyin_section: str = ""
    source_xhtml: str = ""
    source_anchor: str = ""
    image_refs: list[str] = field(default_factory=list)
    parse_status: str = "ok"
    parse_note: str = ""


class VocabXhtmlParser(HTMLParser):
    def __init__(self, source_xhtml: str, initial_section: str = ""):
        super().__init__()
        self.source_xhtml = source_xhtml
        self.entries: list[WordEntry] = []
        self.current_section = initial_section
        self.skipped_non_vocab_h2 = 0
        self.skipped_empty_description = 0
        self.current: WordEntry | None = None
        self.capture_tag: str | None = None
        self.capture_chunks: list[str] = []
        self.capture_attrs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"h1", "h2", "p"}:
            self.capture_tag = tag
            self.capture_chunks = []
            self.capture_attrs = {k: (v or "") for k, v in attrs}
            return
        if tag == "img" and self.current:
            attr = {k: (v or "") for k, v in attrs}
            src = attr.get("src", "")
            if src:
                resolved = posixpath.normpath(str(PurePosixPath(self.source_xhtml).parent / src))
                self.current.image_refs.append(resolved)

    def handle_data(self, data: str) -> None:
        if self.capture_tag:
            self.capture_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag != self.capture_tag:
            return
        text = clean_text("".join(self.capture_chunks))
        attrs = self.capture_attrs
        self.capture_tag = None
        self.capture_chunks = []
        self.capture_attrs = {}
        if not text:
            return
        if tag == "h1":
            self._finish_current()
            if is_vocab_section(text.strip()):
                self.current_section = text.strip()
        elif tag == "h2":
            self._finish_current()
            if not is_vocab_section(self.current_section):
                self.skipped_non_vocab_h2 += 1
                return
            self.current = WordEntry(
                word=text.strip(),
                pinyin_section=self.current_section,
                source_xhtml=self.source_xhtml,
                source_anchor=attrs.get("id", ""),
            )
        elif tag == "p" and self.current:
            self.current.action_parts.append(text)

    def close(self) -> None:
        super().close()
        self._finish_current()

    def _finish_current(self) -> None:
        if not self.current:
            return
        if self.current.word and self.current.action_parts:
            self.entries.append(self.current)
        else:
            self.skipped_empty_description += 1
        self.current = None


def clean_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


def is_vocab_section(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]", text.strip()))


def split_word(word: str) -> tuple[str, str]:
    variant_parts: list[str] = []
    base = word.strip()
    m = re.search(r"[鈶犫憽鈶⑩懀鈶も懃鈶︹懅鈶ㄢ澏鉂封澑鉂光澓鉂烩澕鉂解澗]$", base)
    if m:
        variant_parts.append(m.group(0))
        base = base[: m.start()].strip()
    m = re.search(r"锛?[^锛塢+)锛?", base)
    if m:
        variant_parts.append(m.group(1))
        base = base[: m.start()].strip()
    return base or word.strip(), "锛?.join(variant_parts)


def entry_to_row(entry_id: int, entry: WordEntry) -> dict[str, Any]:
    word_base, word_variant = split_word(entry.word)
    action_description = "\n".join(entry.action_parts).strip()
    return {
        "id": entry_id,
        "word": entry.word,
        "word_base": word_base,
        "word_variant": word_variant,
        "word_description": "",
        "action_description": action_description,
        "retrieval_text": f"璇嶇洰锛歿entry.word}銆傚姩浣滐細{action_description}",
        "pinyin_section": entry.pinyin_section,
        "source_xhtml": entry.source_xhtml,
        "source_anchor": entry.source_anchor,
        "image_refs": entry.image_refs,
        "parse_status": entry.parse_status,
        "parse_note": entry.parse_note,
    }


def parse_epub(config_path: str) -> None:
    cfg = load_config(config_path)
    if not cfg.epub_path.exists():
        raise FileNotFoundError(f"EPUB not found: {cfg.epub_path}")
    log(f"[extract] epub={cfg.epub_path}")
    start = time.time()
    rows: list[dict[str, Any]] = []
    h2_total = 0
    skipped_non_vocab_h2 = 0
    skipped_empty_description = 0
    current_section = ""
    with zipfile.ZipFile(cfg.epub_path) as z:
        xhtml_files = sorted(
            n for n in z.namelist() if n.startswith(TEXT_PREFIX) and n.lower().endswith(".xhtml")
        )
        log(f"[extract] xhtml files: {len(xhtml_files)}")
        for idx, name in enumerate(xhtml_files, 1):
            data = z.read(name).decode("utf-8", errors="replace")
            h2_total += len(re.findall(r"<h2\b", data, flags=re.IGNORECASE))
            parser = VocabXhtmlParser(name, current_section)
            parser.feed(data)
            parser.close()
            current_section = parser.current_section
            skipped_non_vocab_h2 += parser.skipped_non_vocab_h2
            skipped_empty_description += parser.skipped_empty_description
            for entry in parser.entries:
                rows.append(entry_to_row(len(rows) + 1, entry))
            if idx == 1 or idx % 10 == 0 or idx == len(xhtml_files):
                progress("[extract] processed", idx, len(xhtml_files), start)
                log(f"[extract] words={len(rows)}")

    count = write_jsonl(cfg.raw_jsonl, rows)
    log(f"[extract] wrote raw jsonl rows={count} path={cfg.raw_jsonl}")
    with open_db(cfg) as con:
        con.execute("DELETE FROM hand_word_table")
        con.executemany(
            """
            INSERT INTO hand_word_table (
                id, word, word_base, word_variant, word_description, action_description,
                retrieval_text, pinyin_section, source_xhtml, source_anchor, image_refs_json,
                parse_status, parse_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["id"],
                    r["word"],
                    r["word_base"],
                    r["word_variant"],
                    r["word_description"],
                    r["action_description"],
                    r["retrieval_text"],
                    r["pinyin_section"],
                    r["source_xhtml"],
                    r["source_anchor"],
                    json.dumps(r["image_refs"], ensure_ascii=False),
                    r["parse_status"],
                    r["parse_note"],
                )
                for r in rows
            ],
        )
        con.commit()
    empty = sum(1 for r in rows if not r["action_description"].strip())
    duplicates = len(rows) - len({(r["word"], r["action_description"]) for r in rows})
    report = {
        "epub_path": str(cfg.epub_path),
        "xhtml_count": len(xhtml_files),
        "h2_count": h2_total,
        "word_count": len(rows),
        "skipped_h2_without_description": h2_total - len(rows),
        "skipped_non_vocab_h2": skipped_non_vocab_h2,
        "skipped_empty_description_h2": skipped_empty_description,
        "empty_description_count": empty,
        "duplicate_word_entries": duplicates,
        "parse_status_counts": {"ok": len(rows)},
        "output_jsonl": str(cfg.raw_jsonl),
        "sqlite_path": str(cfg.sqlite_path),
    }
    write_json(cfg.parse_report_json, report)
    log(f"[extract] done words={len(rows)} empty={empty} duplicates={duplicates}")


@main_guard
def main() -> None:
    parser = argparse.ArgumentParser()
    add_config_arg(parser)
    args = parser.parse_args()
    parse_epub(args.config)


if __name__ == "__main__":
    main()

