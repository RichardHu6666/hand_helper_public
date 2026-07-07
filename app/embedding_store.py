from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.runtime_config import CONFIG
from app.storage import LITE_DB_PATH, lite_vocab_entries, load_lite_vocab


class Embedder(Protocol):
    model_name: str

    def encode(self, texts: list[str]) -> list[list[float]]:
        ...


class HashingEmbedder:
    def __init__(self, model_name: str = "hashing-local-v1", dim: int = 128) -> None:
        self.model_name = model_name
        self.dim = dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = [ch for ch in text if not ch.isspace()]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, device: str = "cpu") -> None:
        system_site = Path("/usr/local/lib/python3.12/dist-packages")
        if system_site.exists() and str(system_site) not in sys.path:
            sys.path.append(str(system_site))
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device=device)

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return [list(map(float, row)) for row in vectors]


def make_embedder(model_name: str, device: str = "cpu", allow_hash_fallback: bool = True) -> Embedder:
    try:
        return SentenceTransformerEmbedder(model_name, device=device)
    except Exception:
        if not allow_hash_fallback:
            raise
        return HashingEmbedder(model_name=f"{model_name} (hash-fallback)")


def embedding_text(entry: Any) -> str:
    return "\n".join(
        [
            f"璇嶆潯锛歿entry.word_base}",
            f"鍔ㄤ綔鎻忚堪锛歿entry.action_description}",
            f"妫€绱㈡枃鏈細{entry.retrieval_text}",
            f"鍔ㄤ綔鍩哄厓锛歿entry.primitive_text}",
        ]
    )


def text_hash(texts: list[str]) -> str:
    h = hashlib.sha256()
    for text in texts:
        h.update(text.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def write_npy(path: Path, matrix: list[list[float]]) -> None:
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    header = f"{{'descr': '<f4', 'fortran_order': False, 'shape': ({rows}, {cols}), }}"
    header_bytes = header.encode("latin1")
    padding = 16 - ((10 + len(header_bytes) + 1) % 16)
    full_header = header_bytes + b" " * padding + b"\n"
    with path.open("wb") as f:
        f.write(b"\x93NUMPY")
        f.write(bytes([1, 0]))
        f.write(struct.pack("<H", len(full_header)))
        f.write(full_header)
        for row in matrix:
            f.write(struct.pack("<" + "f" * cols, *row))


def read_npy(path: Path) -> list[list[float]]:
    data = path.read_bytes()
    if not data.startswith(b"\x93NUMPY"):
        raise ValueError("not an npy file")
    major = data[6]
    if major != 1:
        raise ValueError("only npy v1 supported by fallback loader")
    header_len = struct.unpack("<H", data[8:10])[0]
    header = data[10 : 10 + header_len].decode("latin1")
    shape_text = header.split("'shape':", 1)[1].split(")", 1)[0].strip().lstrip("(")
    rows, cols = [int(part.strip()) for part in shape_text.split(",")[:2]]
    offset = 10 + header_len
    values = struct.unpack("<" + "f" * rows * cols, data[offset : offset + rows * cols * 4])
    return [list(values[i * cols : (i + 1) * cols]) for i in range(rows)]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    an = math.sqrt(sum(x * x for x in a)) or 1.0
    bn = math.sqrt(sum(y * y for y in b)) or 1.0
    return max(0.0, min(1.0, dot / (an * bn)))


@dataclass
class EmbeddingStore:
    model: str = CONFIG.embed_model
    cache_path: Path = Path(CONFIG.embed_cache_path)
    meta_path: Path = Path(CONFIG.embed_meta_path)
    vectors: list[list[float]] | None = None
    meta: dict[str, Any] | None = None
    error: str | None = None

    def current_meta(self) -> dict[str, Any]:
        entries = load_lite_vocab()
        texts = [embedding_text(entry) for entry in entries]
        return {
            "model": self.model,
            "vocab_path": str(LITE_DB_PATH),
            "vocab_rows": len(entries),
            "entry_ids": [entry.id for entry in entries],
            "text_hash": text_hash(texts),
        }

    def build(self, embedder: Embedder | None = None, device: str = "cpu") -> dict[str, Any]:
        entries = load_lite_vocab()
        texts = [embedding_text(entry) for entry in entries]
        embedder = embedder or make_embedder(self.model, device=device)
        vectors = embedder.encode(texts)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        write_npy(self.cache_path, vectors)
        meta = self.current_meta()
        actual_model = getattr(embedder, "model_name", self.model)
        meta["model"] = actual_model
        meta["backend"] = "hash_fallback" if "hash" in actual_model.lower() else "sentence_transformers"
        meta["embedding_dim"] = len(vectors[0]) if vectors else 0
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.vectors = vectors
        self.meta = meta
        self.error = None
        return meta

    def load(self) -> bool:
        try:
            if not self.cache_path.exists() or not self.meta_path.exists():
                self.error = "embedding cache missing; run scripts/build_embeddings.py"
                return False
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            expected = self.current_meta()
            if meta.get("vocab_rows") != expected["vocab_rows"] or meta.get("entry_ids") != expected["entry_ids"] or meta.get("text_hash") != expected["text_hash"]:
                self.error = "embedding cache does not match current vocab; rebuild required"
                return False
            self.vectors = read_npy(self.cache_path)
            self.meta = meta
            self.error = None
            return True
        except Exception as exc:
            self.error = str(exc)
            self.vectors = None
            return False

    def status(self, enabled: bool) -> dict[str, Any]:
        rows = self.meta.get("vocab_rows") if self.meta else None
        return {
            "enabled": enabled,
            "loaded": self.vectors is not None,
            "model": self.model,
            "cache_path": str(self.cache_path),
            "rows": rows,
            "backend": self.meta.get("backend") if self.meta else None,
            "embedding_dim": self.meta.get("embedding_dim") if self.meta else None,
            "error": self.error,
        }

    def vector_for_id(self, entry_id: int) -> list[float] | None:
        if self.vectors is None or self.meta is None:
            return None
        try:
            index = self.meta["entry_ids"].index(entry_id)
        except ValueError:
            return None
        return self.vectors[index]

