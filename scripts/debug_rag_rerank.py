#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embedding_store import EmbeddingStore
from app.rag_reranker import RAGReranker
from app.schemas import StreamFrameRequest
from app.stream_decoder import StreamDecoder
from app.stream_models import StreamFrame


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    store = EmbeddingStore()
    if not store.load():
        print(f"embedding cache not loaded: {store.error}")
        print("run: python scripts/build_embeddings.py --model BAAI/bge-small-zh-v1.5 --device cpu")
    decoder = StreamDecoder(reranker=RAGReranker(store))
    responses = []
    for item in load_jsonl(Path(args.fixture)):
        req = StreamFrameRequest(session_id=item["session_id"], timestamp=item["timestamp"], primitive=item["primitive"], debug=True)
        responses.append(decoder.decode(StreamFrame.from_request(req), include_debug=True))
    debug = (responses[-1].get("debug") or {}) if responses else {}
    primitive = debug.get("primitive_top_candidates") or []
    reranked = debug.get("reranked_top_candidates") or primitive
    print("Primitive top5:")
    for idx, item in enumerate(primitive[: args.top_k], start=1):
        print(f"{idx}. {item['word_base']} primitive={item.get('primitive_score', item.get('score'))}")
    print("\nReranked top5:")
    for idx, item in enumerate(reranked[: args.top_k], start=1):
        print(f"{idx}. {item['word_base']} primitive={item.get('primitive_score')} rag={item.get('rag_score')} final={item.get('final_score', item.get('score'))}")
    print(f"\nrerank={debug.get('rerank')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

