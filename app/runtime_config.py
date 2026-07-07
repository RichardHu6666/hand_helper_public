from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path("/root/sign_cloud_v1")
if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class RuntimeConfig:
    enable_rag_rerank: bool = env_bool("ENABLE_RAG_RERANK", True)
    enable_llm_sentence: bool = env_bool("ENABLE_LLM_SENTENCE", False)
    auto_build_embed_cache: bool = env_bool("AUTO_BUILD_EMBED_CACHE", False)
    embed_model: str = os.getenv("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
    embed_device: str = os.getenv("EMBED_DEVICE", "cpu")
    embed_cache_path: str = os.getenv("EMBED_CACHE_PATH", str(PROJECT_ROOT / "data/vocab_embeddings_bge_small_zh_v1.npy"))
    embed_meta_path: str = os.getenv("EMBED_META_PATH", str(PROJECT_ROOT / "data/vocab_embeddings_meta.json"))
    rag_top_k: int = env_int("RAG_TOP_K", 8)
    rag_weight: float = env_float("RAG_WEIGHT", 0.12)
    rag_min_primitive_score: float = env_float("RAG_MIN_PRIMITIVE_SCORE", 0.55)
    llm_provider: str = os.getenv("LLM_PROVIDER", "deepseek")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    llm_timeout_sec: int = env_int("LLM_TIMEOUT_SEC", 30)
    llm_max_candidates: int = env_int("LLM_MAX_CANDIDATES", 5)


CONFIG = RuntimeConfig()

