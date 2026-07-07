#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embedding_store import EmbeddingStore, make_embedder


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--no-hash-fallback", action="store_true")
    args = parser.parse_args()
    start = time.time()
    store = EmbeddingStore(model=args.model)
    embedder = make_embedder(args.model, device=args.device, allow_hash_fallback=not args.no_hash_fallback)
    meta = store.build(embedder=embedder, device=args.device)
    elapsed = time.time() - start
    print(f"vocab_rows={meta['vocab_rows']}")
    print(f"embedding_dim={meta.get('embedding_dim')}")
    print(f"cache_path={store.cache_path}")
    print(f"elapsed_sec={elapsed:.2f}")
    print(f"model_used={meta['model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

