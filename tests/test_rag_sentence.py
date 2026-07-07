import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.embedding_store import EmbeddingStore, HashingEmbedder, embedding_text
from app.main import app
from app.rag_reranker import RAGReranker
from app.sentence_composer import ConfirmedWord, SentenceComposer, SessionSentenceState
from app.storage import load_lite_vocab


def test_embedding_text_contains_required_sections() -> None:
    entry = load_lite_vocab()[0]
    text = embedding_text(entry)
    assert "璇嶆潯锛? in text
    assert "鍔ㄤ綔鎻忚堪锛? in text
    assert "妫€绱㈡枃鏈細" in text
    assert "鍔ㄤ綔鍩哄厓锛? in text


def test_embedding_cache_meta_detects_vocab_hash(tmp_path: Path) -> None:
    store = EmbeddingStore(cache_path=tmp_path / "emb.npy", meta_path=tmp_path / "meta.json")
    meta = store.build(embedder=HashingEmbedder(dim=16))
    assert meta["vocab_rows"] == 109
    assert store.load() is True
    data = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    data["vocab_rows"] = -1
    (tmp_path / "meta.json").write_text(json.dumps(data), encoding="utf-8")
    assert store.load() is False


def test_fake_rerank_is_reproducible_and_respects_low_primitive_score(tmp_path: Path) -> None:
    store = EmbeddingStore(cache_path=tmp_path / "emb.npy", meta_path=tmp_path / "meta.json")
    store.build(embedder=HashingEmbedder(dim=16))
    assert store.load()
    reranker = RAGReranker(store, enabled=True, embedder=HashingEmbedder(dim=16), min_primitive_score=0.55)
    candidates = [
        {"id": 357, "word_base": "鍘曟墍", "score": 0.9, "start_ts": "1", "end_ts": "2", "span_summary": {"field_modes": {}}},
        {"id": 3048, "word_base": "姘?, "score": 0.2, "start_ts": "1", "end_ts": "2", "span_summary": {"field_modes": {}}},
    ]
    result = reranker.rerank(candidates)
    assert result.debug["applied"] is True
    low = next(item for item in result.candidates if item["id"] == 3048)
    assert low["rag_score"] == 0.0
    assert low["final_score"] == 0.2


def test_sentence_fallback_without_llm_key() -> None:
    composer = SentenceComposer(enabled=False)
    state = SessionSentenceState(confirmed_words=[ConfirmedWord(1, "鍘曟墍", 0.8, "1", "2")])
    composer.compose_state(state)
    assert state.last_sentence == "鍘曟墍"
    assert state.last_sentence_status == "fallback"


def test_sentence_validation_rejects_outside_core_word() -> None:
    composer = SentenceComposer(enabled=False)
    state = SessionSentenceState(confirmed_words=[ConfirmedWord(1, "鍘曟墍", 0.8, "1", "2")])
    try:
        composer._validate_llm_result({"sentence": "鍚冮キ", "used_words": ["鍚冮キ"]}, state)
    except ValueError as exc:
        assert "outside" in str(exc)
    else:
        raise AssertionError("expected validation failure")


def test_health_contains_embedding_and_llm_status() -> None:
    with TestClient(app) as client:
        data = client.get("/health").json()
    assert "embedding" in data
    assert "llm" in data
    assert data["embedding"]["enabled"] is True
    assert data["llm"]["configured"] is False


def test_sentence_api_after_confirmed_and_reset() -> None:
    primitive = {
        "hand_count": 1,
        "dominant_side": "signer_right",
        "location": "signer_center_upper",
        "movement": "left_right",
        "bimanual_relation": "single_hand",
        "dominant_shape": "five",
        "nondominant_shape": "no_hand",
    }
    with TestClient(app) as client:
        client.post("/api/v1/debug/reset/sentence-api")
        for i in range(1, 7):
            client.post("/api/v1/stream/frame", json={"session_id": "sentence-api", "timestamp": f"260701-143012-{i:03d}", "primitive": primitive, "debug": True})
        sentence = client.get("/api/v1/sentence/sentence-api").json()
        assert sentence["ok"] is True
        assert sentence["status"] in {"fallback", "empty"}
        assert sentence["sentence"] in {"", "鍘曟墍"}
        reset = client.post("/api/v1/sentence/reset/sentence-api").json()
        assert reset["reset"] is True

