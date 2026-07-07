from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.embedding_store import Embedder, EmbeddingStore, HashingEmbedder, cosine, make_embedder
from app.runtime_config import CONFIG


def query_text_from_candidate(candidate: dict[str, Any]) -> str:
    summary = candidate.get("span_summary") or {}
    modes = summary.get("field_modes") or {}
    return "\n".join(
        [
            f"鎵嬫暟閲忥細{modes.get('hand_count', 'unknown')}",
            f"涓绘墜浣嶇疆锛歿modes.get('location', 'unknown')}",
            f"杩愬姩锛歿modes.get('movement', 'unknown')}",
            f"鍙屾墜鍏崇郴锛歿modes.get('bimanual_relation', 'unknown')}",
            f"涓绘墜鎵嬪瀷锛歿modes.get('dominant_shape', 'unknown')}",
            f"鍓墜鎵嬪瀷锛歿modes.get('nondominant_shape', 'unknown')}",
            f"鍊欓€夊姩浣滄憳瑕侊細{summary}",
        ]
    )


@dataclass
class RerankResult:
    candidates: list[dict[str, Any]]
    debug: dict[str, Any]


class RAGReranker:
    def __init__(
        self,
        store: EmbeddingStore,
        enabled: bool = CONFIG.enable_rag_rerank,
        weight: float = CONFIG.rag_weight,
        min_primitive_score: float = CONFIG.rag_min_primitive_score,
        embedder: Embedder | None = None,
    ) -> None:
        self.store = store
        self.enabled = enabled
        self.weight = weight
        self.min_primitive_score = min_primitive_score
        self.embedder = embedder
        self._loaded_embedder: Embedder | None = None


    def _query_embedder(self) -> Embedder:
        if self.embedder is not None:
            return self.embedder
        if self._loaded_embedder is not None:
            return self._loaded_embedder
        dim = (self.store.meta or {}).get("embedding_dim") or 128
        # Keep request-path reranking offline-only. Cached entry vectors are loaded at startup,
        # and query vectors use a stable local hashing embedder to avoid first-request network probes.
        self._loaded_embedder = HashingEmbedder(model_name="query-hash-local-v1", dim=int(dim))
        return self._loaded_embedder

    def rerank(self, candidates: list[dict[str, Any]]) -> RerankResult:
        primitive_top1 = candidates[0]["word_base"] if candidates else None
        if not self.enabled:
            return RerankResult(candidates, {"enabled": False, "applied": False, "reason": "disabled", "primitive_top1": primitive_top1, "reranked_top1": primitive_top1, "rank_changed": False})
        if self.store.vectors is None:
            for candidate in candidates:
                candidate.setdefault("primitive_score", candidate.get("score", 0.0))
                candidate.setdefault("rag_score", None)
                candidate.setdefault("final_score", candidate.get("score", 0.0))
                candidate.setdefault("rerank_applied", False)
            return RerankResult(candidates, {"enabled": True, "applied": False, "reason": self.store.error or "embedding_not_loaded", "primitive_top1": primitive_top1, "reranked_top1": primitive_top1, "rank_changed": False})
        reranked = []
        for candidate in candidates:
            primitive_score = float(candidate.get("score", 0.0))
            query_vector = self._query_embedder().encode([query_text_from_candidate(candidate)])[0]
            entry_vector = self.store.vector_for_id(int(candidate["id"]))
            rag_score = cosine(query_vector, entry_vector or []) if primitive_score >= self.min_primitive_score else 0.0
            final_score = primitive_score if primitive_score < self.min_primitive_score else (1 - self.weight) * primitive_score + self.weight * rag_score
            updated = dict(candidate)
            updated["primitive_score"] = round(primitive_score, 4)
            updated["rag_score"] = round(rag_score, 4)
            updated["final_score"] = round(final_score, 4)
            updated["score"] = round(final_score, 4)
            updated["rag_text"] = query_text_from_candidate(candidate)
            updated["embedding_model"] = self.store.model
            updated["rerank_applied"] = primitive_score >= self.min_primitive_score
            breakdown = dict(updated.get("score_breakdown") or {})
            breakdown["primitive_score"] = round(primitive_score, 4)
            breakdown["rag_score"] = round(rag_score, 4)
            breakdown["reranked_final_score"] = round(final_score, 4)
            updated["score_breakdown"] = breakdown
            reranked.append(updated)
        reranked.sort(key=lambda item: (-item["score"], item["id"]))
        reranked_top1 = reranked[0]["word_base"] if reranked else None
        return RerankResult(
            reranked,
            {
                "enabled": True,
                "applied": True,
                "primitive_top1": primitive_top1,
                "reranked_top1": reranked_top1,
                "rank_changed": primitive_top1 != reranked_top1,
                "query_embedder": getattr(self._query_embedder(), "model_name", None),
                "embedding_backend": (self.store.meta or {}).get("backend"),
            },
        )

