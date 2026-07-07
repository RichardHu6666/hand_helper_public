#!/usr/bin/env python
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.storage import DB_PATH, init_db, vocab_size  # noqa: E402


def main() -> None:
    init_db()
    print(f"Initialized {DB_PATH} with {vocab_size()} words.")


if __name__ == "__main__":
    main()

