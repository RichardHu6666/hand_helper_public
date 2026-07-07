import argparse
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "vocab_pipeline" / "hand_language_vocabulary_lite.sqlite3"
DEFAULT_EXTRA = Path(__file__).resolve().with_name("sign_ui_extra_chars.txt")
DEFAULT_FONT = ROOT / "managed_components" / "lvgl__lvgl" / "scripts" / "built_in_font" / "SimSun.woff"
DEFAULT_OUTPUT = ROOT / "main" / "fonts" / "lv_font_sign_ui_14.c"


def read_extra_chars(path: Path) -> str:
    if not path.exists():
        return ""
    chars = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        chars.append(stripped)
    return "".join(chars)


def read_vocab_words(db_path: Path) -> list[str]:
    if not db_path.exists():
        raise FileNotFoundError(f"lite vocabulary db not found: {db_path}")
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT word_base FROM hand_language_vocabulary ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    return [row[0] for row in rows if row and row[0]]


def collect_chars(db_path: Path, extra_path: Path) -> str:
    words = read_vocab_words(db_path)
    raw = "".join(words) + read_extra_chars(extra_path)
    chars = sorted({ch for ch in raw if not ch.isspace() and ord(ch) > 0x7E})
    return "".join(chars)


def generated_codepoints(output_path: Path) -> set[int]:
    if not output_path.exists():
        return set()
    text = output_path.read_text(encoding="utf-8", errors="ignore")
    return {int(match, 16) for match in re.findall(r"U\+([0-9A-Fa-f]{4,6})", text)}


def check_font(output_path: Path, required_chars: str) -> int:
    codepoints = generated_codepoints(output_path)
    missing = [ch for ch in required_chars if ord(ch) not in codepoints]
    print(f"[font-check] output={output_path}")
    print(f"[font-check] required_non_ascii={len(required_chars)}")
    print(f"[font-check] generated_codepoints={len(codepoints)}")
    print(f"[font-check] missing_chars={len(missing)}")
    if missing:
        print("[font-check] missing=" + "".join(missing))
        return 1
    return 0


def normalize_lvgl_include(output_path: Path) -> None:
    text = output_path.read_text(encoding="utf-8", errors="ignore")
    conditional_include = (
        '#ifdef LV_LVGL_H_INCLUDE_SIMPLE\n'
        '#include "lvgl.h"\n'
        '#else\n'
        '#include "lvgl/lvgl.h"\n'
        '#endif\n'
    )
    if conditional_include in text:
        text = text.replace(conditional_include, '#include "lvgl.h"\n')
        output_path.write_text(text, encoding="utf-8", newline="\n")


def generate_font(args: argparse.Namespace, required_chars: str) -> None:
    font_conv = args.font_conv or shutil.which("lv_font_conv")
    if not font_conv:
        raise RuntimeError(
            "lv_font_conv was not found. Install it first, for example: npm install -g lv_font_conv"
        )

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        font_conv,
        "--no-compress",
        "--no-prefilter",
        "--bpp",
        str(args.bpp),
        "--size",
        str(args.size),
        "--font",
        str(Path(args.font).resolve()),
        "-r",
        "0x20-0x7E",
        "--symbols",
        required_chars,
        "--format",
        "lvgl",
        "-o",
        str(output),
        "--force-fast-kern-format",
    ]
    print(f"[font-gen] chars={len(required_chars)} size={args.size} bpp={args.bpp}")
    print(f"[font-gen] output={output}")
    subprocess.run(cmd, check=True)
    normalize_lvgl_include(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--extra", default=str(DEFAULT_EXTRA))
    parser.add_argument("--font", default=str(DEFAULT_FONT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--font-conv", default=None)
    parser.add_argument("--size", type=int, default=14)
    parser.add_argument("--bpp", type=int, default=4)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    required_chars = collect_chars(Path(args.db).resolve(), Path(args.extra).resolve())
    if args.check_only:
        return check_font(Path(args.output).resolve(), required_chars)

    generate_font(args, required_chars)
    return check_font(Path(args.output).resolve(), required_chars)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[font-gen] error: {exc}", file=sys.stderr)
        raise SystemExit(1)

